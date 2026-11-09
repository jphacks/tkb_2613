"""OAuth の内部境界と既存ログインの切り替え。外部サービスには接続しない。"""

import asyncio
from collections.abc import Sequence
from typing import Any

from fastapi.testclient import TestClient

from tkb_api.bluesky import BlueskySession, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.delete import _delete

DID = "did:plc:demo"
POST = f"at://{DID}/app.bsky.feed.post/3kabc"


def _client() -> TestClient:
    settings = Settings(mock_mode=False, auth_mode="oauth", internal_auth_secret="test-only-secret")  # noqa: S106
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_oauth_rejects_password_and_unauthorized_completion() -> None:
    with _client() as client:
        assert (
            client.post(
                "/api/session", json={"handle": "demo.bsky.social", "password": "not-real"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/__internal/oauth/complete", json={"did": DID, "handle": "demo.bsky.social"}
            ).status_code
            == 403
        )
        assert client.get("/api/session").status_code == 401


def test_oauth_completion_rejects_bad_identity_and_rotates_session() -> None:
    with _client() as client:
        headers = {"X-Internal-Auth": "test-only-secret"}
        bad = client.post(
            "/__internal/oauth/complete",
            json={"did": "not-a-did", "handle": "demo.bsky.social"},
            headers=headers,
        )
        assert bad.status_code == 403
        first = client.post(
            "/__internal/oauth/complete",
            json={"did": DID, "handle": "demo.bsky.social"},
            headers=headers,
        )
        assert first.status_code == 200
        old_cookie = first.cookies.get("tkb_session")
        second = client.post(
            "/__internal/oauth/complete",
            json={"did": DID, "handle": "demo.bsky.social"},
            headers=headers,
        )
        assert second.status_code == 200
        assert old_cookie != second.cookies.get("tkb_session")
        store: SessionStore = client.app.state.sessions  # type: ignore[attr-defined]
        assert store.get(old_cookie or "") is None


def test_oauth_session_expires_in_memory() -> None:
    now = [0.0]
    store = SessionStore(1800, clock=lambda: now[0])
    identifier = store.create(LoginResult("demo.bsky.social", DID, None, "oauth"))
    assert store.get(identifier) is not None
    now[0] = 1800
    assert store.get(identifier) is None


def test_oauth_delete_preserves_partial_success(monkeypatch: Any) -> None:
    calls: list[str] = []

    class Reply:
        def __init__(self, success: bool) -> None:
            self.status_code = 200 if success else 502

        def json(self) -> dict[str, bool]:
            return {"deleted": self.status_code == 200}

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            assert timeout == 20

        async def __aenter__(self) -> "FakeHttpClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def post(self, _url: str, *, json: dict[str, str], headers: dict[str, str]) -> Reply:
            assert headers["X-Internal-Auth"] == "test-only-secret"
            calls.append(json["post_id"])
            return Reply(json["post_id"] == POST)

    monkeypatch.setattr("tkb_api.routes.delete.httpx.AsyncClient", FakeHttpClient)

    async def unused(_client: Any, _did: str, _ids: Sequence[str]) -> list[str]:
        raise AssertionError("legacy delete must not run")

    session = BlueskySession("demo.bsky.social", DID, None, 1800, "oauth")
    settings = Settings(mock_mode=False, auth_mode="oauth", internal_auth_secret="test-only-secret")  # noqa: S106
    other = f"at://{DID}/app.bsky.feed.post/3kdef"
    result = asyncio.run(_delete(session, settings, unused, [POST, other]))
    assert result == [POST]
    assert calls == [POST, other]
