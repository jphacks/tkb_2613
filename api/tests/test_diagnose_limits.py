"""診断の乱用対策・公開時間外・Bluesky の混雑を、HTTP の応答として確かめる。"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from atproto import AsyncClient
from atproto_client.exceptions import RateLimitExceededError
from fastapi.testclient import TestClient

from tkb_api import bluesky
from tkb_api.bluesky import BlueskyRateLimitedError, Diagnosis, LoginResult, delete_own_posts
from tkb_api.config import Settings, get_settings
from tkb_api.limits import JST, DiagnoseLimiter, PublicWindow
from tkb_api.main import create_app
from tkb_api.routes.delete import get_delete_posts
from tkb_api.routes.diagnose import get_clock, get_extractor_factory, get_fetch_posts
from tkb_api.routes.session import MOCK_DID, SESSION_COOKIE, get_login
from tkb_common.schemas import Post
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig

# ブラウザは POST・DELETE に Origin を付ける（元に戻せない操作は Origin を確かめる）
BROWSER_ORIGIN = {"Origin": "http://localhost:3000"}

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
REAL_DID = "did:plc:me00000000000000000000"


class FakeBlueskyClient:
    async def get_profile(self, *, actor: str) -> SimpleNamespace:
        assert actor == REAL_DID
        return SimpleNamespace(description="")


REAL_CLIENT = cast(AsyncClient, FakeBlueskyClient())
NOW = datetime(2026, 11, 16, 20, 30, tzinfo=JST)
DEMO_POSTS = tuple(
    Post.model_validate(p) for p in json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][:3]
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mock_mode": True,
        "demo_fixture_path": FIXTURE,
        "mock_event_interval_seconds": 0,
    }
    return Settings(**{**base, **overrides})


def _client(settings: Settings, now: datetime = NOW) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_clock] = lambda: lambda: now
    return TestClient(app, headers=BROWSER_ORIGIN)


def _login(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    assert res.status_code == 200


def _limiter(client: TestClient) -> DiagnoseLimiter:
    limiter: DiagnoseLimiter = client.app.state.diagnose_limiter  # type: ignore[attr-defined]
    return limiter


def _detail(res: Any) -> dict[str, Any]:
    detail: dict[str, Any] = res.json()["detail"]
    return detail


# --- 1日の回数 ---


def test_daily_limit_returns_429_with_the_reset_time() -> None:
    with _client(_settings(diagnose_daily_limit=2)) as client:
        _login(client)
        assert client.post("/api/diagnose").status_code == 200
        assert client.post("/api/diagnose").status_code == 200

        res = client.post("/api/diagnose")

    assert res.status_code == 429
    detail = _detail(res)
    assert detail["code"] == "daily_limit"
    assert detail["limit"] == 2
    assert detail["resets_at"] == "2026-11-17T00:00:00+09:00"
    assert int(res.headers["Retry-After"]) == 3 * 60 * 60 + 30 * 60


def test_daily_limit_follows_the_account_across_logins() -> None:
    with _client(_settings(diagnose_daily_limit=1)) as client:
        _login(client)
        assert client.post("/api/diagnose").status_code == 200
        assert _limiter(client).used_today(MOCK_DID) == 1
        _login(client)  # ログインし直しても同じアカウント（モックの DID）
        assert client.post("/api/diagnose").status_code == 429


# --- 同時実行の枠・同じセッション ---


def test_busy_returns_503_with_retry_after_and_is_not_counted() -> None:
    settings = _settings(max_concurrent_diagnoses=1, diagnose_daily_limit=1)
    with _client(settings) as client:
        _login(client)
        other = _limiter(client).acquire("someone-else", "did:plc:other")

        res = client.post("/api/diagnose")

        assert res.status_code == 503
        assert _detail(res)["code"] == "busy"
        assert res.headers["Retry-After"] == "30"
        # 混雑で断られた分は数えないので、空けば今日の1回目として診断できる
        other.release()
        assert client.post("/api/diagnose").status_code == 200


def test_second_diagnosis_in_the_same_session_returns_409() -> None:
    with _client(_settings(max_concurrent_diagnoses=5)) as client:
        _login(client)
        session_id = client.cookies[SESSION_COOKIE]
        running = _limiter(client).acquire(session_id, "did:plc:x")  # 別のタブで診断中

        res = client.post("/api/diagnose")

        assert res.status_code == 409
        assert _detail(res)["code"] == "already_running"
        running.release()
        assert client.post("/api/diagnose").status_code == 200


def test_same_account_from_another_login_returns_409() -> None:
    with _client(_settings(max_concurrent_diagnoses=5)) as client:
        _login(client)
        running = _limiter(client).acquire(
            "another-login", MOCK_DID
        )  # 別の端末でログインして診断中

        res = client.post("/api/diagnose")

        assert res.status_code == 409
        assert _detail(res)["code"] == "already_running"
        running.release()
        assert client.post("/api/diagnose").status_code == 200


def test_slot_is_returned_after_a_diagnosis_finishes() -> None:
    with _client(_settings(max_concurrent_diagnoses=1)) as client:
        _login(client)
        for _ in range(3):
            assert client.post("/api/diagnose").status_code == 200
        assert _limiter(client).active == 0


def test_login_is_checked_before_the_limits() -> None:
    with _client(_settings(max_concurrent_diagnoses=1)) as client:
        _limiter(client).acquire("someone-else", "did:plc:other")
        assert client.post("/api/diagnose").status_code == 401


# --- 公開時間外 ---

WINDOWS = [
    PublicWindow(
        start=datetime(2026, 11, 16, 20, tzinfo=JST), end=datetime(2026, 11, 16, 22, tzinfo=JST)
    ),
    PublicWindow(
        start=datetime(2026, 11, 17, 20, tzinfo=JST), end=datetime(2026, 11, 17, 22, tzinfo=JST)
    ),
]


def test_outside_the_public_hours_returns_503_with_the_next_start() -> None:
    later = datetime(2026, 11, 16, 23, 0, tzinfo=JST)
    with _client(_settings(public_windows=WINDOWS), now=later) as client:
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 503
    assert _detail(res) == {
        "code": "closed",
        "message": "公開時間外です",
        "next_open": "2026-11-17T20:00:00+09:00",
    }


def test_after_the_last_window_reports_that_the_service_ended() -> None:
    after = datetime(2026, 11, 18, 9, 0, tzinfo=JST)
    with _client(_settings(public_windows=WINDOWS), now=after) as client:
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 503
    assert _detail(res)["code"] == "closed"
    assert _detail(res)["next_open"] is None


def test_inside_the_public_hours_diagnoses_normally() -> None:
    with _client(_settings(public_windows=WINDOWS)) as client:
        _login(client)
        assert client.post("/api/diagnose").status_code == 200


def test_closed_is_not_counted() -> None:
    later = datetime(2026, 11, 16, 23, 0, tzinfo=JST)
    with _client(_settings(public_windows=WINDOWS), now=later) as client:
        _login(client)
        client.post("/api/diagnose")
        assert _limiter(client).used_today(MOCK_DID) == 0
        assert _limiter(client).active == 0


def test_public_windows_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_WINDOWS",
        '[{"start": "2026-11-16T20:00:00+09:00", "end": "2026-11-16T22:00:00+09:00"}]',
    )
    assert Settings().public_windows == WINDOWS[:1]


# --- 本番モード：モデルと Bluesky ---


class _UnreachableExtractor(Extractor):
    def __init__(self) -> None:
        super().__init__(VlmClient(VlmConfig(base_url="", api_key="", model="")))

    async def model_reachable(self, timeout_s: float) -> bool:
        return False


def _real_client(
    fetch_posts: bluesky.PostsFetcher, extractor: Extractor | None = None
) -> TestClient:
    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=REAL_DID, client=REAL_CLIENT)

    client = _client(Settings(mock_mode=False, max_posts=5))
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_login] = lambda: login
    overrides[get_fetch_posts] = lambda: fetch_posts
    fake = extractor or Extractor(VlmClient(VlmConfig(base_url="", api_key="", model="")))
    overrides[get_extractor_factory] = lambda: lambda: fake
    return client


async def _no_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
    return []


def test_model_unavailable_returns_503_and_is_not_counted() -> None:
    fetched: list[str] = []

    async def fetch_posts(_client: AsyncClient, did: str, _limit: int) -> list[Post]:
        fetched.append(did)
        return []

    with _real_client(fetch_posts, _UnreachableExtractor()) as client:
        _login(client)
        res = client.post("/api/diagnose")
        limiter = _limiter(client)

        assert res.status_code == 503
        assert _detail(res)["code"] == "model_unavailable"
        assert fetched == []  # モデルが使えないなら Bluesky にも取りに行かない
        assert limiter.used_today(REAL_DID) == 0
        assert limiter.active == 0


def test_bluesky_rate_limit_while_fetching_returns_bluesky_busy() -> None:
    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        raise BlueskyRateLimitedError

    with _real_client(fetch_posts) as client:
        _login(client)
        res = client.post("/api/diagnose")
        assert _limiter(client).active == 0
        assert _limiter(client).used_today(REAL_DID) == 0

    assert res.status_code == 503
    assert _detail(res)["code"] == "bluesky_busy"


def test_real_diagnosis_is_counted_when_it_starts() -> None:
    with _real_client(_no_posts) as client:
        _login(client)
        assert client.post("/api/diagnose").status_code == 200
        assert _limiter(client).used_today(REAL_DID) == 1


def test_bluesky_rate_limit_at_login_returns_bluesky_busy() -> None:
    async def login(_handle: str, _password: str) -> LoginResult:
        raise BlueskyRateLimitedError

    with _client(Settings(mock_mode=False)) as client:
        client.app.dependency_overrides[get_login] = lambda: login  # type: ignore[attr-defined]
        res = client.post(
            "/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD}
        )

    assert res.status_code == 503
    assert _detail(res)["code"] == "bluesky_busy"
    assert PASSWORD not in res.text


# --- bluesky.py：atproto の 429 を見分ける ---


class _RateLimitedFeed:
    async def get_author_feed(self, **_: Any) -> Any:
        raise RateLimitExceededError


@pytest.mark.anyio
async def test_fetch_own_posts_maps_429_to_rate_limited() -> None:
    with pytest.raises(BlueskyRateLimitedError):
        await bluesky.fetch_own_posts(cast(AsyncClient, _RateLimitedFeed()), REAL_DID, 5)


class _RateLimitedLogin:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def login(self, _handle: str, _password: str) -> Any:
        raise RateLimitExceededError


@pytest.mark.anyio
async def test_login_maps_429_to_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bluesky, "AsyncClient", _RateLimitedLogin)
    with pytest.raises(BlueskyRateLimitedError):
        await bluesky.login("alice.bsky.social", PASSWORD)


class _DeletesThenRateLimited:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def delete_post(self, post_id: str) -> None:
        self.calls.append(post_id)
        if len(self.calls) == 2:
            raise RateLimitExceededError


@pytest.mark.anyio
async def test_delete_stops_at_429_and_reports_what_was_deleted() -> None:
    ids = [f"at://{REAL_DID}/app.bsky.feed.post/{i}" for i in ("a", "b", "c")]
    client = _DeletesThenRateLimited()

    with pytest.raises(BlueskyRateLimitedError) as e:
        await delete_own_posts(cast(AsyncClient, client), REAL_DID, ids)

    assert e.value.deleted == (ids[0],)
    assert client.calls == ids[:2]  # 断られたあとは試さない


def test_delete_route_reports_bluesky_busy_and_failed_posts() -> None:
    ids = [p.post_id for p in DEMO_POSTS]

    async def delete_posts(_c: AsyncClient, _did: str, post_ids: Sequence[str]) -> list[str]:
        raise BlueskyRateLimitedError(post_ids[:1])  # 1件消したところで 429

    with _real_client(_no_posts) as client:
        _login(client)
        store = client.app.state.sessions  # type: ignore[attr-defined]
        store.set_diagnosis(client.cookies[SESSION_COOKIE], Diagnosis(posts=DEMO_POSTS, clues=()))
        client.app.dependency_overrides[get_delete_posts] = lambda: delete_posts  # type: ignore[attr-defined]
        res = client.post("/api/delete", json={"delete": ids})

    assert res.status_code == 200
    body = res.json()
    assert body["bluesky_busy"] is True
    assert body["delete"] == ids[:1]
    assert body["failed"] == ids[1:]
