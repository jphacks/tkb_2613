"""Threads の本文を読むモデルの選び方と、診断前の応答確認。実モデル・実 API へは接続しない。"""

from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import threads
from tkb_api.threads_poc import to_post
from tkb_common.schemas import Clue, ClueSource, ClueType, Post

ORIGIN = "https://testserver"
HEADERS = {"Origin": ORIGIN}
VLM = {
    "vlm_base_url": "http://10.0.0.15:8000/v1",
    "vlm_api_key": "test-only-key",
    "vlm_model": "team-model",
    "model_allowed_host_suffixes": "10.0.0.15",
}


class FakeExtractor:
    """build_extractor の代わり。応答確認と投稿ごとの読み取りを記録する。"""

    image_enabled = True

    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable
        self.read: list[str] = []
        self.images: list[list[bytes]] = []

    async def model_reachable(self, timeout_s: float) -> bool:
        return self.reachable

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.read.append(post.post_id)
        self.images.append(images)
        return [
            Clue(
                post_id=post.post_id,
                image_index=None,
                type=ClueType.ROUTINE_TEXT,
                value=post.text[:4],
                region=None,
                confidence=0.9,
                source=ClueSource.TEXT,
            )
        ]


def _settings(**kwargs: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "threads_public_origin": ORIGIN,
        "threads_callback_url": f"{ORIGIN}/api/threads/callback",
        "threads_enabled": True,
        "threads_query_logs_redacted": True,
        "threads_app_id": "app-id",
        "threads_app_secret": "test-only-secret",
        "cookie_secure": True,
        "share_enabled": False,
        "gazetteer_dir": Path("/missing-threads-gazetteer"),
        **VLM,
    }
    return Settings(**{**base, **kwargs})


def _capture(monkeypatch: pytest.MonkeyPatch, extractor: FakeExtractor) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def build(**kwargs: Any) -> FakeExtractor:
        calls.append(kwargs)
        return extractor

    monkeypatch.setattr(threads, "build_extractor", build)
    return calls


def _own_posts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    fetched: list[int] = []

    async def fetch(token: str, limit: int) -> tuple[str, list[Post]]:
        fetched.append(limit)
        post = to_post({"id": "1", "text": "架空の本文", "timestamp": "2026-11-11T00:00:00+09:00"})
        assert post is not None
        return "42", [post]

    monkeypatch.setattr(threads, "fetch_own_posts", fetch)
    return fetched


async def _live_diagnose(settings: Settings) -> httpx.Response:
    app = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        session_id = app.state.threads_sessions.create("test-only-token", "42", "tester")
        client.cookies.set("threads_tkb_session", session_id, path="/api/threads")
        return await client.post("/api/threads/diagnose", headers=HEADERS)


@pytest.mark.anyio
async def test_live_posts_are_read_by_the_same_vllm_as_bluesky(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = FakeExtractor()
    calls = _capture(monkeypatch, extractor)
    _own_posts(monkeypatch)

    response = await _live_diagnose(_settings())

    assert response.status_code == 200
    assert extractor.read == ["threads:1"]
    assert extractor.images == [[]]
    [kwargs] = calls
    assert kwargs["text_backend"] == "vlm"
    assert kwargs["vlm_base_url"] == VLM["vlm_base_url"]
    assert kwargs["vlm_api_key"] == VLM["vlm_api_key"]
    assert kwargs["vlm_model"] == VLM["vlm_model"]
    assert kwargs["allowed_hosts"] == ["10.0.0.15"]
    assert kwargs["ocr_base_url"] == ""  # 写真は読まない
    assert kwargs["mock_mode"] is False


@pytest.mark.anyio
async def test_ollama_can_still_be_chosen_by_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = FakeExtractor()
    calls = _capture(monkeypatch, extractor)
    _own_posts(monkeypatch)

    response = await _live_diagnose(
        _settings(
            threads_text_backend="ollama",
            ollama_base_url="http://10.0.0.15:11434",
            ollama_model="team-small",
        )
    )

    assert response.status_code == 200
    [kwargs] = calls
    assert kwargs["text_backend"] == "ollama"
    assert kwargs["ollama_base_url"] == "http://10.0.0.15:11434"
    assert kwargs["ollama_model"] == "team-small"
    assert kwargs["allowed_hosts"] == ["10.0.0.15"]


def test_the_default_text_backend_is_vllm() -> None:
    assert Settings(_env_file=None).threads_text_backend == "vlm"
    assert Settings(_env_file=None).threads_image_diagnosis is False


@pytest.mark.anyio
async def test_image_flag_passes_first_image_to_existing_vllm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = FakeExtractor()
    requested_images: list[bool] = []

    async def fetch(
        token: str, limit: int, *, include_images: bool = False
    ) -> tuple[str, list[Post]]:
        del token, limit
        requested_images.append(include_images)
        post = to_post(
            {
                "id": "1",
                "text": "架空の本文",
                "timestamp": "2026-11-11T00:00:00+09:00",
                "media_type": "IMAGE",
                "media_url": "https://scontent.cdninstagram.com/photo.jpg",
            },
            include_image=True,
        )
        assert post is not None
        return "42", [post]

    async def fetch_images(post: Post) -> list[bytes]:
        assert len(post.images) == 1
        return [b"image-bytes"]

    monkeypatch.setattr(threads, "fetch_own_posts", fetch)
    session = threads.ThreadsSession(
        token="test-only-token",  # noqa: S106
        owner_id="42",
        username="tester",
        expires_at=float("inf"),
    )
    posts = await threads._own_posts(session, _settings(threads_image_diagnosis=True))
    extracted = [
        item async for item in threads.extract_posts(extractor, posts, fetch_images, concurrency=1)
    ]

    assert requested_images == [True]
    assert extractor.images == [[b"image-bytes"]]
    assert extracted[0].error is None
    assert posts[0].images[0].index == 0


@pytest.mark.anyio
async def test_unreachable_model_stops_before_reading_threads_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = FakeExtractor(reachable=False)
    _capture(monkeypatch, extractor)
    fetched = _own_posts(monkeypatch)

    response = await _live_diagnose(_settings())

    assert response.status_code == 503
    assert fetched == []
    assert extractor.read == []


@pytest.mark.anyio
async def test_third_party_ai_endpoint_is_refused_without_leaking_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched = _own_posts(monkeypatch)

    response = await _live_diagnose(
        _settings(
            vlm_base_url="https://api.openai.com/v1",
            model_allowed_host_suffixes="openai.com",
        )
    )

    assert response.status_code == 503
    assert "openai" not in response.text
    assert fetched == []


@pytest.mark.anyio
async def test_gpu_demo_reads_the_fictional_posts_with_the_same_vllm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = FakeExtractor()
    calls = _capture(monkeypatch, extractor)
    settings = _settings(threads_mock_mode=True, threads_gpu_demo_enabled=True)
    app = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        login = await client.post(
            "/api/threads/mock/gpu-session", json={"consent": True}, headers=HEADERS
        )
        assert login.status_code == 200
        response = await client.post("/api/threads/diagnose", headers=HEADERS)

    assert response.status_code == 200
    assert extractor.read == [f"threads:{n}" for n in range(9001, 9006)]
    [kwargs] = calls
    assert kwargs["text_backend"] == "vlm"
    assert kwargs["vlm_base_url"] == VLM["vlm_base_url"]
