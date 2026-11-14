"""ログインなしの体験デモ。架空アカウントの表だけを使い、外部には接続しない。"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from tkb_api import pipeline
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes import demo
from tkb_api.routes.diagnose import get_gazetteer
from tkb_engine.gazetteer import Gazetteer

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
POST_IDS = [p["post_id"] for p in DOC["posts"]]
GYM_POST = next(i for i in POST_IDS if i.endswith("000002"))


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: Gazetteer()
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    # 本番と同じ MOCK_MODE=0。モデルの接続先を設定しても、デモは使わない
    settings = Settings(
        mock_mode=False,
        demo_fixture_path=FIXTURE,
        vlm_base_url="http://vlm.example.test/v1",
        share_enabled=False,
    )
    with _client(settings) as c, respx.mock(assert_all_called=False) as router:
        yield c
        assert not router.calls  # Bluesky にもモデルにも接続しない


def test_demo_diagnosis_needs_no_login_and_returns_the_fictional_account(
    client: TestClient,
) -> None:
    res = client.get("/api/demo/diagnosis")

    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store, no-transform"
    body = res.json()
    assert body["demo"] is True
    assert [p["post_id"] for p in body["posts"]] == POST_IDS
    assert len(body["clues"]) == len(DOC["clues"])
    assert "conclusions" not in body
    assert len(body["profile_claims"]) == 29
    assert isinstance(body["profile_relations"], list)
    assert body["profile_claim_suggestions"] == body["plan"]["delete"]
    assert set(body["plan"]) == {"delete", "broken", "after", "posts"}
    assert len(body["plan"]["after"]) == 29
    assert "set-cookie" not in res.headers


def test_demo_simulate_drops_the_selected_posts(client: TestClient) -> None:
    res = client.post("/api/demo/simulate", json={"delete": [GYM_POST]})

    assert res.status_code == 200
    body = res.json()
    assert body["delete"] == [GYM_POST]
    assert "routine" in body["broken"]
    assert len(body["after"]) == 29
    for claim_set in body["after"]:
        for candidate in claim_set["candidate_pool"]:
            assert all(ref["post_id"] != GYM_POST for ref in candidate["evidence"])


def test_demo_simulate_matches_the_plan(client: TestClient) -> None:
    plan = client.get("/api/demo/diagnosis").json()["plan"]

    body = client.post("/api/demo/simulate", json={"delete": plan["delete"]}).json()

    assert body["after"] == plan["after"]
    assert body["broken"] == plan["broken"]


@pytest.mark.parametrize(
    "payload",
    [
        {"delete": ["at://did:plc:someoneelse/app.bsky.feed.post/3kxxxx"]},
        {"delete": [GYM_POST], "did": "did:plc:someoneelse"},
        {"delete": "not-a-list"},
    ],
)
def test_demo_simulate_rejects_other_posts_and_extra_fields(
    client: TestClient, payload: dict[str, object]
) -> None:
    res = client.post("/api/demo/simulate", json=payload)

    assert res.status_code == 422
    assert "someoneelse" not in res.text


def test_demo_has_no_delete_endpoint(client: TestClient) -> None:
    assert client.post("/api/demo/delete", json={"delete": [GYM_POST]}).status_code in {404, 405}


def test_demo_reports_unavailable_without_the_fixture(tmp_path: Path) -> None:
    settings = Settings(demo_fixture_path=tmp_path / "missing.json", share_enabled=False)
    with _client(settings) as client:
        res = client.get("/api/demo/diagnosis")

    assert res.status_code == 503
    assert "missing" not in res.text


class _Counter:
    """demo のルール推理と計画の関数を包み、呼ばれた回数を数える。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = {"infer": 0, "plan": 0}
        infer = demo.infer
        plan = pipeline.plan_claims_json

        def counted_infer(*args: Any, **kwargs: Any) -> Any:
            self.calls["infer"] += 1
            return infer(*args, **kwargs)

        def counted_plan(*args: Any, **kwargs: Any) -> Any:
            self.calls["plan"] += 1
            return plan(*args, **kwargs)

        monkeypatch.setattr(demo, "infer", counted_infer)
        monkeypatch.setattr(demo, "plan_claims_json", counted_plan)
        monkeypatch.setattr(demo, "_cached", None)


def _fixed_gazetteer_client(settings: Settings, gazetteer: Gazetteer) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: gazetteer
    return TestClient(app)


def test_demo_diagnosis_is_computed_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = _Counter(monkeypatch)
    settings = Settings(demo_fixture_path=FIXTURE, share_enabled=False)

    with _fixed_gazetteer_client(settings, Gazetteer()) as client:
        first = client.get("/api/demo/diagnosis")
        second = client.get("/api/demo/diagnosis")

    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "application/json"
    assert first.content == second.content
    assert counter.calls == {"infer": 1, "plan": 1}


def test_demo_diagnosis_cache_follows_the_settings_and_gazetteer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    counter = _Counter(monkeypatch)
    copy = tmp_path / "demo.json"
    copy.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    gazetteer = Gazetteer()

    for path, gaz in [(FIXTURE, gazetteer), (copy, gazetteer), (copy, Gazetteer())]:
        settings = Settings(demo_fixture_path=path, share_enabled=False)
        with _fixed_gazetteer_client(settings, gaz) as client:
            assert client.get("/api/demo/diagnosis").status_code == 200

    # 表のパスか地名の表が変われば、前の応答を使わずに計算し直す
    assert counter.calls == {"infer": 3, "plan": 3}


def test_demo_diagnosis_is_computed_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 差し替えなしの本番と同じ形。設定は環境変数から読む
    monkeypatch.setenv("DEMO_FIXTURE_PATH", str(FIXTURE))
    monkeypatch.setenv("GAZETTEER_DIR", str(tmp_path))
    monkeypatch.setenv("SHARE_ENABLED", "0")
    counter = _Counter(monkeypatch)

    with TestClient(create_app()) as client:
        assert counter.calls == {"infer": 1, "plan": 1}
        bodies = [client.get("/api/demo/diagnosis") for _ in range(3)]

    assert all(res.status_code == 200 for res in bodies)
    assert bodies[0].json()["demo"] is True
    assert counter.calls == {"infer": 1, "plan": 1}


def test_demo_startup_survives_a_missing_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEMO_FIXTURE_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("GAZETTEER_DIR", str(tmp_path))
    monkeypatch.setenv("SHARE_ENABLED", "0")
    counter = _Counter(monkeypatch)

    with TestClient(create_app()) as client:
        res = client.get("/api/demo/diagnosis")

    assert res.status_code == 503
    assert "missing" not in res.text
    assert counter.calls == {"infer": 0, "plan": 0}
