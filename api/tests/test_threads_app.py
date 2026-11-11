"""合成 X 投稿だけで認証から仮除外まで通す。実 API・実モデルへ接続しない。"""

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes.threads import ThreadsCallbackAccessFilter

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


def test_oauth_callback_code_is_redacted_from_access_log() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1", "GET", "/api/threads/callback?code=secret&state=secret", "1.1", 303),
        None,
    )
    assert ThreadsCallbackAccessFilter().filter(record)
    assert "secret" not in record.getMessage()


def _client(**kwargs: Any) -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,
        threads_public_origin=ORIGIN,
        threads_callback_url=f"{ORIGIN}/api/threads/callback",
        gazetteer_dir=Path("/missing-x-gazetteer"),
        share_enabled=False,
        **kwargs,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url=ORIGIN
    )


@pytest.mark.anyio
async def test_mock_x_diagnosis_simulation_and_rediagnosis() -> None:
    async with _client(threads_mock_mode=True) as client:
        denied = await client.post(
            "/api/threads/mock/session", json={"consent": False}, headers=HEADERS
        )
        assert denied.status_code == 403
        login = await client.post(
            "/api/threads/mock/session", json={"consent": True}, headers=HEADERS
        )
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        session = await client.get("/api/threads/session")
        assert session.json() == {"username": "架空のThreadsアカウント", "mock": True}
        result = await client.post("/api/threads/diagnose", headers=HEADERS)
        assert result.status_code == 200
        snapshot = result.json()
        assert [p["post_id"] for p in snapshot["posts"]] == ["threads:9001", "threads:9002"]
        assert len(snapshot["clues"]) == 2
        assert snapshot["clues"][0]["quote"] in snapshot["posts"][0]["text"]
        assert snapshot["conclusions"]
        restored = await client.get("/api/threads/diagnosis")
        assert restored.json() == snapshot

        preview = await client.post(
            "/api/threads/simulate", json={"delete": ["threads:9001"]}, headers=HEADERS
        )
        assert preview.status_code == 200
        assert preview.json()["delete"] == ["threads:9001"]
        after = await client.post(
            "/api/threads/rediagnose", json={"delete": ["threads:9001"]}, headers=HEADERS
        )
        assert after.status_code == 200
        assert [p["post_id"] for p in after.json()["posts"]] == ["threads:9002"]
        assert all(c["post_id"] == "threads:9002" for c in after.json()["clues"])
        unknown = await client.post(
            "/api/threads/simulate", json={"delete": ["threads:another"]}, headers=HEADERS
        )
        assert unknown.status_code == 422
        assert (await client.delete("/api/threads/session", headers=HEADERS)).status_code == 204
        assert (await client.get("/api/threads/session")).status_code == 401


@pytest.mark.anyio
async def test_oauth_state_cookie_identity_and_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from tkb_api.routes import threads

    async def exchange(code: str, verifier: str, settings: Settings) -> tuple[str, str]:
        assert code == "code" and verifier
        return "private-token", "42"

    async def identity(token: str) -> tuple[str, str]:
        assert token == "private-token"  # noqa: S105
        return "42", "tester"

    monkeypatch.setattr(threads, "_exchange", exchange)
    monkeypatch.setattr(threads, "_identity", identity)
    origin = "https://testserver"
    settings = Settings(
        _env_file=None,
        threads_public_origin=origin,
        threads_callback_url=f"{origin}/api/threads/callback",
        threads_enabled=True,
        threads_query_logs_redacted=True,
        threads_app_id="123",
        threads_app_secret="secret",  # noqa: S106
        cookie_secure=True,
        share_enabled=False,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url=origin
    ) as client:
        start = await client.post(
            "/api/threads/start", json={"consent": True}, headers={"Origin": origin}
        )
        assert start.status_code == 200
        query = parse_qs(urlparse(start.json()["authorize_url"]).query)
        assert query["scope"] == ["threads_basic"]
        state = query["state"][0]
        wrong = await client.get("/api/threads/callback", params={"state": "wrong", "code": "code"})
        assert wrong.status_code == 303
        assert wrong.headers["location"] == "/threads?auth_error=state"
        assert "code" not in wrong.headers["location"]
        restarted = await client.post(
            "/api/threads/start", json={"consent": True}, headers={"Origin": origin}
        )
        state = parse_qs(urlparse(restarted.json()["authorize_url"]).query)["state"][0]
        callback = await client.get(
            "/api/threads/callback", params={"state": state, "code": "code"}
        )
        assert callback.status_code == 303 and callback.headers["location"] == "/threads"
        assert "private-token" not in str(callback.headers)
        assert (await client.get("/api/threads/session")).json() == {
            "username": "tester",
            "mock": False,
        }
        assert (await client.get("/api/x/session")).status_code == 401
        replay = await client.get("/api/threads/callback", params={"state": state, "code": "code"})
        assert replay.status_code == 303
        assert replay.headers["location"] == "/threads?auth_error=state"
        assert (
            await client.delete("/api/threads/session", headers={"Origin": origin})
        ).status_code == 204
        assert (await client.get("/api/threads/diagnosis")).status_code == 401


