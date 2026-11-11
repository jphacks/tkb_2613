"""合成 X 投稿だけで認証から仮除外まで通す。実 API・実モデルへ接続しない。"""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import x as x_routes
from tkb_api.routes.x import XCallbackAccessFilter, XSessionStore

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


def test_oauth_callback_code_is_redacted_from_access_log() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1", "GET", "/api/x/callback?code=secret&state=secret", "1.1", 303),
        None,
    )
    assert XCallbackAccessFilter().filter(record)
    assert "secret" not in record.getMessage()


def _app(**kwargs: Any) -> FastAPI:
    settings = Settings(
        _env_file=None,
        x_public_origin=ORIGIN,
        x_callback_url=f"{ORIGIN}/api/x/callback",
        gazetteer_dir=Path("/missing-x-gazetteer"),
        share_enabled=False,
        **kwargs,
    )
    return create_app(settings=settings)


def _client(**kwargs: Any) -> httpx.AsyncClient:
    return _client_for(_app(**kwargs))


def _client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


GPU_BASE = "http://gpu.example.test:8000/v1"
GPU_DEMO = {
    "x_mock_mode": True,
    "x_gpu_demo_enabled": True,
    "vlm_base_url": GPU_BASE,
    "vlm_model": "synthetic-vlm",
    "model_allowed_host_suffixes": "gpu.example.test",
    "max_concurrent_diagnoses": 1,
}


@pytest.mark.anyio
async def test_gpu_x_diagnosis_waits_for_a_free_diagnose_slot() -> None:
    app = _app(**GPU_DEMO)
    # 本体の診断が枠を使い切っている
    other = app.state.diagnose_limiter.acquire("bluesky-session", "did:plc:other")
    async with _client_for(app) as client:
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{GPU_BASE}/models").respond(json={"data": [{"id": "synthetic-vlm"}]})
            start = await client.post(
                "/api/x/mock/gpu-session", json={"consent": True}, headers=HEADERS
            )
            assert start.status_code == 200

            busy = await client.post("/api/x/diagnose", headers=HEADERS)

            assert busy.status_code == 503
            assert busy.json()["detail"]["code"] == "busy"
            assert "retry-after" in busy.headers
            assert not router.calls  # 枠がないときは GPU に送らない

            other.release()
            # 枠が空けば進む（ここではモデルが空の応答を返して 503 になるが、枠は返す）
            await client.post("/api/x/diagnose", headers=HEADERS)
            assert router.calls
    assert app.state.diagnose_limiter.active == 0


@pytest.mark.anyio
async def test_preset_x_diagnosis_does_not_take_a_diagnose_slot() -> None:
    app = _app(x_mock_mode=True, max_concurrent_diagnoses=1)
    other = app.state.diagnose_limiter.acquire("bluesky-session", "did:plc:other")
    async with _client_for(app) as client:
        await client.post("/api/x/mock/session", json={"consent": True}, headers=HEADERS)

        result = await client.post("/api/x/diagnose", headers=HEADERS)

    assert result.status_code == 200
    other.release()


def test_x_session_store_drops_expired_sessions_and_pending_logins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(x_routes, "time", SimpleNamespace(monotonic=lambda: now[0]))
    store = XSessionStore(ttl_s=60)
    old_session = store.create(None, "0", "old")
    old_state = store.start("verifier", "nonce")

    now[0] += x_routes.START_TTL_S + 61
    store.create(None, "0", "new")
    store.start("verifier", "nonce")

    assert old_session not in store.sessions
    assert old_state not in store.pending
    assert len(store.sessions) == 1
    assert len(store.pending) == 1


def test_x_session_store_drops_the_oldest_when_over_the_limit() -> None:
    store = XSessionStore(ttl_s=60, max_pending=2, max_sessions=2)
    sessions = [store.create(None, "0", f"user{i}") for i in range(3)]
    states = [store.start("verifier", "nonce") for _ in range(3)]

    assert list(store.sessions) == sessions[1:]
    assert list(store.pending) == states[1:]


