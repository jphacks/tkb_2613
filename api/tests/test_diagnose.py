import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from atproto import AsyncClient
from fastapi.testclient import TestClient
from pydantic import SecretStr

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
    get_photo_place_searcher,
)
from tkb_api.routes.session import get_login
from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION
from tkb_common.schemas import Clue, ClueSource, ClueType, ExternalLookupStatus, Post
from tkb_detect.errors import ForbiddenEndpointError
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig
from tkb_engine.gazetteer import Gazetteer

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DEMO_POST_COUNT = len(json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"])

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


def test_completed_diagnosis_can_be_read_again_only_in_its_session(client: TestClient) -> None:
    assert client.get("/api/diagnosis").status_code == 401
    _login(client)
    assert client.get("/api/diagnosis").status_code == 404

    result = client.post("/api/diagnose", json={"public_web_lookup_consent": True})
    assert result.status_code == 200
    restored = client.get("/api/diagnosis")
    assert restored.status_code == 200
    assert restored.headers["cache-control"] == "no-store, no-transform"
    data = restored.json()
    assert len(data["posts"]) == DEMO_POST_COUNT
    assert len(data["clues"]) > 0
    assert data["deleted"] == []
    assert data["conclusions"] == _events(result.text)[-3][1]["conclusions"]
    assert data["plan"] == _events(result.text)[-2][1]
    streamed_claims = _events(result.text)[-3][1]
    assert data["photo_place_results"] == streamed_claims["photo_place_results"]
    assert {(entry["post_id"], entry["image_index"]) for entry in data["photo_place_results"]} == {
        (post["post_id"], image["index"]) for post in data["posts"] for image in post["images"]
    }
    assert streamed_claims["external_lookup_status"] == "fixture"
    assert data["profile_claims"] == streamed_claims["profile_claims"]
    assert data["profile_relations"] == streamed_claims["profile_relations"]
    evidence_paths = [
        path
        for claim in streamed_claims["profile_claims"]
        for candidate in claim["candidate_pool"]
        for path in candidate["evidence_paths"]
    ]
    assert evidence_paths
    assert {path["provenance"] for path in evidence_paths} <= {
        "direct_disclosure",
        "combined_inference",
        "unclassified",
    }
    restored_paths = [
        path
        for claim in data["profile_claims"]
        for candidate in claim["candidate_pool"]
        for path in candidate["evidence_paths"]
    ]
    assert restored_paths == evidence_paths
    assert data["profile_claim_suggestions"] == streamed_claims["profile_claim_suggestions"]
    assert data["external_profile_results"] == streamed_claims["external_profile_results"]
    assert data["external_lookup_status"] == streamed_claims["external_lookup_status"]

    _login(client)
    assert client.get("/api/diagnosis").status_code == 404


def test_completed_diagnosis_restore_recalculates_candidate_snapshot_after_deletion(
    client: TestClient,
) -> None:
    _login(client)
    result = client.post("/api/diagnose", json={"public_web_lookup_consent": True})
    assert result.status_code == 200
    original = client.get("/api/diagnosis").json()
    session_id = client.cookies.get("tkb_session")
    assert isinstance(session_id, str)
    suggested = original["profile_claim_suggestions"]
    candidate_post_ids = [
        reference["post_id"]
        for claim in original["profile_claims"]
        for candidate in claim["candidate_pool"]
        for path in candidate["evidence_paths"]
        for reference in path["evidence"]
        if reference["post_id"] is not None
    ]
    deleted_post_id = (suggested or candidate_post_ids)[0]
    client.app.state.sessions.mark_deleted(session_id, [deleted_post_id])  # type: ignore[attr-defined]

    restored = client.get("/api/diagnosis")
    assert restored.status_code == 200
    data = restored.json()
    assert data["deleted"] == [deleted_post_id]
    assert data["posts"] == original["posts"]
    assert data["clues"] == original["clues"]
    assert all(
        reference["post_id"] != deleted_post_id
        for claim in data["profile_claims"]
        for candidate in claim["candidate_pool"]
        for path in candidate["evidence_paths"]
        for reference in path["evidence"]
    )
    assert all(
        reference["post_id"] != deleted_post_id
        for relation in data["profile_relations"]
        for path in relation["evidence_paths"]
        for reference in path["evidence"]
    )
    assert deleted_post_id not in data["profile_claim_suggestions"]
    assert deleted_post_id not in data["plan"]["delete"]
    assert all(
        data["clues"][index]["post_id"] != deleted_post_id
        for conclusion in data["conclusions"]
        for index in conclusion["clue_indices"]
    )


def test_mock_diagnose_streams_posts_clues_conclusions_plan_then_done(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts, clues = doc["posts"], doc["clues"]
    events = _events(res.text)
    names = [name for name, _ in events]
    assert names == ["post"] * DEMO_POST_COUNT + ["clues"] * DEMO_POST_COUNT + [
        "conclusions",
        "plan",
        "done",
    ]
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


class FakeBlueskyClient:
    async def get_profile(self, *, actor: str) -> SimpleNamespace:
        assert actor == REAL_DID
        return SimpleNamespace(description="")


REAL_CLIENT = cast(AsyncClient, FakeBlueskyClient())


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


def _real_client(
    fetch_posts: PostsFetcher,
    extractor: Extractor | None = None,
    settings: Settings | None = None,
) -> TestClient:
    """MOCK_MODE=0 の api。ログイン・投稿の取得・手がかりの取り出しを偽物に差し替える。"""

    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=REAL_DID, client=REAL_CLIENT)

    client = _client(settings or Settings(mock_mode=False, max_posts=5))
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


def test_oauth_diagnose_accepts_a_session_without_a_password_client() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})
    calls: list[tuple[AsyncClient, str, int]] = []

    class ReadyExtractor(FakeExtractor):
        async def model_reachable(self, timeout_s: float) -> bool:
            return True

    profile_requests: list[tuple[AsyncClient, str]] = []

    async def fetch_profile(client: AsyncClient, did: str) -> str:
        profile_requests.append((client, did))
        return ""

    async def fetch_posts(client: AsyncClient, did: str, limit: int) -> list[Post]:
        calls.append((client, did, limit))
        return [post]

    settings = Settings(
        mock_mode=False,
        auth_mode="oauth",
        internal_auth_secret="test-only-secret",  # noqa: S106
        max_posts=5,
    )
    with _client(settings) as client:
        overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
        overrides[get_fetch_posts] = lambda: fetch_posts
        overrides[get_fetch_profile_text] = lambda: fetch_profile
        overrides[get_extractor_factory] = lambda: ReadyExtractor
        completed = client.post(
            "/__internal/oauth/complete",
            json={"did": REAL_DID, "handle": "alice.bsky.social"},
            headers={"X-Internal-Auth": "test-only-secret"},
        )
        assert completed.status_code == 200
        res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert len(calls) == 1
    assert isinstance(calls[0][0], AsyncClient)
    assert calls[0][1:] == (REAL_DID, 5)
    assert len(profile_requests) == 1
    assert profile_requests[0][1] == REAL_DID
    assert [name for name, _ in _events(res.text)] == [
        "post",
        "clues",
        "conclusions",
        "plan",
        "done",
    ]


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


