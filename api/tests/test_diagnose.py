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
from tkb_api.public_web_identity import ExternalLookupResult
from tkb_api.routes.diagnose import (
    get_external_profile_searcher,
    get_extractor_factory,
    get_fetch_posts,
    get_fetch_profile_text,
    get_gazetteer,
)
from tkb_api.routes.session import get_login
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    ExternalLookupStatus,
    ExternalProfileResult,
    ExternalProfileStatus,
    Post,
)
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


def test_public_lookup_consent_requires_json_boolean_and_absent_body_defaults_off(
    client: TestClient,
) -> None:
    _login(client)
    invalid = client.post("/api/diagnose", json={"public_web_lookup_consent": "yes"})
    assert invalid.status_code == 422
    absent = client.post("/api/diagnose")
    assert absent.status_code == 200
    event = next(data for name, data in _events(absent.text) if name == "conclusions")
    assert event["external_lookup_status"] == "not_requested"
    assert event["external_profile_results"] == []


def test_mock_diagnose_streams_posts_clues_conclusions_then_done(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts, clues = doc["posts"], doc["clues"]
    events = _events(res.text)
    names = [name for name, _ in events]
    assert names == ["post"] * 12 + ["clues"] * 12 + ["conclusions", "done"]
    assert [data for name, data in events if name == "post"] == [{"post": p} for p in posts]

    # 手がかりはデモ用データのものを、投稿ごとにまとめて流す
    clue_events = [data for name, data in events if name == "clues"]
    assert [e["post_id"] for e in clue_events] == [p["post_id"] for p in posts]
    assert all(e["error"] is None for e in clue_events)
    assert sum(len(e["clues"]) for e in clue_events) == len(clues)

    # 推理の根拠の番号は、conclusions の clues の並びでの番号
    _, result = events[-2]
    by_attribute = {c["attribute"]: c for c in result["conclusions"]}
    station = by_attribute["station"]
    assert station["value"] == "根津駅"
    assert {result["clues"][i]["value"] for i in station["clue_indices"]} >= {"根x"}
    assert by_attribute["routine"]["value"].startswith("毎週火曜 20時ごろ")
    claim_by_attribute = {item["attribute"]: item for item in result["profile_claims"]}
    assert claim_by_attribute["residential_area"]["value"] == "文京区"
    assert result["profile_claim_suggestions"] == [posts[10]["post_id"]]
    assert result["external_lookup_status"] == "not_requested"
    assert result["external_profile_results"] == []
    assert events[-1] == ("done", {"posts_seen": len(posts)})


def test_mock_external_lookup_uses_fictional_fixture_without_network(client: TestClient) -> None:
    async def must_not_call(_handle: str) -> ExternalLookupResult:
        raise AssertionError("MOCK_MODE must not call the search provider")

    client.app.dependency_overrides[get_external_profile_searcher] = lambda: must_not_call  # type: ignore[attr-defined]
    _login(client)
    response = client.post("/api/diagnose", json={"public_web_lookup_consent": True})
    assert response.status_code == 200
    event = next(data for name, data in _events(response.text) if name == "conclusions")
    assert event["external_lookup_status"] == "fixture"
    linked, candidate = event["external_profile_results"]
    assert linked["status"] == "owner_linked"
    assert linked["owner_evidence"]["kind"] == "profile_text"
    assert linked["url"] == "https://example.com/haruki-blog"
    assert candidate["status"] == "candidate"
    assert candidate["owner_evidence"] is None


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

    async def extract_profile_text(self, did: str, text: str) -> list[Clue]:
        return [
            Clue(
                post_id=f"profile:{did}",
                image_index=None,
                type=ClueType.NAME_TEXT,
                value="本人記載の名前",
                region=None,
                confidence=0.9,
                source=ClueSource.PROFILE_TEXT,
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

    async def fetch_profile(_client: AsyncClient, did: str) -> str:
        assert did == REAL_DID
        return "本人プロフィール文"

    overrides[get_fetch_profile_text] = lambda: fetch_profile
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
    assert [name for name, _ in events] == ["post", "clues", "conclusions", "done"]
    assert events[1][1]["post_id"] == post.post_id
    assert events[1][1]["clues"][0]["value"] == post.text
    assert events[2][1]["clues"] == events[1][1]["clues"]
    assert events[2][1]["owner_profile_text"] == "本人プロフィール文"
    assert events[2][1]["profile_claims"] == []
    assert events[2][1]["self_report_clues"][0]["source"] == "profile_text"
    assert events[-1] == ("done", {"posts_seen": 1})


def test_real_public_search_is_per_run_opt_in_and_marks_only_owner_published_urls() -> None:
    post = Post.model_validate(
        {
            "post_id": "at://did:plc:me00000000000000000000/app.bsky.feed.post/external1",
            "text": "通常の投稿",
            "created_at": "2026-11-10T08:00:00+09:00",
            "images": [],
        }
    )
    calls: list[str] = []
    search_result = ExternalProfileResult(
        id="candidate-id",
        url="https://example.net/blog",
        domain="example.net",
        title="架空ブログ",
        status=ExternalProfileStatus.CANDIDATE,
        owner_evidence=None,
    )

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    async def fetch_profile(_client: AsyncClient, did: str) -> str:
        assert did == REAL_DID
        return "私のブログ: https://example.net/blog"

    async def search(handle: str) -> ExternalLookupResult:
        calls.append(handle)
        return ExternalLookupResult(ExternalLookupStatus.SEARCHED, (search_result,))

    with _real_client(fetch_posts) as client:
        overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
        overrides[get_fetch_profile_text] = lambda: fetch_profile
        overrides[get_external_profile_searcher] = lambda: search
        _login(client)

        opted_out = client.post("/api/diagnose")
        opted_out_event = next(
            data for name, data in _events(opted_out.text) if name == "conclusions"
        )
        assert opted_out_event["external_lookup_status"] == "not_requested"
        assert opted_out_event["external_profile_results"] == []
        assert calls == []

        opted_in = client.post("/api/diagnose", json={"public_web_lookup_consent": True})

    assert opted_in.status_code == 200
    assert calls == ["alice.bsky.social"]
    event = next(data for name, data in _events(opted_in.text) if name == "conclusions")
    assert event["external_lookup_status"] == "searched"
    linked = event["external_profile_results"][0]
    assert linked["status"] == "owner_linked"
    assert linked["owner_evidence"]["kind"] == "profile_text"
    assert str(linked["url"]) == "https://example.net/blog"


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

        async def fetch_profile(_client: AsyncClient, _did: str) -> str:
            return ""

        client.app.dependency_overrides[get_fetch_profile_text] = lambda: fetch_profile  # type: ignore[attr-defined]
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
    assert _events("\n\n".join(events) + "\n\n")[-1] == ("done", {"posts_seen": 12})
