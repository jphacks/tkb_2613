import logging
import socket
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
import respx
from PIL import Image

from tkb_api.pipeline import diagnose_events, real_extractions
from tkb_api.threads_poc import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    THREADS_API,
    ThreadsPocError,
    _resolved_public_ips,
    _validate_image_bytes,
    fetch_own_posts,
    fetch_threads_images,
    to_post,
)
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.extract import Extractor
from tkb_engine.gazetteer import Gazetteer


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, "JPEG")
    return output.getvalue()


def test_image_pixel_limit_rejects_decode_bombs() -> None:
    output = BytesIO()
    Image.new("1", (5001, 5000)).save(output, "PNG")
    assert MAX_IMAGE_PIXELS < 5001 * 5000
    with pytest.raises(ThreadsPocError, match="画像形式"):
        _validate_image_bytes(output.getvalue())


def test_httpx_log_redacts_threads_media_url(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info(
            'HTTP Request: %s %s "%s %d %s"',
            "GET",
            httpx.URL("https://scontent.cdninstagram.com/photo.jpg?token=must-not-log"),
            "HTTP/1.1",
            200,
            "OK",
        )
    assert "must-not-log" not in caplog.text
    assert "[redacted]" in caplog.text


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


@pytest.mark.parametrize(
    "url",
    [
        "http://scontent.cdninstagram.com/photo.jpg",
        "https://cdninstagram.com.evil.example/photo.jpg",
        "https://evilfbcdn.net/photo.jpg",
        "https://user:password@scontent.cdninstagram.com/photo.jpg",
        "https://scontent.cdninstagram.com:8443/photo.jpg",
        "https://127.0.0.1/photo.jpg",
    ],
)
def test_image_flag_rejects_non_meta_or_ambiguous_urls(url: str) -> None:
    post = to_post(
        {
            "id": "123",
            "text": "本文は残す",
            "timestamp": "2026-11-10T08:31:00+09:00",
            "media_type": "IMAGE",
            "media_url": url,
        },
        include_image=True,
    )
    assert post is not None
    assert post.images == []


def test_dns_answer_rejects_private_or_mixed_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    def private(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private)
    with pytest.raises(OSError):
        _resolved_public_ips("scontent.cdninstagram.com", 443)


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
    image = _jpeg()
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
            content=image, headers={"Content-Type": "image/jpeg"}
        )
        _, posts = await fetch_own_posts("dummy-token", limit=1, include_images=True)
        images = await fetch_threads_images(posts[0])
    assert posts_route.calls[0].request.url.params["fields"] == (
        "id,text,timestamp,media_type,media_url"
    )
    assert images == [image]
    assert "authorization" not in image_route.calls[0].request.headers


@pytest.mark.anyio
async def test_image_redirect_is_not_followed() -> None:
    image_url = "https://scontent.cdninstagram.com/photo.jpg"
    post = to_post(
        {
            "id": "1",
            "text": "写真",
            "timestamp": "2026-11-10T00:00:00Z",
            "media_type": "IMAGE",
            "media_url": image_url,
        },
        include_image=True,
    )
    assert post is not None
    with respx.mock(assert_all_called=False) as router:
        first = router.get(image_url).respond(302, headers={"Location": "http://169.254.169.254/"})
        internal = router.get("http://169.254.169.254/").respond(content=_jpeg())
        with pytest.raises(ThreadsPocError):
            await fetch_threads_images(post)
    assert first.called
    assert not internal.called


@pytest.mark.anyio
async def test_image_body_over_limit_is_rejected_without_content_length() -> None:
    image_url = "https://scontent.cdninstagram.com/large.jpg"
    post = to_post(
        {
            "id": "1",
            "text": "写真",
            "timestamp": "2026-11-10T00:00:00Z",
            "media_type": "IMAGE",
            "media_url": image_url,
        },
        include_image=True,
    )
    assert post is not None
    response = httpx.Response(
        200,
        stream=httpx.ByteStream(b"x" * (MAX_IMAGE_BYTES + 1)),
        headers={"Content-Type": "image/jpeg"},
    )
    with respx.mock as router:
        router.get(image_url).mock(return_value=response)
        with pytest.raises(ThreadsPocError, match="大きすぎ"):
            await fetch_threads_images(post)


@pytest.mark.anyio
async def test_corrupt_image_is_rejected_after_mime_check() -> None:
    image_url = "https://scontent.cdninstagram.com/broken.jpg"
    post = to_post(
        {
            "id": "1",
            "text": "写真",
            "timestamp": "2026-11-10T00:00:00Z",
            "media_type": "IMAGE",
            "media_url": image_url,
        },
        include_image=True,
    )
    assert post is not None
    with respx.mock as router:
        router.get(image_url).respond(
            content=b"not-an-image", headers={"Content-Type": "image/jpeg"}
        )
        with pytest.raises(ThreadsPocError, match="画像形式"):
            await fetch_threads_images(post)


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