def _real_settings(allowed: str) -> Settings:
    return Settings(
        mock_mode=False,
        vlm_base_url="http://10.0.2.15:8000/v1",
        ocr_base_url="http://10.0.2.15:8080",
        model_allowed_host_suffixes=allowed,
    )


def test_extractor_uses_the_allowlist_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env から読んだ許可リストが、環境変数を経由せずに VLM と OCR の両方に効く
    monkeypatch.delenv("MODEL_ALLOWED_HOST_SUFFIXES", raising=False)
    extractor = get_extractor_factory(_real_settings("10.0.2.15"), MINI_GAZETTEER)()
    assert isinstance(extractor, Extractor)


@pytest.mark.parametrize("allowed", ["", "10.0.2.16", "0.2.15"])
def test_extractor_rejects_hosts_outside_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, allowed: str
) -> None:
    # 環境変数に許可があっても、Settings の許可リスト（空なら localhost だけ）が優先される
    monkeypatch.setenv("MODEL_ALLOWED_HOST_SUFFIXES", "10.0.2.15")
    with pytest.raises(ForbiddenEndpointError):
        get_extractor_factory(_real_settings(allowed), MINI_GAZETTEER)()


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
    assert _events("\n\n".join(events) + "\n\n")[-1] == (
        "done",
        {"posts_seen": DEMO_POST_COUNT},
    )