@pytest.mark.anyio
async def test_mock_x_diagnosis_simulation_and_rediagnosis() -> None:
    async with _client(x_mock_mode=True) as client:
        denied = await client.post("/api/x/mock/session", json={"consent": False}, headers=HEADERS)
        assert denied.status_code == 403
        login = await client.post("/api/x/mock/session", json={"consent": True}, headers=HEADERS)
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        session = await client.get("/api/x/session")
        assert session.json() == {"username": "架空のXアカウント", "mock": True}
        result = await client.post("/api/x/diagnose", headers=HEADERS)
        assert result.status_code == 200
        snapshot = result.json()
        assert [p["post_id"] for p in snapshot["posts"]] == ["x:9001", "x:9002"]
        assert len(snapshot["clues"]) == 2
        assert snapshot["clues"][0]["quote"] in snapshot["posts"][0]["text"]
        assert snapshot["conclusions"]
        restored = await client.get("/api/x/diagnosis")
        assert restored.json() == snapshot

        preview = await client.post("/api/x/simulate", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert preview.status_code == 200
        assert preview.json()["delete"] == ["x:9001"]
        after = await client.post("/api/x/rediagnose", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert after.status_code == 200
        assert [p["post_id"] for p in after.json()["posts"]] == ["x:9002"]
        assert all(c["post_id"] == "x:9002" for c in after.json()["clues"])
        unknown = await client.post(
            "/api/x/simulate", json={"delete": ["x:another"]}, headers=HEADERS
        )
        assert unknown.status_code == 422
        assert (await client.delete("/api/x/session", headers=HEADERS)).status_code == 204
        assert (await client.get("/api/x/session")).status_code == 401


@pytest.mark.anyio
async def test_synthetic_x_gpu_demo_uses_guarded_vlm_and_never_calls_x() -> None:
    base = "http://gpu.example.test:8000/v1"
    async with _client(
        x_mock_mode=True,
        x_gpu_demo_enabled=True,
        vlm_base_url=base,
        vlm_model="synthetic-vlm",
        model_allowed_host_suffixes="gpu.example.test",
    ) as client:
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{base}/models").respond(json={"data": [{"id": "synthetic-vlm"}]})

            def vlm_response(request: httpx.Request) -> httpx.Response:
                prompt = json.dumps(json.loads(request.content), ensure_ascii=False)
                value = "火曜のジム" if "今週も火曜のジム" in prompt else "毎週火曜はジム"
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "clues": [
                                                {
                                                    "type": "routine_text",
                                                    "value": value,
                                                    "confidence": 0.9,
                                                }
                                            ]
                                        }
                                    )
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    },
                )

            chat = router.post(f"{base}/chat/completions").mock(side_effect=vlm_response)
            start = await client.post(
                "/api/x/mock/gpu-session", json={"consent": True}, headers=HEADERS
            )
            assert start.status_code == 200
            result = await client.post("/api/x/diagnose", headers=HEADERS)
            assert result.status_code == 200
            snapshot = result.json()
            assert snapshot["mock"] is True
            assert len(snapshot["posts"]) == 2
            assert len(snapshot["clues"]) == 2
            assert all(
                clue["value"] in post["text"]
                for clue, post in zip(snapshot["clues"], snapshot["posts"], strict=True)
            )
            assert len(chat.calls) == 2
            assert all(call.request.url.host == "gpu.example.test" for call in router.calls)
            preview = await client.post(
                "/api/x/simulate", json={"delete": ["x:9001"]}, headers=HEADERS
            )
            assert preview.status_code == 200
            after = await client.post(
                "/api/x/rediagnose", json={"delete": ["x:9001"]}, headers=HEADERS
            )
            assert after.status_code == 200
            assert [p["post_id"] for p in after.json()["posts"]] == ["x:9002"]
            assert len(chat.calls) == 2  # 仮除外と再診断では再送しない


