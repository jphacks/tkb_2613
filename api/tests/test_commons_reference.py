import asyncio
import io
import json
import sqlite3
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

from tkb_api.commons_reference import (
    ALLOWED_LICENSE_URLS,
    COMMONS_API,
    COMMONS_HOST,
    MAX_CANDIDATES_PER_DIAGNOSIS,
    MAX_HTTP_REQUESTS_PER_DIAGNOSIS,
    MAX_REFERENCE_IMAGES_PER_DIAGNOSIS,
    THUMB_HOST,
    _local_candidate_coordinates,
    mark_reference_lookup_unavailable,
    search_commons_references,
)
from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    PhotoPlaceCandidate,
    PhotoPlaceEvidence,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceResult,
    PhotoPlaceSource,
    PhotoPlaceStatus,
    Post,
)
from tkb_engine.gazetteer import Gazetteer

POST_ID = "at://did:plc:private-did/app.bsky.feed.post/private-uri"
THUMB_URL = f"https://{THUMB_HOST}/wikipedia/commons/thumb/example.jpg/256px-example.jpg"
FILE_URL = "https://commons.wikimedia.org/wiki/File:Example.jpg"


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    original_policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(coroutine)
    finally:
        asyncio.set_event_loop_policy(original_policy)


def _picture(variant: int = 0, quality: int = 94) -> bytes:
    image = Image.new("RGB", (320, 240), "#dce5ed")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18 + variant * 70, 20, 135 + variant * 55, 132), fill="#176b87")
    draw.ellipse((165, 35 + variant * 5, 255, 125 + variant * 5), fill="#db7a32")
    draw.line((15, 205, 302, 160 - variant * 15), fill="#202c39", width=9)
    draw.polygon([(40, 170), (86, 145 + variant * 12), (129, 185)], fill="#709c54")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def _index(path: Path, place_id: str = "places:poi-1") -> None:
    source = {
        "source_id": "overture:poi-1",
        "provider": "Overture Maps",
        "dataset": "places",
        "license_id": "CC-BY-4.0",
        "record_id": "poi-1",
    }
    record = {
        "place_id": place_id,
        "label": "中央文化館",
        "aliases": ["中央文化館"],
        "latitude": 35.123456,
        "longitude": 139.123456,
        "country": "JP",
        "basic_category": "cultural",
        "sources": [source],
    }
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.executescript(
            """
            CREATE TABLE poi_place (
                place_id TEXT PRIMARY KEY,
                license_verified INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE poi_alias (
                name_key TEXT NOT NULL,
                place_id TEXT NOT NULL,
                PRIMARY KEY(name_key, place_id)
            );
            """
        )
        db.execute("INSERT INTO poi_place VALUES (?, 1, ?)", (place_id, json.dumps(record)))
        db.executemany(
            "INSERT INTO poi_alias VALUES (?, ?)",
            ((key, place_id) for key in place_name_keys("中央文化館")),
        )


def _post() -> Post:
    return Post.model_validate(
        {
            "post_id": POST_ID,
            "text": "本文と写真は外部へ送信しない",
            "created_at": "2026-11-01T12:00:00+09:00",
            "images": [
                {
                    "index": 0,
                    "url": "https://cdn.bsky.app/img/a",
                    "alt": "",
                    "width": 320,
                    "height": 240,
                }
            ],
        }
    )


def _candidate() -> PhotoPlaceResult:
    local_source = PhotoPlaceSource(
        source_id="overture:poi-1",
        provider="Overture Maps",
        dataset="places",
        license_id="CC-BY-4.0",
        record_id="poi-1",
        attribution="Overture",
    )
    place = PhotoPlaceCandidate(
        place_id="places:poi-1",
        label="中央文化館",
        place_type="facility",
        photo_relation="visible_in_frame",
        score=None,
        evidence=[PhotoPlaceEvidence(kind="clue", clue_index=0)],
        source_ids=["overture:poi-1"],
        sources=[local_source],
    )
    return PhotoPlaceResult(
        post_id=POST_ID,
        image_index=0,
        status=PhotoPlaceStatus.CANDIDATE,
        granularity=PhotoPlaceGranularity.FACILITY,
        candidates=[place],
    )


