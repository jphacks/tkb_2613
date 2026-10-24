import asyncio
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from atproto_client.exceptions import NetworkError, UnauthorizedError
from fastapi import Depends
from fastapi.testclient import TestClient

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.session import MOCK_DID, SESSION_COOKIE, current_session, get_login

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値


def _client(settings: Settings, login: bluesky.LoginFn | None = None) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    if login is not None:
        app.dependency_overrides[get_login] = lambda: login

    @app.get("/test/me")
    def me(session: Annotated[BlueskySession, Depends(current_session)]) -> dict[str, str]:
        return {"did": session.did}

    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(Settings(mock_mode=True)) as c:
        yield c


def test_mock_login_sets_http_only_cookie(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "@alice.bsky.social", "password": PASSWORD})

    assert res.status_code == 200
    assert res.json() == {"handle": "alice.bsky.social", "did": MOCK_DID}
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert PASSWORD not in cookie


def test_session_cookie_identifies_the_logged_in_account(client: TestClient) -> None:
    assert client.get("/test/me").status_code == 401

    client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})

    assert client.get("/test/me").json() == {"did": MOCK_DID}


def test_read_session_returns_the_logged_in_account(client: TestClient) -> None:
    assert client.get("/api/session").status_code == 401

    client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})

    res = client.get("/api/session")
    assert res.status_code == 200
    assert res.json() == {"handle": "alice.bsky.social", "did": MOCK_DID}


def test_logout_discards_the_session(client: TestClient) -> None:
    client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})

    res = client.delete("/api/session")

    assert res.status_code == 204
    assert client.get("/test/me").status_code == 401
    assert len(client.app.state.sessions) == 0  # type: ignore[attr-defined]


def test_logout_without_session_is_ok(client: TestClient) -> None:
    assert client.delete("/api/session").status_code == 204


def test_rejects_empty_password(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": ""})

    assert res.status_code == 422
    assert "set-cookie" not in res.headers


def test_validation_errors_do_not_echo_the_password(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": " @ ", "password": PASSWORD})

    assert res.status_code == 422
    assert PASSWORD not in res.text


def test_rejects_empty_handle(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": " @ ", "password": PASSWORD})
    assert res.status_code == 422


def test_real_login_uses_the_bluesky_result() -> None:
    calls: list[tuple[str, str]] = []

    async def login(handle: str, password: str) -> LoginResult:
        calls.append((handle, password))
        return LoginResult(handle="alice.bsky.social", did="did:plc:alice", client=None)

    with _client(Settings(mock_mode=False), login) as c:
        res = c.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
        assert res.json() == {"handle": "alice.bsky.social", "did": "did:plc:alice"}
        assert c.get("/test/me").json() == {"did": "did:plc:alice"}
    assert calls == [("alice.bsky.social", PASSWORD)]


@pytest.mark.parametrize(
    ("error", "status"),
    [(bluesky.LoginFailedError(), 401), (bluesky.BlueskyUnavailableError(), 502)],
)
def test_real_login_maps_errors(error: Exception, status: int) -> None:
    async def login(handle: str, password: str) -> LoginResult:
        raise error

    with _client(Settings(mock_mode=False), login) as c:
        res = c.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
        assert res.status_code == status
        assert "set-cookie" not in res.headers


class _FakeClient:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    async def login(self, handle: str, password: str) -> Any:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Me:
    handle = "alice.bsky.social"
    did = "did:plc:alice"


def test_bluesky_login_returns_handle_and_did(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bluesky, "AsyncClient", lambda: _FakeClient(_Me()))

    result = asyncio.run(bluesky.login("alice.bsky.social", PASSWORD))

    assert (result.handle, result.did) == ("alice.bsky.social", "did:plc:alice")


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (UnauthorizedError(), bluesky.LoginFailedError),
        (NetworkError(), bluesky.BlueskyUnavailableError),
        (None, bluesky.BlueskyUnavailableError),
    ],
)
def test_bluesky_login_maps_errors(
    monkeypatch: pytest.MonkeyPatch, outcome: Any, expected: type[Exception]
) -> None:
    monkeypatch.setattr(bluesky, "AsyncClient", lambda: _FakeClient(outcome))

    with pytest.raises(expected):
        asyncio.run(bluesky.login("alice.bsky.social", PASSWORD))


def test_store_expires_sessions() -> None:
    now = [0.0]
    store = SessionStore(ttl_seconds=10, clock=lambda: now[0])
    result = LoginResult(handle="a", did="did:plc:a", client=None)
    first = store.create(result)

    assert store.get(first) is not None
    now[0] = 10.0
    assert store.get(first) is None

    second = store.create(result)
    now[0] = 25.0
    store.create(result)  # 作るときに期限切れのものを捨てる
    assert store.get(second) is None
    assert len(store) == 1
    assert store.get("unknown") is None
