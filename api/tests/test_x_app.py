"""合成 X 投稿と HTTP モックだけで、認証保護と公開情報集計を確認する。"""

import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes.x import XCallbackAccessFilter

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


def _app(**kwargs: Any) -> FastAPI:
    return create_app(
        settings=Settings(
            _env_file=None,
            x_public_origin=ORIGIN,
            x_callback_url=f"{ORIGIN}/api/x/callback",
            gazetteer_dir=Path("/missing-x-gazetteer"),
            share_enabled=False,
            **kwargs,
        )
    )


def _client(**kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(**kwargs)), base_url=ORIGIN)


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


@pytest.mark.anyio
async def test_mock_public_information_exclusion_and_logout() -> None:
    async with _client(x_mock_mode=True) as client:
        assert (
            await client.post("/api/x/mock/session", json={"consent": False}, headers=HEADERS)
        ).status_code == 403
        login = await client.post("/api/x/mock/session", json={"consent": True}, headers=HEADERS)
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie

        result = await client.post("/api/x/diagnose", headers=HEADERS)
        assert result.status_code == 200
        snapshot = result.json()
        assert len(snapshot["posts"]) == 3
        by_key = {(item["category"], item["value"]): item for item in snapshot["information"]}
        assert by_key[("station", "渋谷駅")]["count"] == 2
        assert by_key[("weekday", "日曜日")]["count"] == 2
        assert by_key[("time", "10時")]["count"] == 2
        assert by_key[("school", "青空大学")]["count"] == 2
        assert all(
            evidence["quote"]
            in next(
                post["text"] for post in snapshot["posts"] if post["post_id"] == evidence["post_id"]
            )
            for item in snapshot["information"]
            for evidence in item["evidence"]
        )
        assert not {"clues", "conclusions", "plan"} & snapshot.keys()

        preview = await client.post("/api/x/simulate", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert preview.status_code == 200
        after = {(item["category"], item["value"]): item for item in preview.json()["after"]}
        assert after[("station", "渋谷駅")]["count"] == 1

        rediagnosed = await client.post(
            "/api/x/rediagnose", json={"delete": ["x:9001"]}, headers=HEADERS
        )
        assert [post["post_id"] for post in rediagnosed.json()["posts"]] == [
            "x:9002",
            "x:9003",
        ]
        assert (
            await client.post("/api/x/simulate", json={"delete": ["x:unknown"]}, headers=HEADERS)
        ).status_code == 422

        assert (await client.delete("/api/x/session", headers=HEADERS)).status_code == 204
        assert (await client.get("/api/x/session")).status_code == 401
        assert (await client.get("/api/x/diagnosis")).status_code == 401


@pytest.mark.anyio
async def test_live_oauth_and_content_are_closed_without_all_approvals() -> None:
    async with _client(x_mock_mode=False, x_client_id="public-id") as client:
        with respx.mock as router:
            start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
            assert start.status_code == 403
            assert not router.calls

    async with _client(
        x_mock_mode=False,
        x_client_id="public-id",
        x_client_secret="synthetic-secret",  # noqa: S106 - HTTPモック用
        x_use_case_approved=True,
        x_paid_reads_approved=True,
    ) as client:
        assert (
            await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
        ).status_code == 403

    async with _client(
        x_mock_mode=False,
        x_client_id="public-id",
        x_use_case_approved=True,
        x_paid_reads_approved=True,
        x_query_logs_redacted=True,
    ) as client:
        config = await client.get("/api/x/config")
        assert config.json()["live_enabled"] is False  # Web App の Secret も必須
        assert (
            await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
        ).status_code == 403


@pytest.mark.anyio
async def test_oauth_pkce_state_owner_check_and_direct_only_aggregation() -> None:
    async with _client(
        x_mock_mode=False,
        x_client_id="public-id",
        x_client_secret="synthetic-secret",  # noqa: S106 - HTTPモック用
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
        assert (await client.get("/api/x/callback?state=bad&code=code")).status_code == 400

        with respx.mock(assert_all_called=True) as router:
            token = router.post("https://api.x.com/2/oauth2/token").respond(
                json={
                    "access_token": "synthetic-token",
                    "token_type": "bearer",
                    "scope": "tweet.read users.read",
                    "expires_in": 7200,
                }
            )
            router.get("https://api.x.com/2/users/me").respond(
                json={"data": {"id": "42", "username": "fictional_demo"}}
            )
            posts = router.get("https://api.x.com/2/users/42/tweets").respond(
                json={
                    "data": [
                        {
                            "id": "123",
                            "author_id": "42",
                            "text": "新宿駅、金曜19時に集合",
                            "created_at": "2026-11-10T00:00:00Z",
                        }
                    ]
                }
            )
            callback = await client.get(
                f"/api/x/callback?state={query['state'][0]}&code=synthetic-code",
                follow_redirects=False,
            )
            assert callback.status_code == 303
            result = await client.post("/api/x/diagnose", headers=HEADERS)
            assert result.status_code == 200
            information = result.json()["information"]
            assert {(item["category"], item["value"]) for item in information} == {
                ("station", "新宿駅"),
                ("weekday", "金曜日"),
                ("time", "19時"),
            }
            assert posts.calls[0].request.url.params["post.fields"] == "author_id,created_at"
            assert b"code_verifier=" in token.calls[0].request.content
            assert len(posts.calls) == 1
            assert not any("ollama" in str(call.request.url) for call in router.calls)

        replay = await client.get(
            f"/api/x/callback?state={query['state'][0]}&code=synthetic-code",
            follow_redirects=False,
        )
        assert replay.status_code == 400  # state と開始Cookieは一回限り
