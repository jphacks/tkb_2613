import asyncio
import json
import sys

import httpx
import pytest
from pydantic import SecretStr

from tkb_api.photo_place_web import BRAVE_PLACE_SEARCH_ENDPOINT, search_photo_places
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    PhotoPlaceCandidate,
    PhotoPlaceEvidence,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceResult,
    PhotoPlaceStatus,
)


def _run(coroutine):
    original_policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(coroutine)
    finally:
        asyncio.set_event_loop_policy(original_policy)


def _clue(
    value: str,
    *,
    post_id: str = "at://demo/post",
    image_index: int | None = 0,
    clue_type: ClueType = ClueType.SHOP,
    source: ClueSource = ClueSource.OCR,
    confidence: float = 0.95,
    region: tuple[int, int, int, int] | None = (1, 1, 50, 20),
) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=image_index,
        type=clue_type,
        value=value,
        region=region,
        confidence=confidence,
        source=source,
    )


def _unknown(post_id: str = "at://demo/post", image_index: int = 0) -> PhotoPlaceResult:
    return PhotoPlaceResult(
        post_id=post_id,
        image_index=image_index,
        status=PhotoPlaceStatus.UNKNOWN,
        granularity=PhotoPlaceGranularity.UNKNOWN,
        reason_codes=["insufficient_local_evidence"],
    )


def _local_candidate(place_id: str, label: str) -> PhotoPlaceCandidate:
    return PhotoPlaceCandidate(
        place_id=place_id,
        label=label,
        place_type="facility",
        photo_relation="visible_in_frame",
        evidence=[PhotoPlaceEvidence(kind="clue", clue_index=0)],
        source_ids=[f"local:{place_id}"],
        sources=[],
    )


def _response(title: str, *, country: str = "JP", url: str = "https://example.org/place") -> dict:
    return {
        "results": [
            {
                "title": title,
                "url": url,
                "id": "temporary-brave-id-must-not-be-retained",
                "postal_address": {
                    "country": country,
                    "addressRegion": "東京都",
                    "addressLocality": "府中市",
                    "postalCode": "183-0000",
                    "streetAddress": "not retained",
                },
                "thumbnail": {"src": "https://example.org/image.jpg"},
            }
        ]
    }


def test_place_search_sends_only_allowlisted_name_and_keeps_unverified_candidate() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response("府中美術館"),
        )

    result = _run(
        search_photo_places(
            [_unknown()],
            [_clue("府中美術館")],
            SecretStr("fake-test-token"),
            transport=httpx.MockTransport(respond),
        )
    )[0]

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).startswith(BRAVE_PLACE_SEARCH_ENDPOINT)
    assert dict(request.url.params) == {
        "q": "府中美術館",
        "country": "JP",
        "count": "5",
        "search_lang": "ja",
        "ui_lang": "ja-JP",
        "spellcheck": "false",
    }
    assert request.headers["x-subscription-token"] == "fake-test-token"
    assert result.status is PhotoPlaceStatus.CANDIDATE
    assert result.lookup_status is PhotoPlaceLookupStatus.WEB_SEARCHED
    assert result.reason_codes == []
    [candidate] = result.candidates
    assert candidate.photo_relation.value == "visible_in_frame"
    assert candidate.score is None
    assert candidate.area_label == "東京都 府中市"
    assert candidate.evidence[0].clue_index == 0
    [source] = candidate.sources
    assert source.source_url == "https://example.org/place"
    assert source.record_id is None
    assert "temporary-brave-id" not in candidate.place_id
    assert "image.jpg" not in json.dumps(result.model_dump(mode="json"))
    assert "183-0000" not in json.dumps(result.model_dump(mode="json"))


def test_same_query_for_multiple_images_keeps_each_images_own_clue_reference() -> None:
    post_id = "at://demo/post"
    image_results = [_unknown(post_id, 0), _unknown(post_id, 1)]
    clues = [
        _clue("府中美術館", post_id=post_id, image_index=0),
        _clue("府中美術館", post_id=post_id, image_index=1),
    ]
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response("府中美術館"),
        )

    results = _run(
        search_photo_places(
            image_results,
            clues,
            SecretStr("test-token"),
            transport=httpx.MockTransport(respond),
        )
    )

    assert len(requests) == 1
    assert [result.candidates[0].evidence[0].clue_index for result in results] == [0, 1]


def test_external_same_name_does_not_merge_into_one_local_branch() -> None:
    ambiguous = PhotoPlaceResult(
        post_id="at://demo/post",
        image_index=0,
        status=PhotoPlaceStatus.AMBIGUOUS,
        granularity=PhotoPlaceGranularity.FACILITY,
        candidates=[
            _local_candidate("local:1", "府中美術館"),
            _local_candidate("local:2", "別の施設"),
        ],
        reason_codes=["multiple_matches"],
    )
    result = _run(
        search_photo_places(
            [ambiguous],
            [_clue("府中美術館")],
            SecretStr("test-token"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json=_response("府中美術館", url="https://example.org/branch"),
                )
            ),
        )
    )[0]

    assert result.status is PhotoPlaceStatus.AMBIGUOUS
    assert len(result.candidates) == 3
    assert result.candidates[0].sources == []
    assert result.candidates[2].sources[0].provider == "Brave Search Place Search"


