"""Threads の本番向けの安定化：表のキャッシュ、投稿ごとの失敗、推理を別スレッドで動かすこと。"""

import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api import pipeline
from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import diagnose as bluesky_diagnose
from tkb_api.routes import threads
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.errors import DetectError
from tkb_engine.cross_post import infer_owner_claims_with_web
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.planner import simulate
from tkb_engine.rules import infer

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}
POST_TEXT = "娘の小学校"


class FlakyExtractor:
    """指定した投稿だけ読み取りに失敗する。失敗の文言に本文を入れて、外に出ないことを確かめる。"""

    image_enabled = False

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing

    async def model_reachable(self, timeout_s: float) -> bool:
        return True

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        if post.post_id in self.failing:
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


async def _gpu_diagnose(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, failing: set[str]
) -> httpx.Response:
    monkeypatch.setattr(threads, "build_extractor", lambda **kwargs: FlakyExtractor(failing))
    login = await client.post(
        "/api/threads/mock/gpu-session", json={"consent": True}, headers=HEADERS
    )
    assert login.status_code == 200
    return await client.post("/api/threads/diagnose", headers=HEADERS)


@pytest.mark.anyio
async def test_a_failed_post_is_reported_and_left_out_instead_of_failing_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _client() as client:
        response = await _gpu_diagnose(client, monkeypatch, {"threads:9004"})
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["post_errors"] == [
            {"post_id": "threads:9004", "error": threads.POST_ERROR_MESSAGE}
        ]
        assert POST_TEXT not in str(snapshot["post_errors"])  # 理由に本文を入れない
        assert "threads:9004" not in [p["post_id"] for p in snapshot["posts"]]
        assert all(c["post_id"] != "threads:9004" for c in snapshot["clues"])
        evidence = {e["post_id"] for claim in snapshot["profile_claims"] for e in claim["evidence"]}
        assert "threads:9004" not in evidence
        # 外した投稿は仮除外の対象にもならない
        excluded = await client.post(
            "/api/threads/simulate", json={"delete": ["threads:9004"]}, headers=HEADERS
        )
        assert excluded.status_code == 422
        assert (await client.get("/api/threads/diagnosis")).json() == snapshot


@pytest.mark.anyio
async def test_no_failures_reports_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _client() as client:
        response = await _gpu_diagnose(client, monkeypatch, set())
        assert response.status_code == 200
        assert response.json()["post_errors"] == []
        assert len(response.json()["posts"]) == 5


@pytest.mark.anyio
async def test_when_every_post_fails_the_diagnosis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    every = {f"threads:{n}" for n in range(9001, 9006)}
    async with _client() as client:
        response = await _gpu_diagnose(client, monkeypatch, every)
        assert response.status_code == 503
        assert POST_TEXT not in response.text
        # 結果は置かないので、モデルが戻ればもう一度診断できる
        assert (await client.get("/api/threads/diagnosis")).status_code == 404


@pytest.mark.anyio
async def test_detect_error_message_is_not_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Detecting(FlakyExtractor):
        async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
            if post.post_id == "threads:9003":
                raise DetectError("モデルの応答を読めませんでした")
            return await super().extract_post(post, images)

    monkeypatch.setattr(threads, "build_extractor", lambda **kwargs: Detecting(set()))
    async with _client() as client:
        await client.post("/api/threads/mock/gpu-session", json={"consent": True}, headers=HEADERS)
        response = await client.post("/api/threads/diagnose", headers=HEADERS)
    assert response.json()["post_errors"] == [
        {"post_id": "threads:9003", "error": threads.POST_ERROR_MESSAGE}
    ]


@pytest.mark.anyio
async def test_the_gazetteer_is_read_once_like_bluesky(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[Path] = []

    def load(data_dir: Path) -> Gazetteer:
        reads.append(data_dir)
        return Gazetteer()

    monkeypatch.setattr(bluesky_diagnose, "load_gazetteer", load)
    bluesky_diagnose._cached_gazetteer.cache_clear()
    try:
        async with _client() as client:
            await client.post("/api/threads/mock/session", json={"consent": True}, headers=HEADERS)
            assert (await client.post("/api/threads/diagnose", headers=HEADERS)).status_code == 200
            body = {"delete": ["threads:9001"]}
            assert (
                await client.post("/api/threads/simulate", json=body, headers=HEADERS)
            ).status_code == 200
            assert (
                await client.post("/api/threads/rediagnose", json=body, headers=HEADERS)
            ).status_code == 200
    finally:
        bluesky_diagnose._cached_gazetteer.cache_clear()
    assert reads == [Path("/missing-threads-gazetteer")]


@pytest.mark.anyio
async def test_inference_runs_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def recording(name: str, original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seen[name] = threading.get_ident()
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(
        pipeline,
        "infer_owner_claims_with_web",
        recording("profile", infer_owner_claims_with_web),
    )
    monkeypatch.setattr(threads, "simulate_deletion", recording("simulate", simulate))
    monkeypatch.setattr(threads, "infer", recording("rediagnose", infer))
    async with _client() as client:
        await client.post("/api/threads/mock/session", json={"consent": True}, headers=HEADERS)
        await client.post("/api/threads/diagnose", headers=HEADERS)
        body = {"delete": ["threads:9001"]}
        await client.post("/api/threads/simulate", json=body, headers=HEADERS)
        await client.post("/api/threads/rediagnose", json=body, headers=HEADERS)

    assert set(seen) == {"profile", "simulate", "rediagnose"}
    assert all(ident != loop_thread for ident in seen.values())
