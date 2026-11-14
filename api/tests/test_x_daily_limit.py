"""X API の1日の取得件数の上限。X には接続しない（respx で塞ぐ）。"""

from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.x_budget import DailyResourceBudget, one_check_cost, posts_read_cost

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}
LIVE: dict[str, Any] = {
    "x_mock_mode": False,
    "x_use_case_approved": True,
    "x_paid_reads_approved": True,
    "x_query_logs_redacted": True,
    "x_client_id": "synthetic-client",
    "x_client_secret": "synthetic-secret",
}


def test_default_has_no_daily_limit() -> None:
    settings = Settings(_env_file=None)
    assert settings.x_max_posts == 5
    assert settings.x_daily_resource_limit == 0


def test_costs_follow_the_api_minimum_page_size() -> None:
    assert posts_read_cost(30) == 30
    assert posts_read_cost(1) == 5
    assert one_check_cost(5) == 6


def test_budget_refuses_over_the_limit_and_resets_on_the_next_utc_day() -> None:
    today = [date(2026, 11, 12)]
    budget = DailyResourceBudget(10, today=lambda: today[0])

    assert budget.reserve(6)
    assert not budget.reserve(5)  # 断ったときは数えない
    assert budget.remaining() == 4
    assert budget.reserve(4)
    assert not budget.can_afford(1)

    today[0] = date(2026, 11, 13)
    assert budget.remaining() == 10
    with pytest.raises(ValueError):
        budget.reserve(-1)


def test_zero_limit_means_unlimited() -> None:
    budget = DailyResourceBudget(0)
    assert budget.reserve(10_000)
    assert budget.can_afford(10_000)


def _app(**overrides: Any) -> FastAPI:
    return create_app(
        settings=Settings(
            _env_file=None,
            x_public_origin=ORIGIN,
            x_callback_url=f"{ORIGIN}/api/x/callback",
            gazetteer_dir=Path("/missing-x-gazetteer"),
            share_enabled=False,
            **{**LIVE, **overrides},
        )
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def _mock_x(router: respx.MockRouter) -> dict[str, respx.Route]:
    return {
        "token": router.post("https://api.x.com/2/oauth2/token").respond(
            json={"access_token": "t", "token_type": "bearer", "scope": "tweet.read users.read"}
        ),
        "me": router.get("https://api.x.com/2/users/me").respond(
            json={"data": {"id": "42", "username": "fictional_demo"}}
        ),
        "tweets": router.get("https://api.x.com/2/users/42/tweets").respond(
            json={
                "data": [
                    {
                        "id": str(100 + i),
                        "author_id": "42",
                        "text": f"新宿駅 {i}",
                        "created_at": "2026-11-10T00:00:00Z",
                    }
                    for i in range(5)
                ]
            }
        ),
    }


async def _login(client: httpx.AsyncClient) -> httpx.Response:
    start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
    if start.status_code != 200:
        return start
    state = parse_qs(urlparse(start.json()["authorize_url"]).query)["state"][0]
    return await client.get(f"/api/x/callback?state={state}&code=c", follow_redirects=False)


@pytest.mark.anyio
async def test_start_is_refused_when_one_check_does_not_fit() -> None:
    app = _app(x_max_posts=5, x_daily_resource_limit=5)  # 1回分は 6
    async with _client(app) as client:
        with respx.mock as router:
            start = await client.post("/api/x/start", json={"consent": True}, headers=HEADERS)
    assert start.status_code == 429
    assert int(start.headers["retry-after"]) > 0
    assert not router.calls


@pytest.mark.anyio
async def test_reads_stop_at_the_daily_limit_without_calling_x() -> None:
    app = _app(x_max_posts=5, x_daily_resource_limit=8)  # 1回分（6）は入るが2回分は入らない
    with respx.mock as router:
        routes = _mock_x(router)
        async with _client(app) as first:
            assert (await _login(first)).status_code == 303
            assert (await first.post("/api/x/posts", headers=HEADERS)).status_code == 200
            # 同じセッションの2回目はメモリから返し、上限を使わない
            assert (await first.post("/api/x/posts", headers=HEADERS)).status_code == 200
        assert app.state.x_budget.remaining() == 2

        async with _client(app) as second:
            refused = await _login(second)
    assert refused.status_code == 429
    assert routes["me"].call_count == 1
    assert routes["tweets"].call_count == 1
    assert routes["token"].call_count == 1  # 2回目は認可画面へ進ませない


@pytest.mark.anyio
async def test_posts_fetch_is_refused_when_the_budget_ran_out_after_login() -> None:
    app = _app(x_max_posts=5, x_daily_resource_limit=11)
    with respx.mock as router:
        routes = _mock_x(router)
        async with _client(app) as first, _client(app) as second:
            assert (await _login(first)).status_code == 303  # 使用 1
            assert (await _login(second)).status_code == 303  # 使用 2
            assert (await first.post("/api/x/posts", headers=HEADERS)).status_code == 200
            refused = await second.post("/api/x/posts", headers=HEADERS)  # 7 + 5 > 11
            retry = await second.post("/api/x/posts", headers=HEADERS)
    assert refused.status_code == 429
    assert "上限" in refused.json()["detail"]
    assert retry.status_code == 429  # 断られたセッションは busy のまま残らない
    assert routes["tweets"].call_count == 1
