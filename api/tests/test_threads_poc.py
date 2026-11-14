from datetime import timedelta

import httpx
import pytest
import respx

from tkb_api.pipeline import diagnose_events, real_extractions
from tkb_api.threads_poc import (
    THREADS_API,
    ThreadsPocError,
    fetch_own_posts,
    fetch_threads_images,
    to_post,
)
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.extract import Extractor
from tkb_engine.gazetteer import Gazetteer


def test_to_post_keeps_text_and_timezone_without_threads_images() -> None:
    post = to_post(
        {
            "id": "123",
            "text": "東京駅に着いた",
            "timestamp": "2026-11-10T08:31:00+09:00",
            "media_type": "IMAGE",
            "media_url": "https://example.test/photo.jpg",
        }
    )
    assert post is not None
    assert post.post_id == "threads:123"
    assert post.text == "東京駅に着いた"
    assert post.created_at.utcoffset() == timedelta(hours=9)
    assert post.images == []
    assert to_post({"id": "456", "text": None}) is None


def test_to_post_keeps_first_image_only_when_enabled() -> None:
    item = {
        "id": "123",
        "text": "写真の投稿",
        "timestamp": "2026-11-10T08:31:00+09:00",
        "media_type": "IMAGE",
        "media_url": "https://scontent.cdninstagram.com/photo.jpg?token=redacted",
    }
    assert to_post(item).images == []  # type: ignore[union-attr]
    post = to_post(item, include_image=True)
    assert post is not None
    assert [image.url for image in post.images] == [item["media_url"]]

    video = to_post({**item, "media_type": "VIDEO"}, include_image=True)
    carousel = to_post({**item, "media_type": "CAROUSEL_ALBUM"}, include_image=True)
    assert video is not None and video.images == []
    assert carousel is not None and carousel.images == []


@pytest.mark.anyio
async def test_fetches_only_own_feed_and_uses_cursor_without_following_next_url() -> None:
    with respx.mock(assert_all_called=True) as router:
        me = router.get(f"{THREADS_API}/me").respond(json={"id": "owner", "username": "tester"})
        pages = router.get(f"{THREADS_API}/me/threads").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "1", "text": "駅に着いた", "timestamp": "2026-11-10T00:00:00Z"},
                            {"id": "2", "text": None, "timestamp": "2026-11-09T00:00:00Z"},
                        ],
                        "paging": {
                            "cursors": {"after": "safe-cursor"},
                            "next": "https://evil.example/steal",
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "1", "text": "重複", "timestamp": "2026-11-10T00:00:00Z"},
                            {"id": "3", "text": "毎週通う", "timestamp": "2026-11-08T00:00:00Z"},
                        ]
                    },
                ),
            ]
        )
        user_id, posts = await fetch_own_posts("dummy-token", limit=2)
    assert user_id == "owner"
    assert [post.post_id for post in posts] == ["threads:1", "threads:3"]
    assert me.calls[0].request.headers["authorization"] == "Bearer dummy-token"
    assert pages.calls[1].request.url.params["after"] == "safe-cursor"
    assert pages.calls[0].request.url.params["fields"] == "id,text,timestamp,media_type"


@pytest.mark.anyio
async def test_image_flag_requests_media_url_and_downloads_only_the_allowed_image() -> None:
    image_url = "https://scontent.cdninstagram.com/photo.jpg?token=redacted"
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{THREADS_API}/me").respond(json={"id": "owner", "username": "tester"})
        posts_route = router.get(f"{THREADS_API}/me/threads").respond(
            json={
                "data": [
                    {
                        "id": "1",
                        "text": "写真の投稿",
                        "timestamp": "2026-11-10T00:00:00Z",
                        "media_type": "IMAGE",
                        "media_url": image_url,
                    }
                ]
            }
        )
        image_route = router.get(image_url).respond(
            content=b"fake-image", headers={"Content-Type": "image/jpeg"}
        )
        _, posts = await fetch_own_posts("dummy-token", limit=1, include_images=True)
        images = await fetch_threads_images(posts[0])
    assert posts_route.calls[0].request.url.params["fields"] == (
        "id,text,timestamp,media_type,media_url"
    )
    assert images == [b"fake-image"]
    assert "authorization" not in image_route.calls[0].request.headers


@pytest.mark.anyio
async def test_http_failure_does_not_expose_token_or_response() -> None:
    with respx.mock as router:
        router.get(f"{THREADS_API}/me").respond(401, json={"error": "secret-dummy-token"})
        with pytest.raises(ThreadsPocError) as exc:
            await fetch_own_posts("secret-dummy-token")
    assert "secret-dummy-token" not in str(exc.value)
    assert "401" in str(exc.value)


@pytest.mark.anyio
async def test_threads_post_flows_through_existing_extraction_and_inference() -> None:
    post = to_post({"id": "123", "text": "毎週火曜はジム", "timestamp": "2026-11-10T00:00:00Z"})
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
