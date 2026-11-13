"""X の実連携は、承認フラグ・Client ID・Client Secret のどれか1つでも欠ければ閉じる。

入口（/config の live_enabled、/start）だけでなく、/callback と実セッションの診断も拒否し、
X へは1件も通信しないことを固定する。X には接続しない（respx で塞ぐ）。
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes.x import SESSION_COOKIE, XSessionStore

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}
COMPLETE: dict[str, Any] = {
    "x_mock_mode": False,
    "x_use_case_approved": True,
    "x_paid_reads_approved": True,
    "x_query_logs_redacted": True,
    "x_client_id": "synthetic-client",
    "x_client_secret": "synthetic-secret",
}
MISSING: dict[str, tuple[str, Any]] = {
    "モックのまま": ("x_mock_mode", True),
    "用途承認なし": ("x_use_case_approved", False),
    "費用承認なし": ("x_paid_reads_approved", False),
    "ログ伏せ字の確認なし": ("x_query_logs_redacted", False),
    "Client ID なし": ("x_client_id", ""),
    "Client ID が空白だけ": ("x_client_id", "   "),
    "Client Secret なし": ("x_client_secret", ""),
    "Client Secret が空白だけ": ("x_client_secret", "  "),
}


def _app(**overrides: Any) -> FastAPI:
    return create_app(
        settings=Settings(
            _env_file=None,
            x_public_origin=ORIGIN,
            x_callback_url=f"{ORIGIN}/api/x/callback",
            gazetteer_dir=Path("/missing-x-gazetteer"),
            share_enabled=False,
            **{**COMPLETE, **overrides},
        )
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


@pytest.mark.anyio
async def test_live_entry_opens_only_when_everything_is_set() -> None:
    async with _client(_app()) as client:
        with respx.mock:
            config = (await client.get("/api/x/config")).json()
            start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
    assert config["live_enabled"] is True
    assert start.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("missing", MISSING.values(), ids=MISSING.keys())
async def test_live_entry_and_api_are_closed_when_one_item_is_missing(
    missing: tuple[str, Any],
) -> None:
    key, value = missing
    app = _app(**{key: value})
    # 承認前に何らかの経路で実トークンのセッションができていても、取得は拒否する
    store: XSessionStore = app.state.x_sessions
    live_session = store.create("synthetic-token", "123", "synthetic_user")
    async with _client(app) as client:
        with respx.mock(assert_all_mocked=True) as router:
            config = (await client.get("/api/x/config")).json()
            start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
            callback = await client.get("/api/x/callback?code=c&state=s")
            client.cookies.set(SESSION_COOKIE, live_session)
            diagnose = await client.post("/api/x/diagnose", headers=HEADERS)
            posts = await client.post("/api/x/posts", headers=HEADERS)
    assert config["live_enabled"] is False
    assert start.status_code == 403
    assert "authorize_url" not in start.text
    assert callback.status_code == 403
    assert diagnose.status_code == 403
    assert posts.status_code == 403
    assert not router.calls  # X へは通信しない
