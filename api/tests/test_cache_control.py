"""api の応答を、途中の中継（Vercel の CDN など）にキャッシュさせない。

ログイン状態の応答がキャッシュされると、別の人に他人のログイン情報が返るおそれがあるため。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(mock_mode=True, mock_event_interval_seconds=0)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c


def test_api_responses_are_never_stored_by_caches(client: TestClient) -> None:
    anonymous = client.get("/api/session")
    login = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    me = client.get("/api/session")
    diagnose = client.post("/api/diagnose")
    logout = client.delete("/api/session")

    for res in (anonymous, login, me, diagnose, logout):
        assert res.headers["cache-control"] == "no-store, no-transform"


def test_validation_errors_are_never_stored_by_caches(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": ""})

    assert res.status_code == 422
    assert res.headers["cache-control"] == "no-store, no-transform"
