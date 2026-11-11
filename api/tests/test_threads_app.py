"""合成 X 投稿だけで認証から仮除外まで通す。実 API・実モデルへ接続しない。"""

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

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
        threads_client_id="123",
        threads_client_secret="secret",  # noqa: S106
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
        assert (
            await client.get("/api/threads/callback", params={"state": "wrong", "code": "code"})
        ).status_code == 400
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
        assert (
            await client.get("/api/threads/callback", params={"state": state, "code": "code"})
        ).status_code == 400
        assert (
            await client.delete("/api/threads/session", headers={"Origin": origin})
        ).status_code == 204
        assert (await client.get("/api/threads/diagnosis")).status_code == 401
