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
    with TestClient(app) as c:
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
    assert set(proposal["delete"]) == {BIRTHDAY_POST, ADDRESS_POST, GYM_POST}
    assert {"station", "active_time", "routine"} <= set(proposal["broken"])
    # 生年月日を先に守り、場所や決まった外出も消す。
    remaining = {c["attribute"] for c in proposal["after"]}
    assert not remaining & {"birthday", "age", "station", "active_time", "routine"}
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
    clues = _diagnose(client)["conclusions"]["clues"]

    res = client.post("/api/simulate", json={"delete": [ADDRESS_POST]})

    assert res.status_code == 200
    body = res.json()
    assert body["delete"] == [ADDRESS_POST]
    assert {"station", "active_time", "home_area"} <= set(body["broken"])
    # 残った結論の根拠の番号は、診断の clues での番号。消した投稿の手がかりは指さない
    for conclusion in body["after"]:
        assert all(clues[i]["post_id"] != ADDRESS_POST for i in conclusion["clue_indices"])
    assert any(c["attribute"] == "routine" for c in body["after"])


def test_simulate_with_nothing_selected_breaks_nothing(client: TestClient) -> None:
    _login(client)
    conclusions = _diagnose(client)["conclusions"]["conclusions"]

    body = client.post("/api/simulate", json={"delete": []}).json()

    assert body["broken"] == []
    assert body["after"] == conclusions


def test_simulate_rejects_posts_that_were_not_diagnosed(client: TestClient) -> None:
    _login(client)
    _diagnose(client)
    other = "at://did:plc:someoneelse/app.bsky.feed.post/3kxxxx"

    res = client.post("/api/simulate", json={"delete": [other]})

    assert res.status_code == 422
    assert other not in res.text


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
