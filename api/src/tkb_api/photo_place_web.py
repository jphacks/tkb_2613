"""Optional, consent-gated Brave Place Search for public facility names only."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from typing import Any, NamedTuple

import httpx
from pydantic import SecretStr

from tkb_api.public_web_identity import _public_https_url
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    PhotoPlaceCandidate,
    PhotoPlaceEvidence,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceRelation,
    PhotoPlaceResult,
    PhotoPlaceSource,
    PhotoPlaceStatus,
    PhotoPlaceType,
)
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.photo_place import place_candidate_from_record

BRAVE_PLACE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/local/place_search"
MAX_QUERIES_PER_DIAGNOSIS = 3
MAX_RESULTS_PER_QUERY = 5
MAX_DISPLAYED_CANDIDATES = 50
MAX_RESPONSE_BYTES = 128_000
REQUEST_TIMEOUT_SECONDS = 2.5
MIN_CLUE_CONFIDENCE = 0.8
MIN_STATION_CONFIDENCE = 0.85
_SAFE_QUERY_CHARACTERS = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff ・ー-]+\Z")
_SENSITIVE_OR_UNCLEAR = re.compile(
    r"(?:https?://|www\.|@|\b\d|\bx\b|\b[a-z0-9._%+-]+@[a-z0-9.-]+\b|"
    r"(?:電話|住所|郵便|〒|番地|丁目|号))",
    re.IGNORECASE,
)
# 店名・地標名ではなく文章に見えるもの（助詞「を」「へ」や述語の語尾）は送らない。
# 名前を取りこぼしても Brave を呼ばないだけで安全側に倒れる。
_SENTENCE_LIKE = re.compile(
    r"[をへ]|(?:ました|ません|ます|です|でした|だった|ている|ていた|てる|てきた|行った|来た)\Z"
)


# Brave候補の裏付けに使ってよい、公的機関が出すローカル索引のデータセット。
# Overture など民間・集合データは名称が一致しても裏付けにしない。
OFFICIAL_PLACE_DATASETS = frozenset({"P05-22"})
# JIS X 0401 の都道府県コード順（01〜47）。
_PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)  # fmt: skip


class _ExternalCandidate(NamedTuple):
    candidate: PhotoPlaceCandidate
    region: str | None
    locality: str | None


def _query(value: str) -> str | None:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 2 <= len(normalized) <= 50:
        return None
    if not _SAFE_QUERY_CHARACTERS.fullmatch(normalized) or _SENSITIVE_OR_UNCLEAR.search(normalized):
        return None
    if _SENTENCE_LIKE.search(normalized):
        return None
    if "x" in normalized.casefold():
        return None
    return normalized


def _eligible_query_clues(clues: Sequence[Clue]) -> dict[str, list[int]]:
    eligible: dict[str, list[int]] = {}
    for index, clue in enumerate(clues):
        if (
            clue.image_index is None
            or clue.region is None
            or clue.source not in {ClueSource.OCR, ClueSource.VLM}
            or clue.type not in {ClueType.SHOP, ClueType.LANDMARK, ClueType.STATION_SIGN}
        ):
            continue
        threshold = (
            MIN_STATION_CONFIDENCE if clue.type is ClueType.STATION_SIGN else MIN_CLUE_CONFIDENCE
        )
        if clue.confidence < threshold:
            continue
        query = _query(clue.value)
        if query is None:
            continue
        eligible.setdefault(query, []).append(index)
    return eligible


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _safe_https_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    parsed = _public_https_url(value)
    return parsed[0] if parsed is not None else None


def _unavailable(result: PhotoPlaceResult, reason: str) -> PhotoPlaceResult:
    status = result.status
    if not result.candidates:
        status = PhotoPlaceStatus.UNAVAILABLE
    return PhotoPlaceResult.model_validate(
        {
            **result.model_dump(mode="python"),
            "status": status,
            "lookup_status": PhotoPlaceLookupStatus.UNAVAILABLE,
            "reason_codes": [reason],
        }
    )


def mark_photo_place_lookup_unavailable(
    results: Sequence[PhotoPlaceResult], clues: Sequence[Clue], reason: str
) -> list[PhotoPlaceResult]:
    """Mark only unresolved images that have a safe queryable visual clue."""
    unresolved = {
        (result.post_id, result.image_index)
        for result in results
        if result.status in {PhotoPlaceStatus.UNKNOWN, PhotoPlaceStatus.AMBIGUOUS}
    }
    eligible = {
        (clues[index].post_id, clues[index].image_index)
        for indices in _eligible_query_clues(clues).values()
        for index in indices
    } & unresolved
    return [
        _unavailable(result, reason) if (result.post_id, result.image_index) in eligible else result
        for result in results
    ]


def _external_candidates(
    payload: object, query: str, clue_indices: Sequence[int]
) -> list[_ExternalCandidate]:
    if not isinstance(payload, dict):
        return []
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []
    candidates: list[_ExternalCandidate] = []
    seen: set[str] = set()
    for item in raw_results[:MAX_RESULTS_PER_QUERY]:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        address = item.get("postal_address")
        # country=JP scopes the search but does not guarantee that every hit is in Japan.
        if not isinstance(address, dict) or str(address.get("country", "")).upper() != "JP":
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if _normalized_name(title) != _normalized_name(query):
            continue
        source_url = _safe_https_url(item.get("url") or item.get("provider_url"))
        if source_url is None:
            continue
        label = title.strip()[:300]
        # Brave's result ID is temporary (~8 hours); never persist or expose it.
        identity = hashlib.sha256(f"{_normalized_name(label)}\n{source_url}".encode()).hexdigest()[
            :24
        ]
        place_id = f"brave-place:{identity}"
        if place_id in seen:
            continue
        seen.add(place_id)
        locality = address.get("addressLocality")
        region = address.get("addressRegion")
        coarse_area = (
            " ".join(
                str(part).strip()
                for part in (region, locality)
                if isinstance(part, str) and part.strip()
            )[:200]
            or None
        )
        source_id = f"brave-place-search:{identity}"
        candidate = PhotoPlaceCandidate(
            place_id=place_id,
            label=label,
            place_type=PhotoPlaceType.FACILITY,
            photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
            area_label=coarse_area,
            score=None,
            evidence=[PhotoPlaceEvidence(kind="clue", clue_index=index) for index in clue_indices],
            source_ids=[source_id],
            sources=[
                PhotoPlaceSource(
                    source_id=source_id,
                    provider="Brave Search Place Search",
                    dataset="unverified external place result",
                    license_id=None,
                    record_id=None,
                    version=None,
                    attribution="Brave Search result; not independently verified",
                    source_url=source_url,
                )
            ],
        )
        candidates.append(
            _ExternalCandidate(
                candidate,
                region.strip() if isinstance(region, str) else None,
                locality.strip() if isinstance(locality, str) else None,
            )
        )
    return candidates


def _official_record_area(candidate: PhotoPlaceCandidate) -> tuple[str, str] | None:
    """Return (都道府県, 市区町村) only for a single-source official local record."""
    if len(candidate.sources) != 1 or not candidate.area_label:
        return None
    source = candidate.sources[0]
    if source.dataset not in OFFICIAL_PLACE_DATASETS or source.record_id is None:
        return None
    # P05 の record_id は「P05-22_<都道府県コード>_<連番>」。都道府県は行政区域コード由来。
    match = re.fullmatch(rf"{re.escape(source.dataset)}_(\d{{2}})_\d+", source.record_id)
    if match is None:
        return None
    code = int(match.group(1))
    if not 1 <= code <= len(_PREFECTURES):
        return None
    return _PREFECTURES[code - 1], candidate.area_label


def _trim_keeping_corroborations(
    candidates: Sequence[PhotoPlaceCandidate],
) -> list[PhotoPlaceCandidate]:
    """表示上限で切るとき、裏付けのある外部候補とその参照先を先に残す（並び順は保つ）。

    同名の公的施設が上限を超える名前（「中央公民館」など）でも、裏付けが切り捨てられないようにする。
    """
    keep: set[str] = set()
    for candidate in candidates:
        if candidate.corroborated_by and len(keep) + 2 <= MAX_DISPLAYED_CANDIDATES:
            keep.update([candidate.place_id, *candidate.corroborated_by])
    for candidate in candidates:
        if len(keep) >= MAX_DISPLAYED_CANDIDATES:
            break
        keep.add(candidate.place_id)
    return [candidate for candidate in candidates if candidate.place_id in keep]


def _area_key(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _area_record_candidates(
    gazetteer: Gazetteer, external: _ExternalCandidate
) -> list[PhotoPlaceCandidate]:
    """Brave結果の名称と市区町村でローカルの公的記録を引く（表示上限とは無関係）。"""
    if not external.locality:
        return []
    locality = external.locality.strip()
    if len(locality) < 2 or not locality.endswith(("市", "区", "町", "村")):
        return []
    clue_index = next(
        (e.clue_index for e in external.candidate.evidence if e.clue_index is not None), None
    )
    if clue_index is None:
        return []
    candidates = []
    for row in gazetteer.places_named_in_area(external.candidate.label, locality):
        candidate = place_candidate_from_record(row, clue_index)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _corroborating_place_id(
    external: _ExternalCandidate, local_candidates: Sequence[PhotoPlaceCandidate]
) -> str | None:
    """名称・都道府県・市区町村がすべて一致する公的記録がちょうど1件のときだけ返す。

    同名の市区町村（府中市など）を取り違えないよう、都道府県が分からなければ裏付けにしない。
    """
    if not external.region or not external.locality:
        return None
    region = _area_key(external.region)
    locality = _area_key(external.locality)
    if len(locality) < 2 or not locality.endswith(("市", "区", "町", "村")):
        return None
    name = _normalized_name(external.candidate.label)
    matches = []
    for local in local_candidates:
        area = _official_record_area(local)
        if area is None or _normalized_name(local.label) != name:
            continue
        prefecture, municipality = area
        # 「北区」だけでは大阪市北区と堺市北区を区別できないので、末尾一致は使わない。
        if _area_key(prefecture) == region and _area_key(municipality) == locality:
            matches.append(local.place_id)
    return matches[0] if len(matches) == 1 else None


async def search_photo_places(
    local_results: Sequence[PhotoPlaceResult],
    clues: Sequence[Clue],
    api_key: SecretStr,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    gazetteer: Gazetteer | None = None,
) -> list[PhotoPlaceResult]:
    """Use only up to three explicitly consented, public facility/station names per diagnosis."""
    key = api_key.get_secret_value().strip()
    needs_lookup = {
        (result.post_id, result.image_index)
        for result in local_results
        if result.status.value in {"unknown", "ambiguous"}
    }
    clue_indices_by_query = _eligible_query_clues(clues)
    eligible_images = {
        (clues[index].post_id, clues[index].image_index)
        for indices in clue_indices_by_query.values()
        for index in indices
    } & needs_lookup
    if not needs_lookup:
        return list(local_results)
    if not eligible_images:
        return list(local_results)
    if not key:
        return [
            _unavailable(result, "photo_place_search_unavailable")
            if (result.post_id, result.image_index) in eligible_images
            else result
            for result in local_results
        ]

    selected: dict[str, list[tuple[str, int]]] = {}
    selected_images: set[tuple[str, int]] = set()
    for query, clue_indices in clue_indices_by_query.items():
        keys: set[tuple[str, int]] = set()
        for index in clue_indices:
            image_index = clues[index].image_index
            if image_index is not None and (clues[index].post_id, image_index) in needs_lookup:
                keys.add((clues[index].post_id, image_index))
        for result_key in keys:
            selected_images.add(result_key)
            selected.setdefault(query, []).append(result_key)
    selected = dict(list(selected.items())[:MAX_QUERIES_PER_DIAGNOSIS])
    if not selected:
        return list(local_results)

    candidates_by_image: dict[tuple[str, int], list[_ExternalCandidate]] = {}
    searched_images: set[tuple[str, int]] = set()
    failed_images: set[tuple[str, int]] = set()
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    ) as client:
        for query, image_keys in selected.items():
            try:
                async with client.stream(
                    "GET",
                    BRAVE_PLACE_SEARCH_ENDPOINT,
                    params={
                        "q": query,
                        "country": "JP",
                        "count": MAX_RESULTS_PER_QUERY,
                        "search_lang": "ja",
                        "ui_lang": "ja-JP",
                        "spellcheck": "false",
                    },
                    headers={"x-subscription-token": key, "accept": "application/json"},
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        != "application/json"
                    ):
                        failed_images.update(image_keys)
                        continue
                    size = 0
                    chunks: list[bytes] = []
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            failed_images.update(image_keys)
                            chunks = []
                            break
                        chunks.append(chunk)
                payload: Any = json.loads(b"".join(chunks))
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                failed_images.update(image_keys)
                continue
            for image_key in image_keys:
                searched_images.add(image_key)
                image_clue_indices = [
                    index
                    for index in clue_indices_by_query[query]
                    if (clues[index].post_id, clues[index].image_index) == image_key
                ]
                found = _external_candidates(payload, query, image_clue_indices)
                candidates_by_image.setdefault(image_key, []).extend(found)

    updated: list[PhotoPlaceResult] = []
    for result in local_results:
        result_key = (result.post_id, result.image_index)
        if result_key not in needs_lookup or result_key not in searched_images:
            if result_key in failed_images:
                updated.append(_unavailable(result, "photo_place_search_failed"))
            elif result_key in selected_images and result_key not in searched_images:
                updated.append(_unavailable(result, "photo_place_query_limit"))
            else:
                updated.append(result)
            continue
        merged = list(result.candidates)
        for external in candidates_by_image.get(result_key, []):
            pool = list(result.candidates)
            if gazetteer is not None:
                # ローカル検索は同名50件で打ち切られるため、裏付けは名称と市区町村で直接引く。
                known = {candidate.place_id for candidate in pool}
                pool.extend(
                    extra
                    for extra in _area_record_candidates(gazetteer, external)
                    if extra.place_id not in known
                )
            corroborating = _corroborating_place_id(external, pool)
            if corroborating is not None:
                merged.extend(
                    extra
                    for extra in pool[len(result.candidates) :]
                    if extra.place_id == corroborating
                )
            merged.append(
                external.candidate.model_copy(update={"corroborated_by": [corroborating]})
                if corroborating is not None
                else external.candidate
            )
        merged_by_id = {candidate.place_id: candidate for candidate in merged}
        candidates = list(merged_by_id.values())
        if len(candidates) == 0:
            status = PhotoPlaceStatus.UNKNOWN
        elif len(candidates) == 1:
            status = PhotoPlaceStatus.CANDIDATE
        else:
            status = PhotoPlaceStatus.AMBIGUOUS
        granularity = (
            PhotoPlaceGranularity.FACILITY
            if candidates
            and all(candidate.place_type is PhotoPlaceType.FACILITY for candidate in candidates)
            else result.granularity
        )
        if len(candidates) > MAX_DISPLAYED_CANDIDATES:
            candidates = _trim_keeping_corroborations(candidates)
        reason_codes: list[str] = []
        if len(candidates) > 1:
            reason_codes.append("multiple_matches")
        if len(merged_by_id) > MAX_DISPLAYED_CANDIDATES:
            reason_codes.append("too_many_matches")
        if not candidates:
            reason_codes.append("no_external_match")
        updated.append(
            PhotoPlaceResult.model_validate(
                {
                    **result.model_dump(mode="python"),
                    "status": status,
                    "granularity": granularity,
                    "candidates": candidates,
                    "lookup_status": PhotoPlaceLookupStatus.WEB_SEARCHED,
                    "reason_codes": reason_codes,
                }
            )
        )
    return updated