# --- 公開Web検索（Brave）が使えるか ---

FAKE_BRAVE_KEY = "brave-test-key-not-real"  # テスト用の架空の値


@pytest.mark.parametrize(("daily_limit", "available"), [(0, False), (1, True), (3, True)])
def test_photo_place_lookup_requires_a_positive_daily_diagnosis_limit(
    daily_limit: int, available: bool
) -> None:
    settings = Settings(
        mock_mode=False,
        diagnose_daily_limit=daily_limit,
        brave_search_api_key=SecretStr(FAKE_BRAVE_KEY),
    )

    assert settings.photo_place_web_lookup_available is available


@pytest.mark.parametrize(
    ("mock_mode", "key", "daily_limit", "public_available", "photo_place_available"),
    [
        (True, "", 0, True, False),  # profile mock works; photo web lookup remains disabled
        (False, "", 3, False, False),
        (False, "   ", 3, False, False),
        (False, FAKE_BRAVE_KEY, 3, True, True),
        (False, FAKE_BRAVE_KEY, 0, True, False),  # daily limit zero must not disable profile search
    ],
)
def test_features_tell_whether_public_web_lookup_is_available_without_the_key(
    mock_mode: bool,
    key: str,
    daily_limit: int,
    public_available: bool,
    photo_place_available: bool,
) -> None:
    settings = Settings(
        mock_mode=mock_mode,
        demo_fixture_path=FIXTURE,
        brave_search_api_key=SecretStr(key),
        diagnose_daily_limit=daily_limit,
    )
    with _client(settings) as client:
        res = client.get("/api/features")
    assert res.status_code == 200
    assert res.json()["public_web_lookup_available"] is public_available
    assert res.json()["photo_place_web_lookup_available"] is photo_place_available
    assert res.json()["commons_reference_lookup_available"] is False
    # キーの値そのものは返さない
    assert FAKE_BRAVE_KEY not in res.text


def _diagnose_with_consent(key: str) -> tuple[list[str], dict[str, Any]]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})
    searched: list[str] = []

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    async def search(handle: str) -> ExternalLookupResult:
        searched.append(handle)
        return ExternalLookupResult(ExternalLookupStatus.SEARCHED)

    settings = Settings(mock_mode=False, max_posts=5, brave_search_api_key=SecretStr(key))
    with _real_client(fetch_posts, settings=settings) as client:
        client.app.dependency_overrides[get_external_profile_searcher] = lambda: search  # type: ignore[attr-defined]
        _login(client)
        res = client.post("/api/diagnose", json={"public_web_lookup_consent": True})
    assert res.status_code == 200
    conclusions = next(data for name, data in _events(res.text) if name == "conclusions")
    return searched, conclusions


def test_consent_without_a_brave_key_is_not_searched_and_reports_unavailable() -> None:
    searched, conclusions = _diagnose_with_consent("")

    assert searched == []
    assert conclusions["external_lookup_status"] == "unavailable"
    assert conclusions["external_profile_results"] == []


def test_consent_with_a_brave_key_runs_the_search_with_the_session_handle() -> None:
    searched, conclusions = _diagnose_with_consent(FAKE_BRAVE_KEY)

    assert searched == ["alice.bsky.social"]
    assert conclusions["external_lookup_status"] == "searched"


