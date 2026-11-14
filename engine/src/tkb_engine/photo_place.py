"""Local, conservative place candidates for objects visible in post images."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence

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
    Post,
)
from tkb_engine.gazetteer import MAX_PLACE_NAME_MATCHES, Gazetteer

STATION_OCR_MIN = 0.8
STATION_VLM_MIN = 0.5
ADDRESS_OCR_MIN = 0.9
POI_CLUE_MIN = 0.65


def infer_photo_places(
    posts: Sequence[Post], clues: Sequence[Clue], gazetteer: Gazetteer
) -> list[PhotoPlaceResult]:
    """Return per-image visible-place candidates; never camera/home location claims."""
    indexed: dict[tuple[str, int], list[tuple[int, Clue]]] = defaultdict(list)
    for clue_index, clue in enumerate(clues):
        if clue.image_index is not None:
            indexed[(clue.post_id, clue.image_index)].append((clue_index, clue))
    results: list[PhotoPlaceResult] = []
    for post in posts:
        for image in post.images:
            image_clues = indexed.get((post.post_id, image.index), [])
            candidates = _station_candidates(image_clues, gazetteer)
            candidates.extend(_postal_candidates(image_clues, gazetteer))
            poi_candidates, poi_truncated = _poi_candidates(image_clues, gazetteer)
            candidates.extend(poi_candidates)
            candidates = _deduplicate(candidates)
            if len(candidates) == 1:
                status, reasons = PhotoPlaceStatus.CANDIDATE, []
            elif len(candidates) > 1 or poi_truncated:
                reasons = ["multiple_matches"]
                if poi_truncated:
                    reasons.append("too_many_matches")
                status = PhotoPlaceStatus.AMBIGUOUS
            else:
                status, reasons = PhotoPlaceStatus.UNKNOWN, ["insufficient_local_evidence"]
            types = {candidate.place_type for candidate in candidates}
            granularity = (
                _granularity(next(iter(types)))
                if len(types) == 1
                else PhotoPlaceGranularity.UNKNOWN
            )
            results.append(
                PhotoPlaceResult(
                    post_id=post.post_id,
                    image_index=image.index,
                    status=status,
                    granularity=granularity,
                    candidates=candidates,
                    reason_codes=reasons,
                    lookup_status=PhotoPlaceLookupStatus.LOCAL_ONLY,
                )
            )
    return results


def _station_candidates(
    image_clues: list[tuple[int, Clue]], gazetteer: Gazetteer
) -> list[PhotoPlaceCandidate]:
    ocr = [
        (i, c)
        for i, c in image_clues
        if c.type is ClueType.STATION_SIGN
        and c.source is ClueSource.OCR
        and c.confidence >= STATION_OCR_MIN
    ]
    vlm = [
        (i, c)
        for i, c in image_clues
        if c.type is ClueType.STATION_SIGN
        and c.source is ClueSource.VLM
        and c.confidence >= STATION_VLM_MIN
    ]
    result: dict[str, PhotoPlaceCandidate] = {}
    for ocr_index, ocr_clue in ocr:
        name = _station_name(ocr_clue.value)
        if not name or "x" in name.casefold():
            continue
        rows = [
            row
            for row in gazetteer.stations
            if _station_name(str(row.get("station_name", ""))) == name
        ]
        for vlm_index, vlm_clue in vlm:
            if _station_name(vlm_clue.value) != name or not _overlap(
                ocr_clue.region, vlm_clue.region
            ):
                continue
            for row in rows:
                identity = str(
                    row.get("station_code")
                    or row.get("station_id")
                    or hashlib.sha256(
                        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode(
                            "utf-8"
                        )
                    ).hexdigest()[:20]
                )
                place_id = f"station:{identity}"
                source = PhotoPlaceSource(
                    source_id=place_id,
                    provider="国土交通省 国土数値情報",
                    dataset="N02 鉄道",
                    license_id="CC-BY-4.0",
                    record_id=identity,
                    attribution="国土数値情報 鉄道データ（N02）",
                )
                candidate = PhotoPlaceCandidate(
                    place_id=place_id,
                    label=f"{name}駅",
                    place_type=PhotoPlaceType.STATION,
                    photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
                    score=None,
                    evidence=[
                        PhotoPlaceEvidence(kind="clue", clue_index=ocr_index),
                        PhotoPlaceEvidence(kind="clue", clue_index=vlm_index),
                    ],
                    source_ids=[place_id],
                    sources=[source],
                )
                result[place_id] = candidate
    return list(result.values())


def _postal_candidates(
    image_clues: list[tuple[int, Clue]], gazetteer: Gazetteer
) -> list[PhotoPlaceCandidate]:
    result: dict[str, PhotoPlaceCandidate] = {}
    for clue_index, clue in image_clues:
        if (
            clue.type is not ClueType.POSTAL_CODE
            or clue.source is not ClueSource.OCR
            or clue.confidence < ADDRESS_OCR_MIN
        ):
            continue
        code = unicodedata.normalize("NFKC", clue.value).replace("-", "").strip()
        if not re.fullmatch(r"\d{7}", code):
            continue
        for row in gazetteer.postal_rows(code):
            city, town = str(row.get("city", "")).strip(), str(row.get("town", "")).strip()
            if not city or not town:
                continue
            place_id = f"postal:{row.get('muni_code', '')}:{code}:{town}"
            source = PhotoPlaceSource(
                source_id=f"japanpost:{code}",
                provider="日本郵便株式会社",
                dataset="郵便番号データ",
                license_id=None,
                record_id=code,
                attribution="日本郵便株式会社 郵便番号データ",
            )
            result[place_id] = PhotoPlaceCandidate(
                place_id=place_id,
                label=f"{city}{town}",
                place_type=PhotoPlaceType.AREA,
                photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
                area_label=city,
                score=None,
                evidence=[PhotoPlaceEvidence(kind="clue", clue_index=clue_index)],
                source_ids=[source.source_id],
                sources=[source],
            )
    return list(result.values())


def _poi_candidates(
    image_clues: list[tuple[int, Clue]], gazetteer: Gazetteer
) -> tuple[list[PhotoPlaceCandidate], bool]:
    observed_types = {ClueType.SHOP, ClueType.LANDMARK, ClueType.ORG_TEXT, ClueType.PLACE_TEXT}
    result: dict[str, PhotoPlaceCandidate] = {}
    truncated = False
    for clue_index, clue in image_clues:
        if (
            clue.type not in observed_types
            or clue.source not in {ClueSource.OCR, ClueSource.VLM}
            or clue.confidence < POI_CLUE_MIN
        ):
            continue
        matches = gazetteer.places_named(clue.value)
        truncated = truncated or len(matches) > MAX_PLACE_NAME_MATCHES
        for row in matches[:MAX_PLACE_NAME_MATCHES]:
            place_id, label = row.get("place_id"), row.get("label")
            if (
                not isinstance(place_id, str)
                or not isinstance(label, str)
                or not place_id
                or not label
            ):
                continue
            raw_sources = row.get("sources", [])
            sources = (
                [
                    PhotoPlaceSource.model_validate(source)
                    for source in raw_sources
                    if isinstance(source, dict)
                ]
                if isinstance(raw_sources, list)
                else []
            )
            # Records with unknown or mixed source licensing remain in the index but are
            # withheld from candidate generation until their provenance is resolved.
            if not sources or any(source.license_id is None for source in sources):
                continue
            source_ids = row.get("source_ids", [])
            if not isinstance(source_ids, list) or not source_ids:
                source_ids = [source.source_id for source in sources] or [f"local-poi:{place_id}"]
            category = row.get("basic_category")
            place_type = (
                PhotoPlaceType.LANDMARK
                if str(category).casefold() == "landmark"
                else PhotoPlaceType.FACILITY
            )
            candidate = PhotoPlaceCandidate(
                place_id=place_id,
                label=label,
                place_type=place_type,
                photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
                area_label=row.get("area_label")
                if isinstance(row.get("area_label"), str)
                else None,
                score=None,
                evidence=[PhotoPlaceEvidence(kind="clue", clue_index=clue_index)],
                source_ids=[str(source_id) for source_id in source_ids],
                sources=sources,
            )
            existing = result.get(place_id)
            if existing is None:
                result[place_id] = candidate
            elif candidate.evidence[0] not in existing.evidence:
                result[place_id] = existing.model_copy(
                    update={"evidence": [*existing.evidence, *candidate.evidence]}
                )
    return list(result.values()), truncated


def _deduplicate(candidates: list[PhotoPlaceCandidate]) -> list[PhotoPlaceCandidate]:
    unique: dict[str, PhotoPlaceCandidate] = {}
    for candidate in candidates:
        previous = unique.get(candidate.place_id)
        if previous is None:
            unique[candidate.place_id] = candidate
        elif candidate.evidence[0] not in previous.evidence:
            unique[candidate.place_id] = previous.model_copy(
                update={"evidence": [*previous.evidence, *candidate.evidence]}
            )
    return list(unique.values())


def _station_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().removesuffix("駅").strip()


def _overlap(
    left: tuple[int, int, int, int] | None, right: tuple[int, int, int, int] | None
) -> bool:
    return bool(
        left
        and right
        and left[0] < right[2]
        and right[0] < left[2]
        and left[1] < right[3]
        and right[1] < left[3]
    )


def _granularity(place_type: PhotoPlaceType) -> PhotoPlaceGranularity:
    if place_type is PhotoPlaceType.STATION:
        return PhotoPlaceGranularity.STATION
    if place_type in {PhotoPlaceType.FACILITY, PhotoPlaceType.LANDMARK}:
        return PhotoPlaceGranularity.FACILITY
    if place_type is PhotoPlaceType.ADDRESS:
        return PhotoPlaceGranularity.ADDRESS
    if place_type is PhotoPlaceType.AREA:
        return PhotoPlaceGranularity.AREA
    return PhotoPlaceGranularity.UNKNOWN