def test_unique_local_candidate_is_sufficient_and_skips_brave() -> None:
    local = PhotoPlaceResult(
        post_id="at://demo/post",
        image_index=0,
        status=PhotoPlaceStatus.CANDIDATE,
        granularity=PhotoPlaceGranularity.FACILITY,
        candidates=[_local_candidate("local:1", "府中美術館")],
    )

    result = _run(
        search_photo_places(
            [local],
            [_clue("府中美術館")],
            SecretStr("test-token"),
            transport=httpx.MockTransport(
                lambda _request: (_ for _ in ()).throw(AssertionError("must not search"))
            ),
        )
    )[0]

    assert result is local


@pytest.mark.parametrize(
    "clue",
    [
        _clue("藤井環", clue_type=ClueType.NAME_TEXT),
        _clue("会社法人", clue_type=ClueType.ORG_TEXT),
        _clue("個人の投稿文", clue_type=ClueType.PLACE_TEXT),
        _clue("府中市朝日町3-11-1", clue_type=ClueType.ADDRESS_TEXT),
        _clue("1830000", clue_type=ClueType.POSTAL_CODE),
        _clue(
            "府中美術館",
            clue_type=ClueType.PLACE_TEXT,
            source=ClueSource.TEXT,
            image_index=None,
            region=None,
        ),
        _clue("府中美術館", region=None),
        _clue("府中美術館", confidence=0.5),
        _clue("府中美術館 x", confidence=0.95),
        _clue("https://example.com", confidence=0.95),
        _clue("美術館へ行ってきました", confidence=0.95),
    ],
)
def test_sensitive_or_nonvisual_clues_never_reach_brave(clue: Clue) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response("府中美術館"))

    result = _run(
        search_photo_places(
            [_unknown()],
            [clue],
            SecretStr("test-token"),
            transport=httpx.MockTransport(respond),
        )
    )[0]

    assert requests == []
    assert result.status is PhotoPlaceStatus.UNKNOWN
    assert result.lookup_status is PhotoPlaceLookupStatus.LOCAL_ONLY


def test_brave_country_scope_is_not_treated_as_country_validation() -> None:
    result = _run(
        search_photo_places(
            [_unknown()],
            [_clue("府中美術館")],
            SecretStr("test-token"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json=_response("府中美術館", country="US"),
                )
            ),
        )
    )[0]

    assert result.status is PhotoPlaceStatus.UNKNOWN
    assert result.lookup_status is PhotoPlaceLookupStatus.WEB_SEARCHED
    assert result.reason_codes == ["no_external_match"]


def test_external_title_must_match_exactly_and_private_urls_are_rejected() -> None:
    payload = {
        "results": [
            _response("別の施設")["results"][0],
            {**_response("府中美術館", url="https://127.0.0.1/internal")["results"][0]},
        ]
    }
    result = _run(
        search_photo_places(
            [_unknown()],
            [_clue("府中美術館")],
            SecretStr("test-token"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, headers={"content-type": "application/json"}, json=payload
                )
            ),
        )
    )[0]

    assert result.status is PhotoPlaceStatus.UNKNOWN
    assert result.reason_codes == ["no_external_match"]


def test_query_limit_is_three_and_unsearched_images_are_unavailable() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        title = request.url.params["q"]
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(title),
        )

    names = ["美術館甲", "美術館乙", "美術館丙", "美術館丁"]
    clues = [_clue(name, image_index=index) for index, name in enumerate(names)]
    images = [_unknown(image_index=index) for index in range(4)]
    results = _run(
        search_photo_places(
            images,
            clues,
            SecretStr("test-token"),
            transport=httpx.MockTransport(respond),
        )
    )

    assert len(requests) == 3
    assert all(
        result.lookup_status is PhotoPlaceLookupStatus.WEB_SEARCHED for result in results[:3]
    )
    assert results[3].status is PhotoPlaceStatus.UNAVAILABLE
    assert results[3].reason_codes == ["photo_place_query_limit"]


def test_missing_key_marks_lookup_unavailable_without_transport() -> None:
    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport must not be called when the key is missing")

    results = _run(
        search_photo_places(
            [_unknown(image_index=0), _unknown(image_index=1)],
            [_clue("府中美術館")],
            SecretStr(""),
            transport=httpx.MockTransport(fail_if_called),
        )
    )
    assert results[0].status is PhotoPlaceStatus.UNAVAILABLE
    assert results[0].lookup_status is PhotoPlaceLookupStatus.UNAVAILABLE
    assert results[1].status is PhotoPlaceStatus.UNKNOWN
    assert results[1].lookup_status is PhotoPlaceLookupStatus.LOCAL_ONLY


def test_missing_key_does_not_mark_images_without_any_allowlisted_clue_unavailable() -> None:
    result = _run(
        search_photo_places(
            [_unknown()],
            [_clue("藤井環", clue_type=ClueType.NAME_TEXT)],
            SecretStr(""),
        )
    )[0]
    assert result.status is PhotoPlaceStatus.UNKNOWN
    assert result.lookup_status is PhotoPlaceLookupStatus.LOCAL_ONLY