def _clue(*, region: tuple[int, int, int, int] | None = (1, 2, 30, 40)) -> Clue:
    return Clue(
        post_id=POST_ID,
        image_index=0,
        type=ClueType.LANDMARK,
        value="中央文化館",
        region=region,
        confidence=0.95,
        source=ClueSource.OCR,
    )


def _commons_response(
    license_name: str = "CC BY 4.0", license_url: str | None = None
) -> dict[str, Any]:
    return {
        "query": {
            "pages": {
                "123": {
                    "pageid": 123,
                    "title": "File:Example.jpg",
                    "imageinfo": [
                        {
                            "thumburl": THUMB_URL,
                            "descriptionurl": FILE_URL,
                            "extmetadata": {
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {
                                    "value": license_url
                                    or ALLOWED_LICENSE_URLS.get(license_name, "")
                                },
                                "Artist": {
                                    "value": "<a href='/wiki/User:Example'>Example Artist</a>"
                                },
                            },
                        }
                    ],
                }
            }
        }
    }


def test_commons_match_adds_reference_evidence_only_for_near_duplicate_and_keeps_visible_relation(
    tmp_path: Path,
) -> None:
    index = tmp_path / "places.sqlite3"
    _index(index)
    requests: list[httpx.Request] = []
    reference = _picture(quality=88)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.content == b""
        if request.url.host == COMMONS_HOST and request.url.path == "/w/api.php":
            return httpx.Response(200, json=_commons_response())
        assert request.url.host == THUMB_HOST
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=reference)

    async def get_source_image(post: Post, image_index: int, max_bytes: int) -> bytes:
        assert post.post_id == POST_ID
        assert image_index == 0
        assert max_bytes <= 4 * 1024 * 1024
        return _picture()

    result = _run(
        search_commons_references(
            [_candidate()],
            [_clue()],
            [_post()],
            Gazetteer(places_path=index),
            get_source_image,
            transport=httpx.MockTransport(respond),
        )
    )[0]

    assert len(requests) == 2
    commons_request = requests[0]
    assert str(commons_request.url).startswith(COMMONS_API)
    assert commons_request.url.params["ggscoord"] == "35.123456|139.123456"
    assert commons_request.url.params["ggsnamespace"] == "6"
    assert POST_ID not in str(commons_request.url)
    assert "private-did" not in str(commons_request.url)
    assert "本文" not in str(commons_request.url)
    candidate = result.candidates[0]
    assert result.status is PhotoPlaceStatus.CANDIDATE
    assert result.lookup_status is PhotoPlaceLookupStatus.REFERENCE_CHECKED
    assert candidate.photo_relation.value == "visible_in_frame"
    assert candidate.score is None
    assert any(
        item.kind.value == "reference" and item.reference_id == "commons:123"
        for item in candidate.evidence
    )
    commons_source = next(
        source for source in candidate.sources if source.provider == "Wikimedia Commons"
    )
    assert commons_source.attribution == "Example Artist · CC BY 4.0"
    assert commons_source.source_url == FILE_URL


