import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from atproto import AsyncClient
from fastapi.testclient import TestClient

from tkb_api.bluesky import BlueskyUnavailableError, LoginResult, PostsFetcher
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_fetch_posts
from tkb_api.routes.session import get_login
from tkb_common.schemas import Post

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _login(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    assert res.status_code == 200


def _events(body: str) -> list[tuple[str, Any]]:
    """SSE の本文を (イベント名, data の JSON) の一覧にする。"""
    events = []
    for block in body.split("\n\n"):
        if not block:
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(mock_mode=True, demo_fixture_path=FIXTURE, mock_event_interval_seconds=0)
    with _client(settings) as c:
        yield c


def test_diagnose_requires_login(client: TestClient) -> None:
    assert client.post("/api/diagnose").status_code == 401


def test_mock_diagnose_streams_each_demo_post_then_done(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    posts = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]
    assert _events(res.text) == [
        *(("post", {"post": post}) for post in posts),
        ("done", {"posts_seen": len(posts)}),
    ]


REAL_DID = "did:plc:me00000000000000000000"
REAL_CLIENT = cast(AsyncClient, object())  # 本物の通信はしない。fetch_posts に渡ることだけ確かめる


def _real_client(fetch_posts: PostsFetcher) -> TestClient:
    """MOCK_MODE=0 の api。ログインと投稿の取得だけを偽物に差し替える。"""

    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=REAL_DID, client=REAL_CLIENT)

    client = _client(Settings(mock_mode=False, max_posts=5))
    client.app.dependency_overrides[get_login] = lambda: login  # type: ignore[attr-defined]
    client.app.dependency_overrides[get_fetch_posts] = lambda: fetch_posts  # type: ignore[attr-defined]
    return client


def test_real_diagnose_streams_the_session_accounts_own_posts() -> None:
    post = Post.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][0])
    calls: list[tuple[AsyncClient, str, int]] = []

    async def fetch_posts(client: AsyncClient, did: str, limit: int) -> list[Post]:
        calls.append((client, did, limit))
        return [post]

    with _real_client(fetch_posts) as client:
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert calls == [(REAL_CLIENT, REAL_DID, 5)]
    assert _events(res.text) == [
        ("post", {"post": post.model_dump(mode="json")}),
        ("done", {"posts_seen": 1}),
    ]


def test_real_diagnose_reports_bluesky_errors_as_bad_gateway() -> None:
    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        raise BlueskyUnavailableError

    with _real_client(fetch_posts) as client:
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 502


def test_real_diagnose_asks_to_log_in_again_after_a_mock_login() -> None:
    settings = Settings(mock_mode=False, demo_fixture_path=FIXTURE)
    with _client(settings) as client:
        # モックでログインしてから設定だけ本番扱いにする（Bluesky のクライアントがないセッション）
        client.app.dependency_overrides[get_settings] = lambda: Settings(mock_mode=True)  # type: ignore[attr-defined]
        _login(client)
        client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]

        assert client.post("/api/diagnose").status_code == 401


def test_mock_diagnose_reports_missing_demo_data(tmp_path: Path) -> None:
    settings = Settings(mock_mode=True, demo_fixture_path=tmp_path / "missing.json")
    with _client(settings) as client:
        _login(client)

        res = client.post("/api/diagnose")

    assert res.status_code == 503
    assert "missing.json" not in res.text


def test_mock_diagnose_rejects_demo_posts_in_the_wrong_format(tmp_path: Path) -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["posts"][0]["images"][0]["url"] = "https://example.com/a.jpg"
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(doc), encoding="utf-8")
    settings = Settings(mock_mode=True, demo_fixture_path=broken, mock_event_interval_seconds=0)
    with _client(settings) as client:
        _login(client)

        res = client.post("/api/diagnose")

    assert res.status_code == 503
    assert "example.com" not in res.text


def test_diagnose_sends_keep_alive_comments_while_waiting_between_events() -> None:
    # 投稿の間を空け、それより短い間隔で keep-alive を送らせる
    # （Vercel や Cloudflare に切られないように）
    settings = Settings(
        mock_mode=True,
        demo_fixture_path=FIXTURE,
        mock_event_interval_seconds=0.05,
        sse_keepalive_seconds=0.01,
    )
    with _client(settings) as client:
        _login(client)

        res = client.post("/api/diagnose")

    blocks = [b for b in res.text.split("\n\n") if b]
    assert ": keep-alive" in blocks
    events = [b for b in blocks if not b.startswith(":")]
    assert _events("\n\n".join(events) + "\n\n")[-1] == ("done", {"posts_seen": 10})
