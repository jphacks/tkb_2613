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
from tkb_api.routes.diagnose import get_extractor_factory, get_fetch_posts, get_gazetteer
from tkb_api.routes.session import get_login
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig
from tkb_engine.gazetteer import Gazetteer

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"

# 根津のまわりだけの小さな表（data/processed がなくてもテストできるように）
NEZU_MESH = "53394661"
MINI_GAZETTEER = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": NEZU_MESH},
        {"station_name": "根岸", "mesh_1km": "52396700"},
    ],
    postal=[{"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"}],
    muni_meshes={"13105": {NEZU_MESH}},
)


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: MINI_GAZETTEER
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


def test_mock_diagnose_streams_posts_clues_conclusions_plan_then_done(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts, clues = doc["posts"], doc["clues"]
    events = _events(res.text)
    names = [name for name, _ in events]
    assert names == ["post"] * 10 + ["clues"] * 10 + ["conclusions", "plan", "done"]
    assert [data for name, data in events if name == "post"] == [{"post": p} for p in posts]

    # 手がかりはデモ用データのものを、投稿ごとにまとめて流す
    clue_events = [data for name, data in events if name == "clues"]
    assert [e["post_id"] for e in clue_events] == [p["post_id"] for p in posts]
    assert all(e["error"] is None for e in clue_events)
    assert sum(len(e["clues"]) for e in clue_events) == len(clues)

    # 推理の根拠の番号は、conclusions の clues の並びでの番号
    _, result = events[-3]
    by_attribute = {c["attribute"]: c for c in result["conclusions"]}
    station = by_attribute["station"]
    assert station["value"] == "根津駅"
    assert {result["clues"][i]["value"] for i in station["clue_indices"]} >= {"根x"}
    assert by_attribute["routine"]["value"].startswith("毎週火曜 20時ごろ")
    assert events[-1] == ("done", {"posts_seen": len(posts)})


REAL_DID = "did:plc:me00000000000000000000"
REAL_CLIENT = cast(AsyncClient, object())  # 本物の通信はしない。fetch_posts に渡ることだけ確かめる


class FakeExtractor(Extractor):
    """本文ごとに routine_text を1つ返す偽物（モデルには接続しない）。"""

    def __init__(self) -> None:
        super().__init__(VlmClient(VlmConfig(base_url="", api_key="", model="")))
        self.seen: list[tuple[str, int]] = []

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.seen.append((post.post_id, len(images)))
        return [
            Clue(
                post_id=post.post_id,
                image_index=None,
                type=ClueType.ROUTINE_TEXT,
                value=post.text,
                region=None,
                confidence=0.9,
                source=ClueSource.TEXT,
            )
        ]


def _real_client(fetch_posts: PostsFetcher, extractor: Extractor | None = None) -> TestClient:
    """MOCK_MODE=0 の api。ログイン・投稿の取得・手がかりの取り出しを偽物に差し替える。"""

    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=REAL_DID, client=REAL_CLIENT)

    client = _client(Settings(mock_mode=False, max_posts=5))
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_login] = lambda: login
    overrides[get_fetch_posts] = lambda: fetch_posts
    fake = extractor or FakeExtractor()
    overrides[get_extractor_factory] = lambda: lambda: fake
    return client


def test_real_diagnose_extracts_clues_from_the_session_accounts_own_posts() -> None:
    # 写真のない投稿（写真の取得は別のテストで確かめる）
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})
    calls: list[tuple[AsyncClient, str, int]] = []
    extractor = FakeExtractor()

    async def fetch_posts(client: AsyncClient, did: str, limit: int) -> list[Post]:
        calls.append((client, did, limit))
        return [post]

    with _real_client(fetch_posts, extractor) as client:
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert calls == [(REAL_CLIENT, REAL_DID, 5)]
    assert extractor.seen == [(post.post_id, 0)]
    events = _events(res.text)
    assert [name for name, _ in events] == ["post", "clues", "conclusions", "plan", "done"]
    assert events[1][1]["post_id"] == post.post_id
    assert events[1][1]["clues"][0]["value"] == post.text
    assert events[2][1]["clues"] == events[1][1]["clues"]
    assert events[-1] == ("done", {"posts_seen": 1})


@pytest.mark.parametrize("vlm_base_url", ["", "https://api.openai.com/v1"])
def test_real_diagnose_reports_a_missing_or_forbidden_model_endpoint(vlm_base_url: str) -> None:
    post = Post.model_validate({**json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]})

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=REAL_DID, client=REAL_CLIENT)

    settings = Settings(mock_mode=False, vlm_base_url=vlm_base_url, max_posts=5)
    with _client(settings) as client:
        client.app.dependency_overrides[get_login] = lambda: login  # type: ignore[attr-defined]
        client.app.dependency_overrides[get_fetch_posts] = lambda: fetch_posts  # type: ignore[attr-defined]
        _login(client)
        res = client.post("/api/diagnose")

    assert res.status_code == 503
    assert "openai" not in res.text


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
