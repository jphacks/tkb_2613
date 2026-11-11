"""ログインなしの体験デモ。架空アカウントの表だけを使い、外部には接続しない。"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
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
    assert body["conclusions"]
    assert set(body["plan"]) == {"delete", "broken", "after", "posts"}
    for conclusion in body["conclusions"]:
        assert all(0 <= i < len(body["clues"]) for i in conclusion["clue_indices"])
    assert "set-cookie" not in res.headers


def test_demo_simulate_drops_the_selected_posts(client: TestClient) -> None:
    clues = client.get("/api/demo/diagnosis").json()["clues"]

    res = client.post("/api/demo/simulate", json={"delete": [GYM_POST]})

    assert res.status_code == 200
    body = res.json()
    assert body["delete"] == [GYM_POST]
    assert "routine" in body["broken"]
    for conclusion in body["after"]:
        assert all(clues[i]["post_id"] != GYM_POST for i in conclusion["clue_indices"])


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