@pytest.mark.anyio
async def test_synthetic_x_gpu_demo_rejects_unlisted_remote_host() -> None:
    async with _client(
        x_mock_mode=True,
        x_gpu_demo_enabled=True,
        vlm_base_url="http://gpu.example.test:8000/v1",
        vlm_model="synthetic-vlm",
    ) as client:
        with respx.mock as router:
            start = await client.post(
                "/api/x/mock/gpu-session", json={"consent": True}, headers=HEADERS
            )
            assert start.status_code == 200
            result = await client.post("/api/x/diagnose", headers=HEADERS)
            assert result.status_code == 503
            assert not router.calls


@pytest.mark.anyio
async def test_live_oauth_is_closed_without_both_approvals() -> None:
    async with _client(x_mock_mode=False, x_client_id="public-id") as client:
        with respx.mock as router:
            response = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
            assert response.status_code == 403
            assert not router.calls

    async with _client(
        x_mock_mode=False,
        x_client_id="public-id",
        x_use_case_approved=True,
        x_paid_reads_approved=True,
    ) as client:
        response = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
        assert response.status_code == 403  # 上流のクエリログ対策も必須


@pytest.mark.anyio
async def test_synthetic_oauth_pkce_fetch_and_ollama_pipeline() -> None:
    async with _client(
        x_mock_mode=False,
        x_client_id="public-id",
        x_use_case_approved=True,
        x_paid_reads_approved=True,
        x_query_logs_redacted=True,
    ) as client:
        start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
        assert start.status_code == 200
        query = parse_qs(urlparse(start.json()["authorize_url"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == ["tweet.read users.read"]
        assert query["redirect_uri"] == [f"{ORIGIN}/api/x/callback"]
        assert "httponly" in start.headers["set-cookie"].lower()
        bad = await client.get("/api/x/callback?state=bad&code=code", follow_redirects=False)
        assert bad.status_code == 400

        with respx.mock(assert_all_called=True) as router:
            token = router.post("https://api.x.com/2/oauth2/token").respond(
                json={
                    "access_token": "synthetic-token",
                    "token_type": "bearer",
                    "scope": "tweet.read users.read",
                    "expires_in": 7200,
                }
            )
            me = router.get("https://api.x.com/2/users/me").respond(
                json={"data": {"id": "42", "username": "fictional_demo"}}
            )
            posts = router.get("https://api.x.com/2/users/42/tweets").respond(
                json={
                    "data": [
                        {
                            "id": "123",
                            "author_id": "42",
                            "text": "毎週火曜はジム",
                            "created_at": "2026-11-10T00:00:00Z",
                        }
                    ]
                }
            )
            router.get("http://localhost:11434/api/tags").respond(
                json={"models": [{"name": "qwen3:4b-instruct"}]}
            )
            chat = router.post("http://localhost:11434/api/chat").respond(
                json={
                    "message": {
                        "content": json.dumps(
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
                    }
                }
            )
            callback = await client.get(
                f"/api/x/callback?state={query['state'][0]}&code=synthetic-code",
                follow_redirects=False,
            )
            assert callback.status_code == 303
            assert callback.headers["location"] == "/x"
            session = await client.get("/api/x/session")
            assert session.json() == {"username": "fictional_demo", "mock": False}
            result = await client.post("/api/x/diagnose", headers=HEADERS)
            assert result.status_code == 200, result.text
            snapshot = result.json()
            assert snapshot["posts"][0]["post_id"] == "x:123"
            assert snapshot["clues"][0]["quote"] == "毎週火曜はジム"
            assert snapshot["conclusions"][0]["attribute"] == "routine"
            assert posts.calls[0].request.url.params["post.fields"] == "author_id,created_at"
            assert b"code_verifier=" in token.calls[0].request.content
            assert me.calls[0].request.headers["authorization"] == "Bearer synthetic-token"
            assert chat.calls[0].request.url.host == "localhost"
            again = await client.post("/api/x/diagnose", headers=HEADERS)
            assert again.json() == snapshot
            assert len(posts.calls) == 1
