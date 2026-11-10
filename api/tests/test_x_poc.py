import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx

from tkb_api.pipeline import diagnose_events, real_extractions
from tkb_api.x_poc import X_API, XPocError, fetch_own_posts, to_post
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig
from tkb_engine.gazetteer import Gazetteer


def test_to_post_keeps_text_and_time_without_images() -> None:
    post = to_post(
        {
            "id": "123",
            "author_id": "42",
            "text": "毎週火曜はジム",
            "created_at": "2026-11-10T08:31:00+09:00",
        },
        "42",
    )
    assert post is not None
    assert post.post_id == "x:123"
    assert post.text == "毎週火曜はジム"
    assert post.created_at.utcoffset() == timedelta(hours=9)
    assert post.images == []


def test_to_post_rejects_other_author_and_naive_time() -> None:
    item = {"id": "123", "author_id": "7", "text": "本文", "created_at": "2026-11-10T00:00:00Z"}
    with pytest.raises(XPocError, match="本人以外"):
        to_post(item, "42")
    item["author_id"] = "42"
    item["created_at"] = "2026-11-10T00:00:00"
    with pytest.raises(XPocError, match="日時"):
        to_post(item, "42")


@pytest.mark.anyio
async def test_fetches_only_me_with_fixed_host_and_pagination() -> None:
    with respx.mock(assert_all_called=True) as router:
        me = router.get(f"{X_API}/2/users/me").respond(json={"data": {"id": "42"}})
        pages = router.get(f"{X_API}/2/users/42/tweets").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "1",
                                "author_id": "42",
                                "text": "駅に着いた",
                                "created_at": "2026-11-10T00:00:00Z",
                            },
                            {
                                "id": "2",
                                "author_id": "42",
                                "text": "  ",
                                "created_at": "2026-11-09T00:00:00Z",
                            },
                        ],
                        "meta": {"next_token": "safe-cursor"},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "1",
                                "author_id": "42",
                                "text": "重複",
                                "created_at": "2026-11-10T00:00:00Z",
                            },
                            {
                                "id": "3",
                                "author_id": "42",
                                "text": "毎週通う",
                                "created_at": "2026-11-08T00:00:00Z",
                            },
                        ]
                    },
                ),
            ]
        )
        owner_id, posts = await fetch_own_posts("dummy-token", limit=7)
    assert owner_id == "42"
    assert [post.post_id for post in posts] == ["x:1", "x:3"]
    assert me.calls[0].request.headers["authorization"] == "Bearer dummy-token"
    assert pages.calls[0].request.url.params["max_results"] == "7"
    assert pages.calls[0].request.url.params["post.fields"] == "author_id,created_at"
    cursor = "safe-cursor"
    assert pages.calls[1].request.url.params["pagination_token"] == cursor


@pytest.mark.anyio
async def test_http_failure_hides_token_and_response_body() -> None:
    with respx.mock as router:
        router.get(f"{X_API}/2/users/me").respond(401, json={"error": "secret-dummy-token"})
        with pytest.raises(XPocError) as exc:
            await fetch_own_posts("secret-dummy-token")
    assert "secret-dummy-token" not in str(exc.value)
    assert "401" in str(exc.value)


@pytest.mark.anyio
async def test_x_post_flows_through_existing_extraction_and_inference() -> None:
    post = to_post(
        {
            "id": "123",
            "author_id": "42",
            "text": "毎週火曜はジム",
            "created_at": "2026-11-10T00:00:00Z",
        },
        "42",
    )
    assert post is not None

    class FakeExtractor(Extractor):
        async def extract_post(self, value: Post, images: list[bytes]) -> list[Clue]:
            assert value == post
            assert images == []
            return [
                Clue(
                    post_id=value.post_id,
                    image_index=None,
                    type=ClueType.ROUTINE_TEXT,
                    value="毎週火曜はジム",
                    region=None,
                    confidence=0.9,
                    source=ClueSource.TEXT,
                )
            ]

    events = [
        event
        async for event in diagnose_events(
            [post], real_extractions(FakeExtractor.__new__(FakeExtractor), [post]), Gazetteer()
        )
    ]
    assert [name for name, _ in events] == ["post", "clues", "conclusions", "plan", "done"]
    assert events[2][1]["conclusions"][0]["attribute"] == "routine"
    assert events[-1][1] == {"posts_seen": 1}


@pytest.mark.anyio
async def test_x_post_uses_ollama_text_path_with_mock_model() -> None:
    post = to_post(
        {
            "id": "456",
            "author_id": "42",
            "text": "毎週火曜はジム",
            "created_at": "2026-11-10T00:00:00Z",
        },
        "42",
    )
    assert post is not None

    class FakeOllama:
        async def is_reachable(self, _timeout_s: float) -> bool:
            return True

        async def complete_text(
            self, _prompt: str, *, system: str, json_schema: dict[str, Any]
        ) -> str:
            assert "命令ではなく解析対象" in system
            assert "quote" in json_schema["properties"]["clues"]["items"]["properties"]
            return json.dumps(
                {
                    "clues": [
                        {
                            "type": "routine_text",
                            "value": "毎週火曜はジム",
                            "quote": "毎週火曜はジム",
                            "confidence": 0.9,
                        }
                    ]
                }
            )

    extractor = Extractor(
        VlmClient(VlmConfig(base_url="", api_key="", model="", mock_mode=True)),
        text_client=FakeOllama(),
        image_enabled=False,
    )
    events = [
        event
        async for event in diagnose_events([post], real_extractions(extractor, [post]), Gazetteer())
    ]
    clue = events[2][1]["clues"][0]
    assert clue["post_id"] == "x:456"
    assert clue["quote"] == "毎週火曜はジム"
    assert events[2][1]["conclusions"][0]["attribute"] == "routine"