def test_no_match_or_unlicensed_file_never_adds_reference_evidence(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _index(index)

    async def source_image(post: Post, image_index: int, max_bytes: int) -> bytes:
        return _picture()

    for payload, expected_calls, thumbnail in (
        (_commons_response(), 2, _picture(variant=1)),
        (
            _commons_response("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
            1,
            b"",
        ),
        (_commons_response("CC BY 4.0", "//creativecommons.org/licenses/by/4.0/"), 1, b""),
    ):
        requests: list[httpx.Request] = []

        def respond(
            request: httpx.Request,
            *,
            requests: list[httpx.Request] = requests,
            payload: dict[str, Any] = payload,
            thumbnail: bytes = thumbnail,
        ) -> httpx.Response:
            requests.append(request)
            if request.url.host == COMMONS_HOST and request.url.path == "/w/api.php":
                return httpx.Response(200, json=payload)
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=thumbnail)

        result = _run(
            search_commons_references(
                [_candidate()],
                [_clue()],
                [_post()],
                Gazetteer(places_path=index),
                source_image,
                transport=httpx.MockTransport(respond),
            )
        )[0]
        assert len(requests) == expected_calls
        assert not any(item.kind.value == "reference" for item in result.candidates[0].evidence)
        assert result.candidates[0].score is None
        assert result.candidates[0].photo_relation.value == "visible_in_frame"


def test_no_consent_side_or_ineligible_candidates_do_not_fetch_or_query(
    tmp_path: Path,
) -> None:
    index = tmp_path / "places.sqlite3"
    _index(index)
    calls = 0

    async def no_source_image(post: Post, image_index: int, max_bytes: int) -> bytes:
        nonlocal calls
        calls += 1
        raise AssertionError("source image should not be fetched")

    requests: list[httpx.Request] = []
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(respond)
    no_region = _run(
        search_commons_references(
            [_candidate()],
            [_clue(region=None)],
            [_post()],
            Gazetteer(places_path=index),
            no_source_image,
            transport=transport,
        )
    )[0]
    assert no_region.lookup_status is PhotoPlaceLookupStatus.LOCAL_ONLY
    assert calls == 0
    assert requests == []
    assert no_region.candidates[0].score is None


def test_request_limits_and_private_source_failure_are_bounded(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _index(index)
    assert MAX_CANDIDATES_PER_DIAGNOSIS == 3
    assert MAX_REFERENCE_IMAGES_PER_DIAGNOSIS == 3
    assert MAX_HTTP_REQUESTS_PER_DIAGNOSIS == 6

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"pages": {}}})

    async def source_image(post: Post, image_index: int, max_bytes: int) -> bytes:
        return b"too large" * (512 * 1024)

    result = _run(
        search_commons_references(
            [_candidate()],
            [_clue()],
            [_post()],
            Gazetteer(places_path=index),
            source_image,
            transport=httpx.MockTransport(responder),
        )
    )[0]
    assert result.lookup_status is PhotoPlaceLookupStatus.REFERENCE_CHECKED
    assert result.candidates[0].evidence == _candidate().candidates[0].evidence


def test_unavailable_status_is_limited_to_locally_eligible_photo_candidates(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _index(index)
    unknown = PhotoPlaceResult(
        post_id=POST_ID,
        image_index=0,
        status=PhotoPlaceStatus.UNKNOWN,
        granularity=PhotoPlaceGranularity.UNKNOWN,
    )
    marked = mark_reference_lookup_unavailable(
        [_candidate(), unknown], [_clue()], Gazetteer(places_path=index)
    )
    assert marked[0].lookup_status is PhotoPlaceLookupStatus.UNAVAILABLE
    assert "reference_lookup_unavailable" in marked[0].reason_codes
    assert marked[0].status is PhotoPlaceStatus.CANDIDATE
    assert marked[1] is unknown


def test_private_or_unlabeled_local_poi_is_not_eligible_for_commons(
    tmp_path: Path,
) -> None:
    for category, taxonomy, label in (
        ("private_residence", None, "中央文化館"),
        ("cultural", ["residential", "home"], "中央文化館"),
        ("cultural", None, "別の施設名"),
    ):
        index = tmp_path / f"{category}-{label}.sqlite3"
        _index(index)
        with sqlite3.connect(index) as db:
            row = json.loads(db.execute("SELECT record_json FROM poi_place").fetchone()[0])
            row["basic_category"] = category
            row["taxonomy"] = taxonomy
            row["label"] = label
            db.execute("UPDATE poi_place SET record_json = ?", (json.dumps(row),))
        assert _local_candidate_coordinates(
            _candidate().candidates[0], Gazetteer(places_path=index)
        ) is None
