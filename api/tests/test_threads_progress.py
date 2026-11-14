"""Threads の診断の進み具合（GET /api/threads/progress）と、診断中の二重送信。"""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import threads
from tkb_common.schemas import Clue, ClueSource, ClueType, Post

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}
MOCK_POSTS = 5


class GatedExtractor:
    """2件目以降の投稿は gate が開くまで読み終わらない。診断中の状態を外から確かめるため。"""

    image_enabled = False

    def __init__(self, gate: asyncio.Event, reachable: bool = True) -> None:
        self.gate = gate
        self.reachable = reachable
        self.calls = 0

    async def model_reachable(self, timeout_s: float) -> bool:
        return self.reachable

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.calls += 1
        if self.calls > 1:
            await self.gate.wait()
        return [
            Clue(
                post_id=post.post_id,
                image_index=None,
                type=ClueType.ROUTINE_TEXT,
                value=post.text[:3],
                region=None,
                confidence=0.9,
                source=ClueSource.TEXT,
            )
        ]


def _client(**kwargs: Any) -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,
        threads_public_origin=ORIGIN,
        threads_mock_mode=True,
        threads_gpu_demo_enabled=True,
        vlm_base_url="http://localhost:8000/v1",
        vlm_model="team-model",
        gazetteer_dir=Path("/missing-threads-gazetteer"),
        share_enabled=False,
        **kwargs,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url=ORIGIN
    )


async def _gpu_login(client: httpx.AsyncClient) -> None:
    login = await client.post(
        "/api/threads/mock/gpu-session", json={"consent": True}, headers=HEADERS
    )
    assert login.status_code == 200


async def _progress(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/threads/progress")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def _wait_until(client: httpx.AsyncClient, posts_read: int) -> dict[str, Any]:
    for _ in range(200):
        body = await _progress(client)
        if body["state"] == "running" and body["posts_read"] >= posts_read:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("診断中の状態になりませんでした")


@pytest.mark.anyio
async def test_progress_requires_a_session() -> None:
    async with _client() as client:
        assert (await client.get("/api/threads/progress")).status_code == 401


@pytest.mark.anyio
async def test_progress_is_idle_before_diagnosis() -> None:
    async with _client() as client:
        await _gpu_login(client)
        assert await _progress(client) == {
            "state": "idle",
            "stage": None,
            "elapsed_ms": None,
            "posts_total": None,
            "posts_read": 0,
            "read_post_ids": [],
            "stages": [],
            "error": None,
        }


@pytest.mark.anyio
async def test_running_diagnosis_reports_real_counts_and_rejects_a_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    monkeypatch.setattr(threads, "build_extractor", lambda **kwargs: GatedExtractor(gate))
    async with _client() as client:
        await _gpu_login(client)
        first = asyncio.create_task(client.post("/api/threads/diagnose", headers=HEADERS))
        running = await _wait_until(client, posts_read=1)
        assert running["stage"] == "reading"
        assert running["posts_total"] == MOCK_POSTS
        # 読み終えた数だけを返す。まだ読んでいない投稿を見込みで数えない
        assert running["posts_read"] == 1
        assert running["read_post_ids"] == ["threads:9001"]
        # GPU デモは架空の投稿を使うので、投稿の取得は段階に入れない
        assert running["stages"] == ["checking_model", "reading", "inferring"]
        assert isinstance(running["elapsed_ms"], int) and running["elapsed_ms"] >= 0
        assert running["error"] is None

        second = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert second.status_code == 409
        # 結果はまだないので、再読み込みした画面は progress で待つ
        assert (await client.get("/api/threads/diagnosis")).status_code == 404

        gate.set()
        done = await first
        assert done.status_code == 200
        assert await _progress(client) == {
            "state": "done",
            "stage": None,
            "elapsed_ms": None,
            "posts_total": None,
            "posts_read": 0,
            "read_post_ids": [],
            "stages": [],
            "error": None,
        }
        assert (await client.get("/api/threads/diagnosis")).json() == done.json()
        # 終わったあとの二重送信は、同じ結果を返すだけ
        again = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert again.status_code == 200
        assert again.json() == done.json()


@pytest.mark.anyio
async def test_stopped_model_is_reported_as_a_failure_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    monkeypatch.setattr(
        threads, "build_extractor", lambda **kwargs: GatedExtractor(gate, reachable=False)
    )
    async with _client() as client:
        await _gpu_login(client)
        response = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert response.status_code == 503
        body = await _progress(client)
        assert body["state"] == "failed"
        assert body["error"] == "model_unavailable"
        # 失敗のあとは busy が外れ、モデルが戻ればもう一度診断できる
        monkeypatch.setattr(threads, "build_extractor", lambda **kwargs: GatedExtractor(gate))
        gate.set()
        retry = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert retry.status_code == 200
        assert (await _progress(client))["state"] == "done"


@pytest.mark.anyio
async def test_fetching_posts_alone_is_not_reported_as_a_diagnosis() -> None:
    async with _client() as client:
        login = await client.post(
            "/api/threads/mock/session", json={"consent": True}, headers=HEADERS
        )
        assert login.status_code == 200
        assert (await client.get("/api/threads/posts")).status_code == 200
        assert (await _progress(client))["state"] == "idle"
