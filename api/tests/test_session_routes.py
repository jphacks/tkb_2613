from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tkb_api.bluesky_auth import (
    AuthenticatedAccount,
    BlueskyAuthenticator,
    LoginProfile,
)
from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes.session import SESSION_COOKIE_NAME, get_current_account
from tkb_api.sessions import SESSION_TTL_SECONDS, SessionStore


@dataclass(frozen=True)
class FakeProfile:
    did: str = "did:plc:example"
    handle: str = "demo.bsky.social"


class FakeClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.received: tuple[str, str] | None = None

    async def login(self, identifier: str, password: str) -> LoginProfile:
        self.received = (identifier, password)
        if self.failure is not None:
            raise self.failure
        return FakeProfile()


@pytest.fixture
def mock_app() -> FastAPI:
    return create_app(Settings(mock_mode=True))


@pytest.fixture
def client(mock_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(mock_app) as test_client:
        yield test_client


def test_mock_login_sets_cookie_and_returns_safe_body(client: TestClient) -> None:
    res = client.post(
        "/api/session",
        json={"handle": "alice.bsky.social", "app_password": "super-secret-password"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body == {"authenticated": True, "handle": "alice.bsky.social"}
    assert "did" not in body
    assert "app_password" not in body
    assert "password" not in body

    # Cookie 検証
    assert SESSION_COOKIE_NAME in res.cookies
    cookie_header = res.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE_NAME}=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()
    assert "path=/" in cookie_header.lower()
    assert f"max-age={SESSION_TTL_SECONDS}" in cookie_header.lower()
    assert "secure" not in cookie_header.lower()


def test_mock_login_normalizes_handle(client: TestClient) -> None:
    # @付きとドメイン省略時の正規化
    res1 = client.post(
        "/api/session",
        json={"handle": "@bob.bsky.social", "app_password": "pw"},
    )
    assert res1.status_code == 200
    assert res1.json()["handle"] == "bob.bsky.social"

    res2 = client.post(
        "/api/session",
        json={"handle": "charlie", "app_password": "pw"},
    )
    assert res2.status_code == 200
    assert res2.json()["handle"] == "charlie.bsky.social"


def test_get_session_states(client: TestClient) -> None:
    # ログイン前
    unauth_res = client.get("/api/session")
    assert unauth_res.status_code == 200
    assert unauth_res.json() == {"authenticated": False, "handle": None}

    # ログイン後
    client.post(
        "/api/session",
        json={"handle": "alice.bsky.social", "app_password": "pw"},
    )
    auth_res = client.get("/api/session")
    assert auth_res.status_code == 200
    assert auth_res.json() == {"authenticated": True, "handle": "alice.bsky.social"}


def test_get_session_after_expiry() -> None:
    now = [1000.0]
    store = SessionStore(clock=lambda: now[0])
    app = create_app(Settings(mock_mode=True), session_store=store)

    with TestClient(app) as client:
        res = client.post(
            "/api/session",
            json={"handle": "alice.bsky.social", "app_password": "pw"},
        )
        assert res.status_code == 200
        assert client.get("/api/session").json()["authenticated"] is True

        # 有効期限を進める
        now[0] += SESSION_TTL_SECONDS + 1
        expired_res = client.get("/api/session")
        assert expired_res.status_code == 200
        assert expired_res.json() == {"authenticated": False, "handle": None}


def test_delete_session_logout(client: TestClient) -> None:
    client.post(
        "/api/session",
        json={"handle": "alice.bsky.social", "app_password": "pw"},
    )
    assert client.get("/api/session").json()["authenticated"] is True

    delete_res = client.delete("/api/session")
    assert delete_res.status_code == 200
    assert delete_res.json() == {"authenticated": False, "handle": None}

    cookie_header = delete_res.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "max-age=0" in cookie_header or "expires=" in cookie_header

    # ログアウト後の確認
    after_res = client.get("/api/session")
    assert after_res.status_code == 200
    assert after_res.json() == {"authenticated": False, "handle": None}


def test_delete_session_when_not_logged_in(client: TestClient) -> None:
    res = client.delete("/api/session")
    assert res.status_code == 200
    assert res.json() == {"authenticated": False, "handle": None}


@pytest.mark.parametrize(
    ("handle", "password"),
    [
        ("", "password123"),
        ("   ", "password123"),
        ("alice.bsky.social", ""),
        ("alice.bsky.social", "   "),
        ("", ""),
    ],
)
def test_login_empty_handle_or_password_returns_401(
    client: TestClient, handle: str, password: str
) -> None:
    res = client.post(
        "/api/session",
        json={"handle": handle, "app_password": password},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Bluesky の認証情報を入力してください"


def test_real_mode_authenticator_success() -> None:
    fake_client = FakeClient()
    authenticator = BlueskyAuthenticator(lambda: fake_client)
    settings = Settings(mock_mode=False)
    app = create_app(settings=settings, authenticator=authenticator)

    with TestClient(app) as client:
        res = client.post(
            "/api/session",
            json={"handle": "real.bsky.social", "app_password": "valid-app-password"},
        )
        assert res.status_code == 200
        assert res.json() == {"authenticated": True, "handle": "demo.bsky.social"}
        assert fake_client.received == ("real.bsky.social", "valid-app-password")


def test_real_mode_authenticator_failure() -> None:
    fake_client = FakeClient(failure=RuntimeError("credentials rejected"))
    authenticator = BlueskyAuthenticator(lambda: fake_client)
    settings = Settings(mock_mode=False)
    app = create_app(settings=settings, authenticator=authenticator)

    with TestClient(app) as client:
        res = client.post(
            "/api/session",
            json={"handle": "real.bsky.social", "app_password": "wrong-password"},
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Bluesky にログインできませんでした"


def test_relogin_revokes_previous_session() -> None:
    store = SessionStore()
    app = create_app(session_store=store)

    with TestClient(app) as client:
        res1 = client.post(
            "/api/session",
            json={"handle": "user1.bsky.social", "app_password": "pw1"},
        )
        token1 = res1.cookies[SESSION_COOKIE_NAME]
        assert store.get(token1) is not None

        res2 = client.post(
            "/api/session",
            json={"handle": "user2.bsky.social", "app_password": "pw2"},
        )
        token2 = res2.cookies[SESSION_COOKIE_NAME]
        assert token1 != token2
        assert store.get(token1) is None
        assert store.get(token2) is not None


def test_get_current_account_dependency() -> None:
    app = create_app(Settings(mock_mode=True))

    @app.get("/api/protected")
    def protected(
        account: Annotated[AuthenticatedAccount, Depends(get_current_account)],
    ) -> dict[str, str]:
        return {"handle": account.handle, "did": account.did}

    with TestClient(app) as client:
        # 未ログイン時は 401
        res_unauth = client.get("/api/protected")
        assert res_unauth.status_code == 401
        assert res_unauth.json()["detail"] == "ログインが必要です"

        # ログイン後は 200 で account を取得可能
        client.post(
            "/api/session",
            json={"handle": "alice.bsky.social", "app_password": "pw"},
        )
        res_auth = client.get("/api/protected")
        assert res_auth.status_code == 200
        assert res_auth.json() == {"handle": "alice.bsky.social", "did": "did:plc:mock-user"}

        # ログアウト後は 401
        client.delete("/api/session")
        res_after = client.get("/api/protected")
        assert res_after.status_code == 401


def test_session_cookie_secure_option() -> None:
    app_insecure = create_app(Settings(mock_mode=True, session_cookie_secure=False))
    with TestClient(app_insecure) as client:
        res = client.post("/api/session", json={"handle": "alice", "app_password": "pw"})
        cookie_header = res.headers.get("set-cookie", "").lower()
        assert "secure" not in cookie_header

    app_secure = create_app(Settings(mock_mode=True, session_cookie_secure=True))
    with TestClient(app_secure) as client:
        res = client.post("/api/session", json={"handle": "alice", "app_password": "pw"})
        cookie_header = res.headers.get("set-cookie", "").lower()
        assert "secure" in cookie_header


def test_login_rejects_extra_fields(client: TestClient) -> None:
    res = client.post(
        "/api/session",
        json={"handle": "alice", "app_password": "pw", "extra": "not-allowed"},
    )
    assert res.status_code == 422


def test_lifespan_closes_session_store() -> None:
    store = SessionStore()
    app = create_app(session_store=store)
    with TestClient(app) as client:
        res = client.post("/api/session", json={"handle": "alice", "app_password": "pw"})
        assert res.status_code == 200
        assert not store._closed
    assert store._closed
