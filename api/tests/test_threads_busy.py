"""Threads の診断が実行中のときの扱い：409・busy の公開・解除・ログ。"""

import asyncio
import logging
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


class GatedExtractor:
    """release が呼ばれるまで読み取りを止める。mode で失敗やキャンセル待ちも作る。"""

    image_enabled = False

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def model_reachable(self, timeout_s: float) -> bool:
        return True

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.started.set()
        await self.release.wait()
        if self.mode == "fail":
            raise RuntimeError(f"本文を含む失敗: {post.text}")
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


def _client() -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,
        threads_public_origin=ORIGIN,
        threads_mock_mode=True,
        threads_gpu_demo_enabled=True,
        vlm_base_url="http://localhost:8000/v1",
        vlm_model="team-model",
        gazetteer_dir=Path("/missing-threads-gazetteer"),
        share_enabled=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url=ORIGIN
    )


async def _login(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, mode: str) -> Any:
    extractor = GatedExtractor(mode)
    monkeypatch.setattr(threads, "build_extractor", lambda **kwargs: extractor)
    login = await client.post(
        "/api/threads/mock/gpu-session", json={"consent": True}, headers=HEADERS
    )
    assert login.status_code == 200
    return extractor


async def _busy(client: httpx.AsyncClient) -> bool:
    body = (await client.get("/api/threads/session")).json()
    assert isinstance(body["busy"], bool)
    return bool(body["busy"])


@pytest.mark.anyio
async def test_duplicate_request_gets_409_without_interrupting_the_running_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client() as client:
        extractor = await _login(client, monkeypatch, "ok")
        assert await _busy(client) is False
        first = asyncio.create_task(client.post("/api/threads/diagnose", headers=HEADERS))
        await asyncio.wait_for(extractor.started.wait(), 5)
        # 再読み込みした画面は、session から処理中だと分かる
        assert await _busy(client) is True
        duplicate = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert duplicate.status_code == 409
        assert await _busy(client) is True  # 重複要求で解除されない
        extractor.release.set()
        finished = await asyncio.wait_for(first, 10)
        assert finished.status_code == 200
        assert await _busy(client) is False
        # 完了後の再読み込みは保存済みの結果を返す
        assert (await client.get("/api/threads/diagnosis")).json() == finished.json()
        assert (await client.post("/api/threads/diagnose", headers=HEADERS)).json() == (
            finished.json()
        )


@pytest.mark.anyio
async def test_busy_is_released_after_a_failed_diagnosis_and_it_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client() as client:
        extractor = await _login(client, monkeypatch, "fail")
        extractor.release.set()
        failed = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert failed.status_code == 503
        assert await _busy(client) is False
        assert (await client.get("/api/threads/diagnosis")).status_code == 404
        extractor.mode = "ok"
        assert (await client.post("/api/threads/diagnose", headers=HEADERS)).status_code == 200


@pytest.mark.anyio
async def test_busy_is_released_when_the_request_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client() as client:
        extractor = await _login(client, monkeypatch, "ok")
        running = asyncio.create_task(client.post("/api/threads/diagnose", headers=HEADERS))
        await asyncio.wait_for(extractor.started.wait(), 5)
        assert await _busy(client) is True
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        for _ in range(50):
            if not await _busy(client):
                break
            await asyncio.sleep(0.05)
        assert await _busy(client) is False


@pytest.mark.anyio
async def test_logs_distinguish_mock_from_live_and_hold_no_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tkb_api.routes.threads")
    async with _client() as client:
        extractor = await _login(client, monkeypatch, "ok")
        first = asyncio.create_task(client.post("/api/threads/diagnose", headers=HEADERS))
        await asyncio.wait_for(extractor.started.wait(), 5)
        assert (await client.post("/api/threads/diagnose", headers=HEADERS)).status_code == 409
        extractor.release.set()
        assert (await first).status_code == 200
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == "tkb_api.routes.threads")
    assert "Threads診断：開始 kind=mock" in text
    assert "重複要求を断る kind=mock" in text
    assert "Threads診断：完了 kind=mock" in text
    assert "kind=live" not in text
    assert "threads:" not in text  # 投稿ID
    assert "娘" not in text  # 本文
