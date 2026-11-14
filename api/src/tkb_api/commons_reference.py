"""Opt-in Commons reference lookup for strict near-duplicate image checks.

Only coordinates from a unique, licensed local POI candidate reach Commons. The user's
image bytes are compared in process and are never sent to Wikimedia or an image service.
"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable, Sequence
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    PhotoPlaceEvidence,
    PhotoPlaceLookupStatus,
    PhotoPlaceResult,
    PhotoPlaceSource,
    PhotoPlaceStatus,
    Post,
)
from tkb_detect.near_duplicate import is_near_duplicate, perceptual_hash
from tkb_engine.gazetteer import Gazetteer

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_HOST = "commons.wikimedia.org"
THUMB_HOST = "upload.wikimedia.org"
COMMONS_USER_AGENT = "Miitsuketa/1.0 (JPHACKS 2026; public-place reference verification)"
MAX_CANDIDATES_PER_DIAGNOSIS = 3
MAX_REFERENCE_IMAGES_PER_DIAGNOSIS = 3
MAX_SEARCH_RADIUS_METERS = 1_000
MAX_THUMBNAIL_BYTES = 512 * 1024
MAX_SOURCE_IMAGE_BYTES = 4 * 1024 * 1024
MAX_HTTP_REQUESTS_PER_DIAGNOSIS = MAX_CANDIDATES_PER_DIAGNOSIS + MAX_REFERENCE_IMAGES_PER_DIAGNOSIS
REQUEST_TIMEOUT_SECONDS = 5.0
MIN_CLUE_CONFIDENCE = 0.65
PRIVATE_PLACE_CATEGORIES = {
    "apartment",
    "apartments",
    "dwelling",
    "home",
    "private_residence",
    "residence",
    "residential",
    "residential_building",
}

# Deny share-alike/GFDL and unrecognized public-domain labels in the first version.
# A file is usable only when both machine-readable fields exactly agree.
ALLOWED_LICENSE_URLS = {
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
}
ALLOWED_CLUE_TYPES = {ClueType.SHOP, ClueType.LANDMARK, ClueType.STATION_SIGN}


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextOnly()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())[:500]


def _meta_value(metadata: Any, key: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    value = metadata.get(key)
    return _plain_text(value.get("value")) if isinstance(value, dict) else ""


def _allowed_rights(metadata: Any) -> tuple[str, str] | None:
    license_name = _meta_value(metadata, "LicenseShortName")
    license_url = _meta_value(metadata, "LicenseUrl")
    expected = ALLOWED_LICENSE_URLS.get(license_name)
    creator = _meta_value(metadata, "Artist")
    if not expected or license_url != expected or not creator:
        return None
    return license_name, creator


def _safe_url(value: Any, host: str) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        return None
    return value


def _eligible_clue(result: PhotoPlaceResult, clues: Sequence[Clue]) -> bool:
    for candidate in result.candidates:
        for evidence in candidate.evidence:
            index = evidence.clue_index
            if index is None or index >= len(clues):
                continue
            clue = clues[index]
            if (
                clue.post_id == result.post_id
                and clue.image_index == result.image_index
                and clue.type in ALLOWED_CLUE_TYPES
                and clue.source in {ClueSource.OCR, ClueSource.VLM}
                and clue.region is not None
                and clue.confidence >= MIN_CLUE_CONFIDENCE
            ):
                return True
    return False


def _local_candidate_coordinates(
    candidate: Any, gazetteer: Gazetteer
) -> tuple[float, float] | None:
    """Require the candidate's source IDs and licenses to match the local POI row."""
    record = gazetteer.place_record(candidate.place_id)
    if record is None:
        return None
    if not isinstance(record.get("label"), str) or record["label"] != candidate.label:
        return None
    if record.get("country") != "JP":
        return None
    categories: set[str] = set()
    basic_category = record.get("basic_category")
    if isinstance(basic_category, str):
        categories.add(basic_category.casefold().replace("-", "_").replace(" ", "_"))

    def collect_taxonomy(value: Any) -> None:
        if isinstance(value, str):
            categories.add(value.casefold().replace("-", "_").replace(" ", "_"))
        elif isinstance(value, dict):
            for child in value.values():
                collect_taxonomy(child)
        elif isinstance(value, list):
            for child in value:
                collect_taxonomy(child)

    collect_taxonomy(record.get("taxonomy"))
    if categories & PRIVATE_PLACE_CATEGORIES:
        return None
    raw_sources = record.get("sources")
    if not isinstance(raw_sources, list):
        return None
    local_sources = {
        source.get("source_id"): source
        for source in raw_sources
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    if not local_sources or not candidate.source_ids or not candidate.sources:
        return None
    if any(source_id not in local_sources for source_id in candidate.source_ids):
        return None
    for source in candidate.sources:
        local = local_sources.get(source.source_id)
        if (
            local is None
            or not source.license_id
            or source.license_id != local.get("license_id")
            or source.provider != local.get("provider")
            or source.dataset != local.get("dataset")
        ):
            return None
    try:
        latitude, longitude = float(record["latitude"]), float(record["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (20 <= latitude <= 46 and 122 <= longitude <= 154):
        return None
    return latitude, longitude


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    response.raise_for_status()
    output = bytearray()
    async for chunk in response.aiter_bytes():
        output.extend(chunk)
        if len(output) > max_bytes:
            raise ValueError("response too large")
    return bytes(output)


async def _commons_pages(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> list[dict[str, Any]]:
    async with client.stream(
        "GET",
        COMMONS_API,
        params={
            "action": "query",
            "format": "json",
            "generator": "geosearch",
            "ggscoord": f"{latitude:.6f}|{longitude:.6f}",
            "ggsradius": str(MAX_SEARCH_RADIUS_METERS),
            "ggsnamespace": "6",
            "ggslimit": "5",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": "256",
            "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Attribution",
        },
        headers={"User-Agent": COMMONS_USER_AGENT, "Accept": "application/json"},
    ) as response:
        body = await _read_limited(response, 256 * 1024)
    payload = json.loads(body)
    query = payload.get("query", {}) if isinstance(payload, dict) else {}
    pages = query.get("pages", {}) if isinstance(query, dict) else {}
    if not isinstance(pages, dict):
        return []
    return [
        page
        for _, page in sorted(pages.items(), key=lambda item: str(item[0]))
        if isinstance(page, dict)
    ]


async def _thumbnail(client: httpx.AsyncClient, url: str) -> bytes:
    async with client.stream("GET", url, headers={"User-Agent": COMMONS_USER_AGENT}) as response:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unexpected thumbnail content type")
        return await _read_limited(response, MAX_THUMBNAIL_BYTES)


async def search_commons_references(
    results: Sequence[PhotoPlaceResult],
    clues: Sequence[Clue],
    posts: Sequence[Post],
    gazetteer: Gazetteer,
    fetch_source_image: Callable[[Post, int, int], Awaitable[bytes]],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[PhotoPlaceResult]:
    """Attach evidence only when a Commons image is a near-exact copy of the post photo."""
    post_by_id = {post.post_id: post for post in posts}
    targets: list[tuple[int, PhotoPlaceResult, tuple[float, float], Post]] = []
    for result_index, result in enumerate(results):
        if result.status is not PhotoPlaceStatus.CANDIDATE or len(result.candidates) != 1:
            continue
        place_candidate = result.candidates[0]
        if place_candidate.photo_relation.value != "visible_in_frame":
            continue
        if not _eligible_clue(result, clues):
            continue
        post = post_by_id.get(result.post_id)
        if post is None or not any(image.index == result.image_index for image in post.images):
            continue
        coordinates = _local_candidate_coordinates(place_candidate, gazetteer)
        if coordinates is None:
            continue
        targets.append((result_index, result, coordinates, post))
        if len(targets) == MAX_CANDIDATES_PER_DIAGNOSIS:
            break
    if not targets:
        return list(results)

    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=1),
    ) as client:
        updated = list(results)
        downloaded = 0
        requests = 0
        for result_index, result, (latitude, longitude), post in targets:
            try:
                user_image = await fetch_source_image(
                    post, result.image_index, MAX_SOURCE_IMAGE_BYTES
                )
                if len(user_image) > MAX_SOURCE_IMAGE_BYTES or perceptual_hash(user_image) is None:
                    updated[result_index] = _with_lookup_status(
                        result, PhotoPlaceLookupStatus.REFERENCE_CHECKED
                    )
                    continue
                if requests >= MAX_HTTP_REQUESTS_PER_DIAGNOSIS:
                    break
                requests += 1
                pages = await _commons_pages(client, latitude, longitude)
                matched_result: PhotoPlaceResult | None = None
                for page in pages:
                    if downloaded >= MAX_REFERENCE_IMAGES_PER_DIAGNOSIS:
                        break
                    infos = page.get("imageinfo", [])
                    if not isinstance(infos, list) or not infos:
                        continue
                    info = infos[0]
                    if not isinstance(info, dict):
                        continue
                    rights = _allowed_rights(info.get("extmetadata"))
                    if rights is None:
                        continue
                    thumb_url = _safe_url(info.get("thumburl"), THUMB_HOST)
                    page_url = _safe_url(info.get("descriptionurl"), COMMONS_HOST)
                    page_id = page.get("pageid")
                    if thumb_url is None or page_url is None or not isinstance(page_id, int):
                        continue
                    if requests >= MAX_HTTP_REQUESTS_PER_DIAGNOSIS:
                        break
                    requests += 1
                    downloaded += 1
                    reference_image = await _thumbnail(client, thumb_url)
                    if not is_near_duplicate(user_image, reference_image):
                        continue
                    license_name, creator = rights
                    reference_id = f"commons:{page_id}"
                    source = PhotoPlaceSource(
                        source_id=reference_id,
                        provider="Wikimedia Commons",
                        dataset="GeoData/Imageinfo",
                        license_id=license_name,
                        record_id=str(page_id),
                        version=None,
                        attribution=f"{creator} · {license_name}",
                        source_url=page_url,
                    )
                    original = result.candidates[0]
                    matched = original.model_copy(
                        update={
                            "evidence": [
                                *original.evidence,
                                PhotoPlaceEvidence(kind="reference", reference_id=reference_id),
                            ],
                            "source_ids": list(dict.fromkeys([*original.source_ids, reference_id])),
                            "sources": [*original.sources, source],
                            # Visual near-duplicate evidence never changes the relation or score.
                            "photo_relation": original.photo_relation,
                            "score": None,
                        }
                    )
                    matched_result = result.model_copy(
                        update={
                            "candidates": [matched],
                            "lookup_status": PhotoPlaceLookupStatus.REFERENCE_CHECKED,
                        }
                    )
                    break
                updated[result_index] = (
                    matched_result
                    if matched_result is not None
                    else _with_lookup_status(result, PhotoPlaceLookupStatus.REFERENCE_CHECKED)
                )
            except Exception:
                updated[result_index] = _with_lookup_status(
                    result, PhotoPlaceLookupStatus.UNAVAILABLE, "reference_lookup_unavailable"
                )
    return updated


def _with_lookup_status(
    result: PhotoPlaceResult,
    status: PhotoPlaceLookupStatus,
    reason: str | None = None,
) -> PhotoPlaceResult:
    reasons = list(result.reason_codes)
    if reason and reason not in reasons:
        reasons.append(reason)
    return result.model_copy(update={"lookup_status": status, "reason_codes": reasons})


def mark_reference_lookup_unavailable(
    results: Sequence[PhotoPlaceResult], clues: Sequence[Clue], gazetteer: Gazetteer
) -> list[PhotoPlaceResult]:
    """Mark only locally eligible reference lookups unavailable, without exposing errors."""
    output: list[PhotoPlaceResult] = []
    for result in results:
        eligible = (
            result.status is PhotoPlaceStatus.CANDIDATE
            and len(result.candidates) == 1
            and _eligible_clue(result, clues)
            and bool(_local_candidate_coordinates(result.candidates[0], gazetteer))
        )
        output.append(
            _with_lookup_status(
                result,
                PhotoPlaceLookupStatus.UNAVAILABLE,
                "reference_lookup_unavailable",
            )
            if eligible
            else result
        )
    return output