@pytest.mark.anyio
async def test_threads_code_exchange_uses_server_secret_and_exact_callback() -> None:
    from urllib.parse import parse_qs

    from tkb_api.routes.threads import _exchange

    settings = Settings(
        _env_file=None,
        threads_app_id="app-id",
        threads_app_secret="test-only-secret",  # noqa: S106
        threads_callback_url="https://example.test/api/threads/callback",
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://graph.threads.net/oauth/access_token").respond(
            json={"access_token": "test-only-token", "user_id": 42}
        )
        token, owner_id = await _exchange("one-time-code", "unused", settings)
    assert route.called
    assert token == "test-only-token"  # noqa: S105
    assert owner_id == "42"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["client_id"] == ["app-id"]
    assert body["client_secret"] == ["test-only-secret"]
    assert body["code"] == ["one-time-code"]
    assert body["redirect_uri"] == ["https://example.test/api/threads/callback"]
    assert body["grant_type"] == ["authorization_code"]


@pytest.mark.anyio
async def test_meta_deauthorize_and_data_deletion_clear_only_signed_owner() -> None:
    import base64
    import hashlib
    import hmac
    import json

    def signed(owner_id: str) -> str:
        payload = (
            base64.urlsafe_b64encode(
                json.dumps({"algorithm": "HMAC-SHA256", "user_id": owner_id}).encode()
            )
            .decode()
            .rstrip("=")
        )
        signature = (
            base64.urlsafe_b64encode(
                hmac.new(b"test-only-secret", payload.encode(), hashlib.sha256).digest()
            )
            .decode()
            .rstrip("=")
        )
        return f"{signature}.{payload}"

    origin = "https://testserver"
    settings = Settings(
        _env_file=None,
        threads_public_origin=origin,
        threads_app_secret="test-only-secret",  # noqa: S106
        cookie_secure=True,
        share_enabled=False,
    )
    app = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        owner_session = app.state.threads_sessions.create(None, "42", "owner")
        other_session = app.state.threads_sessions.create(None, "43", "other")
        client.cookies.set("threads_tkb_session", owner_session, path="/api/threads")
        invalid = await client.post("/api/threads/deauthorize", data={"signed_request": "bad"})
        assert invalid.status_code == 400
        assert (await client.get("/api/threads/session")).status_code == 200
        deleted = await client.post(
            "/api/threads/deauthorize", data={"signed_request": signed("42")}
        )
        assert deleted.status_code == 204
        assert (await client.get("/api/threads/session")).status_code == 401
        assert app.state.threads_sessions.get(other_session) is not None
        result = await client.post(
            "/api/threads/data-deletion", data={"signed_request": signed("43")}
        )
        assert result.status_code == 200
        assert result.json()["url"] == f"{origin}/threads/data-deletion-status"
        assert result.json()["confirmation_code"].isalnum()
        assert app.state.threads_sessions.get(other_session) is None


@pytest.mark.anyio
async def test_posts_are_limited_to_verified_owner_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tkb_api.routes import threads
    from tkb_common.schemas import Post

    origin = "https://testserver"
    settings = Settings(
        _env_file=None,
        threads_public_origin=origin,
        threads_callback_url=f"{origin}/api/threads/callback",
        threads_enabled=True,
        threads_query_logs_redacted=True,
        threads_app_id="app-id",
        threads_app_secret="test-only-secret",  # noqa: S106
        cookie_secure=True,
        share_enabled=False,
    )
    app = create_app(settings=settings)
    calls = 0

    async def fetch(token: str, limit: int) -> tuple[str, list[Post]]:
        nonlocal calls
        calls += 1
        assert token == "test-only-token"  # noqa: S105
        assert limit == settings.threads_max_posts
        return "42", [
            Post.model_validate(
                {
                    "post_id": "threads:1",
                    "text": "架空の本文",
                    "created_at": "2026-11-11T00:00:00+09:00",
                    "images": [],
                }
            )
        ]

    monkeypatch.setattr(threads, "fetch_own_posts", fetch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        assert (await client.get("/api/threads/posts")).status_code == 401
        session_id = app.state.threads_sessions.create("test-only-token", "42", "tester")
        client.cookies.set("threads_tkb_session", session_id, path="/api/threads")
        first = await client.get("/api/threads/posts")
        assert first.status_code == 200
        assert first.json()["posts"][0]["post_id"] == "threads:1"
        assert first.json()["mock"] is False
        assert (await client.get("/api/threads/posts")).status_code == 200
        assert calls == 1
        assert (
            await client.delete("/api/threads/session", headers={"Origin": origin})
        ).status_code == 204
        assert (await client.get("/api/threads/posts")).status_code == 401

    async def wrong_owner(token: str, limit: int) -> tuple[str, list[Post]]:
        return "43", []

    monkeypatch.setattr(threads, "fetch_own_posts", wrong_owner)
    app = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        session_id = app.state.threads_sessions.create("test-only-token", "42", "tester")
        client.cookies.set("threads_tkb_session", session_id, path="/api/threads")
        assert (await client.get("/api/threads/posts")).status_code == 502
