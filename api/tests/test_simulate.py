import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tkb_api.bluesky import Diagnosis, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_gazetteer
from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import Gazetteer

# ブラウザは POST・DELETE に Origin を付ける（元に戻せない操作は Origin を確かめる）
BROWSER_ORIGIN = {"Origin": "http://localhost:3000"}

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
POST_IDS = [p["post_id"] for p in DOC["posts"]]
# 「25歳になりました」の投稿、宛名の郵便番号・住所の投稿、「毎週火曜のジム」の投稿
NAME_POST = next(i for i in POST_IDS if i.endswith("000006"))
ADDRESS_POST = next(i for i in POST_IDS if i.endswith("000009"))
GYM_POST = next(i for i in POST_IDS if i.endswith("000002"))
BIRTHDAY_POST = next(i for i in POST_IDS if i.endswith("000006"))

NEZU_MESH = "53394661"
MINI_GAZETTEER = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": NEZU_MESH},
        {"station_name": "根岸", "mesh_1km": "52396700"},
    ],
    postal=[{"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"}],
    muni_meshes={"13105": {NEZU_MESH}},
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(mock_mode=True, demo_fixture_path=FIXTURE, mock_event_interval_seconds=0)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: MINI_GAZETTEER
    with TestClient(app, headers=BROWSER_ORIGIN) as c:
        yield c


def _login(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    assert res.status_code == 200


def _diagnose(client: TestClient) -> dict[str, Any]:
    """診断を最後まで流し、conclusions と plan の data を返す。"""
    res = client.post("/api/diagnose")
    assert res.status_code == 200
    events: dict[str, Any] = {}
    for block in res.text.split("\n\n"):
        if block.startswith("event: "):
            fields = dict(line.split(": ", 1) for line in block.split("\n"))
            events[fields["event"]] = json.loads(fields["data"])
    return events


def test_diagnose_streams_the_plan_before_done(client: TestClient) -> None:
    _login(client)

    events = _diagnose(client)

    proposal = events["plan"]
    assert proposal["delete"] == events["conclusions"]["profile_claim_suggestions"]
    assert {BIRTHDAY_POST, ADDRESS_POST} <= set(proposal["delete"])
    assert {"given_name", "age", "birthday", "home_nearest_station", "residential_area"} <= set(
        proposal["broken"]
    )
    assert len(proposal["after"]) == 29
    supported_after = {c["attribute"] for c in proposal["after"] if c["candidates"]}
    assert not supported_after & {
        "given_name",
        "age",
        "birthday",
        "home_nearest_station",
        "residential_area",
    }
    by_post = {p["post_id"]: p["broken"] for p in proposal["posts"]}
    assert set(proposal["delete"]) <= by_post.keys()


def test_simulate_requires_login(client: TestClient) -> None:
    assert client.post("/api/simulate", json={"delete": []}).status_code == 401


def test_simulate_requires_a_finished_diagnosis(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/simulate", json={"delete": [ADDRESS_POST]})

    assert res.status_code == 409


def test_simulate_breaks_the_station_when_the_address_post_is_deleted(client: TestClient) -> None:
    _login(client)
    _diagnose(client)

    res = client.post("/api/simulate", json={"delete": [ADDRESS_POST]})

    assert res.status_code == 200
    body = res.json()
    assert body["delete"] == [ADDRESS_POST]
    assert "home_nearest_station" in body["broken"]
    assert len(body["after"]) == 29
    assert "narrowing" in body
    # 残った候補の根拠経路は、消した投稿の手がかりを指さない
    for claim_set in body["after"]:
        for candidate in claim_set["candidate_pool"]:
            assert all(ref["post_id"] != ADDRESS_POST for ref in candidate["evidence"])
    routine = next(c for c in body["after"] if c["attribute"] == "routine")
    assert routine["candidates"]


def test_simulate_with_nothing_selected_breaks_nothing(client: TestClient) -> None:
    _login(client)
    profile_claims = _diagnose(client)["conclusions"]["profile_claims"]

    body = client.post("/api/simulate", json={"delete": []}).json()

    assert body["broken"] == []
    assert body["after"] == profile_claims


def test_simulate_rejects_posts_that_were_not_diagnosed(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    other = "at://did:plc:someoneelse/app.bsky.feed.post/3kxxxx"

    res = client.post("/api/simulate", json={"delete": [other]})

    assert res.status_code == 422
    assert other not in res.text


def test_simulate_starts_from_the_posts_left_after_a_delete(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    assert client.post("/api/delete", json={"delete": [GYM_POST]}).status_code == 200

    res = client.post("/api/simulate", json={"delete": []})

    assert res.status_code == 200
    body = res.json()
    # 消したジムの投稿の分（決まった外出）は、仮除外の結果に戻ってこない
    assert body["broken"] == []
    routine = next(c for c in body["after"] if c["attribute"] == "routine")
    assert routine["candidates"] == []
    # 復元した候補セットと同じ
    assert body["after"] == client.get("/api/diagnosis").json()["profile_claims"]
    assert "narrowing" in body


def test_simulate_matches_the_restored_plan_after_a_delete(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    client.post("/api/delete", json={"delete": [GYM_POST]})
    plan = client.get("/api/diagnosis").json()["plan"]
    assert plan["delete"]

    body = client.post("/api/simulate", json={"delete": plan["delete"]}).json()

    assert body["after"] == plan["after"]
    assert body["broken"] == plan["broken"]


def test_simulate_rejects_posts_that_were_already_deleted(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    client.post("/api/delete", json={"delete": [GYM_POST]})

    res = client.post("/api/simulate", json={"delete": [GYM_POST]})

    assert res.status_code == 422
    assert GYM_POST not in res.text


def test_simulate_rejects_unknown_fields(client: TestClient) -> None:
    _login(client)
    _diagnose(client)

    res = client.post("/api/simulate", json={"delete": [], "handle": "someone.bsky.social"})

    assert res.status_code == 422


def test_logout_discards_the_diagnosis(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    client.delete("/api/session")
    _login(client)

    assert client.post("/api/simulate", json={"delete": []}).status_code == 409


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        posts=tuple(Post.model_validate(p) for p in DOC["posts"]),
        clues=tuple(Clue.model_validate(c) for c in DOC["clues"]),
    )


def test_store_keeps_the_diagnosis_with_the_session_until_it_expires() -> None:
    now = [0.0]
    store = SessionStore(ttl_seconds=10, clock=lambda: now[0])
    session_id = store.create(LoginResult(handle="a", did="did:plc:a", client=None))

    store.set_diagnosis(session_id, _diagnosis())
    assert store.get_diagnosis(session_id) == _diagnosis()

    now[0] = 10.0
    assert store.get(session_id) is None
    assert store.get_diagnosis(session_id) is None


def test_store_clears_the_diagnosis_on_delete_and_on_none() -> None:
    store = SessionStore(ttl_seconds=10)
    session_id = store.create(LoginResult(handle="a", did="did:plc:a", client=None))

    store.set_diagnosis(session_id, _diagnosis())
    store.set_diagnosis(session_id, None)
    assert store.get_diagnosis(session_id) is None

    store.set_diagnosis(session_id, _diagnosis())
    store.delete(session_id)
    assert store.get_diagnosis(session_id) is None


def test_store_ignores_a_diagnosis_for_an_unknown_session() -> None:
    store = SessionStore(ttl_seconds=10)

    store.set_diagnosis("unknown", _diagnosis())

    assert store.get_diagnosis("unknown") is None