def test_photo_place_search_has_separate_consent_and_mock_never_calls_searcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    reference_calls: list[int] = []

    async def fake_photo_search(results: list[Any], clues: list[Clue]) -> list[Any]:
        calls.append((len(results), len(clues)))
        return results

    async def fake_reference_search(
        results: list[Any], clues: list[Clue], posts: list[Post], *_args: Any
    ) -> list[Any]:
        reference_calls.append(len(results))
        return results

    monkeypatch.setattr("tkb_api.routes.diagnose.search_commons_references", fake_reference_search)

    settings = Settings(
        mock_mode=True,
        demo_fixture_path=FIXTURE,
        mock_event_interval_seconds=0,
        brave_search_api_key=SecretStr(FAKE_BRAVE_KEY),
    )
    with _client(settings) as client:
        client.app.dependency_overrides[get_photo_place_searcher] = lambda: fake_photo_search  # type: ignore[attr-defined]
        _login(client)
        features = client.get("/api/features").json()
        result = client.post(
            "/api/diagnose",
            json={
                "public_web_lookup_consent": False,
                "photo_place_web_lookup_consent": True,
                "photo_place_reference_consent": True,
            },
        )

    assert result.status_code == 200
    assert features["photo_place_web_lookup_available"] is False
    assert features["commons_reference_lookup_available"] is False
    assert calls == []
    assert reference_calls == []
    conclusions = next(data for name, data in _events(result.text) if name == "conclusions")
    assert all(
        item["lookup_status"] != "web_searched" for item in conclusions["photo_place_results"]
    )


def test_commons_reference_search_requires_its_own_live_consent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 手元の data/processed に頼らないよう、判定に使う索引とメッシュ表をここで用意する
    # （CI には公開データがない）。地名表そのものは _client で MINI_GAZETTEER に差し替わる。
    with sqlite3.connect(tmp_path / "places.sqlite3") as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
    (tmp_path / "muni_mesh.parquet").touch()
    reference_calls: list[int] = []
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    async def fake_reference_search(
        results: list[Any], clues: list[Clue], posts: list[Post], *_args: Any
    ) -> list[Any]:
        reference_calls.append(len(results))
        return results

    monkeypatch.setattr("tkb_api.routes.diagnose.search_commons_references", fake_reference_search)
    settings = Settings(
        mock_mode=False,
        commons_reference_lookup_enabled=True,
        diagnose_daily_limit=3,
        max_posts=5,
        gazetteer_dir=tmp_path,
    )
    with _real_client(fetch_posts, settings=settings) as client:
        _login(client)
        features = client.get("/api/features").json()
        result = client.post("/api/diagnose", json={"photo_place_reference_consent": True})

    assert result.status_code == 200
    assert features["commons_reference_lookup_available"] is True
    assert reference_calls == [0]


def test_photo_place_search_consent_does_not_imply_profile_web_consent() -> None:
    calls: list[tuple[int, int]] = []

    async def fake_photo_search(results: list[Any], clues: list[Clue]) -> list[Any]:
        calls.append((len(results), len(clues)))
        return results

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    settings = Settings(
        mock_mode=False,
        max_posts=5,
        brave_search_api_key=SecretStr(FAKE_BRAVE_KEY),
    )
    with _real_client(fetch_posts, settings=settings) as client:
        client.app.dependency_overrides[get_photo_place_searcher] = lambda: fake_photo_search  # type: ignore[attr-defined]
        _login(client)
        result = client.post(
            "/api/diagnose",
            json={
                "public_web_lookup_consent": False,
                "photo_place_web_lookup_consent": True,
            },
        )

    assert result.status_code == 200
    assert calls == [(0, 1)]
    conclusions = next(data for name, data in _events(result.text) if name == "conclusions")
    assert conclusions["external_lookup_status"] == "not_requested"


def test_photo_place_daily_limit_zero_disables_search_even_with_consent_and_key() -> None:
    calls: list[tuple[int, int]] = []

    async def fake_photo_search(results: list[Any], clues: list[Clue]) -> list[Any]:
        calls.append((len(results), len(clues)))
        return results

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"][3]
    post = Post.model_validate({**raw, "images": []})

    async def fetch_posts(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        return [post]

    settings = Settings(
        mock_mode=False,
        max_posts=5,
        diagnose_daily_limit=0,
        brave_search_api_key=SecretStr(FAKE_BRAVE_KEY),
    )
    with _real_client(fetch_posts, settings=settings) as client:
        client.app.dependency_overrides[get_photo_place_searcher] = lambda: fake_photo_search  # type: ignore[attr-defined]
        _login(client)
        features = client.get("/api/features").json()
        result = client.post(
            "/api/diagnose",
            json={"photo_place_web_lookup_consent": True},
        )

    assert result.status_code == 200
    assert features["photo_place_web_lookup_available"] is False
    assert calls == []
