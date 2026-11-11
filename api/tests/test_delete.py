import asyncio
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from atproto import AsyncClient
from atproto_client.exceptions import AtProtocolError
from fastapi.testclient import TestClient

from tkb_api.bluesky import Diagnosis, LoginResult, SessionStore, delete_own_posts, is_own_post_uri
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.delete import get_delete_posts
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.session import SESSION_COOKIE, get_login
from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import Gazetteer

# ブラウザは POST・DELETE に Origin を付ける（元に戻せない操作は Origin を確かめる）
BROWSER_ORIGIN = {"Origin": "http://localhost:3000"}

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
POSTS = [Post.model_validate(p) for p in DOC["posts"]]
CLUES = [Clue.model_validate(c) for c in DOC["clues"]]
POST_IDS = [p.post_id for p in POSTS]
# 「毎週火曜のジム」の投稿と、宛名の郵便番号・住所の投稿
GYM_POST = next(i for i in POST_IDS if i.endswith("000002"))
ADDRESS_POST = next(i for i in POST_IDS if i.endswith("000009"))
DEMO_DID = GYM_POST.removeprefix("at://").split("/")[0]
REAL_CLIENT = cast(AsyncClient, object())

NEZU_MESH = "53394661"
MINI_GAZETTEER = Gazetteer(
    stations=[{"station_name": "根津", "mesh_1km": NEZU_MESH}],
    postal=[{"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"}],
    muni_meshes={"13105": {NEZU_MESH}},
)


async def _must_not_delete(_client: AsyncClient, _did: str, _ids: Sequence[str]) -> list[str]:
    raise AssertionError("モックでは Bluesky に接続しない")


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: MINI_GAZETTEER
    app.dependency_overrides[get_delete_posts] = lambda: _must_not_delete
    return TestClient(app, headers=BROWSER_ORIGIN)


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(mock_mode=True, demo_fixture_path=FIXTURE, mock_event_interval_seconds=0)
    with _client(settings) as c:
        yield c


def _login(client: TestClient) -> None:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    assert res.status_code == 200


def _seed_diagnosis(client: TestClient) -> None:
    """診断を流さずに、セッションに診断の結果を置く。"""
    store: SessionStore = client.app.state.sessions  # type: ignore[attr-defined]
    store.set_diagnosis(
        client.cookies[SESSION_COOKIE], Diagnosis(posts=tuple(POSTS), clues=tuple(CLUES))
    )


def test_delete_requires_login(client: TestClient) -> None:
    assert client.post("/api/delete", json={"delete": [GYM_POST]}).status_code == 401


def test_delete_requires_a_finished_diagnosis(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/delete", json={"delete": [GYM_POST]})

    assert res.status_code == 409


def test_delete_rejects_posts_that_were_not_diagnosed(client: TestClient) -> None:
    _login(client)
    _seed_diagnosis(client)
    other = "at://did:plc:someone-else/app.bsky.feed.post/3kzzz"

    res = client.post("/api/delete", json={"delete": [GYM_POST, other]})

    assert res.status_code == 422
    assert other not in res.text


@pytest.mark.parametrize("ids", [[], [GYM_POST] * 11])
def test_delete_rejects_an_empty_or_too_long_list(client: TestClient, ids: list[str]) -> None:
    _login(client)
    _seed_diagnosis(client)

    assert client.post("/api/delete", json={"delete": ids}).status_code == 422


def test_delete_accepts_only_json(client: TestClient) -> None:
    # 別のサイトのフォームから text/plain で送らせても消えない
    _login(client)
    _seed_diagnosis(client)

    res = client.post(
        "/api/delete",
        content=json.dumps({"delete": [GYM_POST]}),
        headers={"Content-Type": "text/plain"},
    )

    assert res.status_code == 422


def test_mock_delete_does_not_contact_bluesky_and_rediagnoses(client: TestClient) -> None:
    _login(client)
    _seed_diagnosis(client)

    res = client.post("/api/delete", json={"delete": [GYM_POST, GYM_POST]})

    assert res.status_code == 200
    body: dict[str, Any] = res.json()
    assert body["delete"] == [GYM_POST]
    assert body["failed"] == []
    assert "routine" in body["broken"]
    assert all(c["attribute"] != "routine" for c in body["after"])


def test_deleted_posts_stay_out_of_the_restored_diagnosis(client: TestClient) -> None:
    _login(client)
    _seed_diagnosis(client)
    deleted = client.post("/api/delete", json={"delete": [GYM_POST]}).json()

    res = client.get("/api/diagnosis")

    assert res.status_code == 200
    data: dict[str, Any] = res.json()
    assert data["deleted"] == [GYM_POST]
    # 投稿と手がかりは診断時のまま（番号を変えない）
    assert [p["post_id"] for p in data["posts"]] == POST_IDS
    assert len(data["clues"]) == len(CLUES)
    # 消した投稿は削除候補にならず、崩れた項目は結論にない
    assert GYM_POST not in data["plan"]["delete"]
    assert all(p["post_id"] != GYM_POST for p in data["plan"]["posts"])
    assert all(c["attribute"] != "routine" for c in data["conclusions"])
    # 結論の番号は診断時の clues での番号で、消した投稿の手がかりを指さない
    assert data["conclusions"] == deleted["after"]
    for conclusion in [*data["conclusions"], *data["plan"]["after"]]:
        for i in conclusion["clue_indices"]:
            assert data["clues"][i]["post_id"] != GYM_POST


def test_restored_plan_numbers_match_the_simulation_from_the_remaining_posts(
    client: TestClient,
) -> None:
    _login(client)
    _seed_diagnosis(client)
    client.post("/api/delete", json={"delete": [GYM_POST]})

    data = client.get("/api/diagnosis").json()

    plan = data["plan"]
    assert plan["delete"]  # デモの投稿では、ジムの投稿を消しても候補が残る
    again = client.post("/api/delete", json={"delete": plan["delete"]}).json()
    # 復元した plan は、残った投稿から実際に消したときの結果と同じ（番号も同じ）
    assert again["after"] == plan["after"]
    assert again["broken"] == plan["broken"]


def test_already_deleted_posts_cannot_be_deleted_again(client: TestClient) -> None:
    _login(client)
    _seed_diagnosis(client)
    assert client.post("/api/delete", json={"delete": [GYM_POST]}).status_code == 200

    res = client.post("/api/delete", json={"delete": [GYM_POST]})

    assert res.status_code == 422


def test_a_second_delete_starts_from_the_posts_left_after_the_first(client: TestClient) -> None:
    _login(client)
    _seed_diagnosis(client)
    client.post("/api/delete", json={"delete": [GYM_POST]})

    body = client.post("/api/delete", json={"delete": [ADDRESS_POST]}).json()

    assert body["delete"] == [ADDRESS_POST]
    # 1回目に消したジムの投稿の分は、2回目の結果に戻ってこない
    assert "routine" not in body["broken"]
    assert all(c["attribute"] != "routine" for c in body["after"])
    assert client.get("/api/diagnosis").json()["deleted"] == [GYM_POST, ADDRESS_POST]


def _real_client() -> TestClient:
    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=DEMO_DID, client=REAL_CLIENT)

    client = _client(Settings(mock_mode=False))
    client.app.dependency_overrides[get_login] = lambda: login  # type: ignore[attr-defined]
    return client


def test_real_delete_deletes_as_the_session_account_and_reports_failures() -> None:
    calls: list[tuple[AsyncClient, str, list[str]]] = []

    async def delete_posts(client: AsyncClient, did: str, ids: Sequence[str]) -> list[str]:
        calls.append((client, did, list(ids)))
        return [GYM_POST]  # 住所の投稿は消せなかった

    with _real_client() as client:
        client.app.dependency_overrides[get_delete_posts] = lambda: delete_posts  # type: ignore[attr-defined]
        _login(client)
        _seed_diagnosis(client)

        res = client.post("/api/delete", json={"delete": [ADDRESS_POST, GYM_POST]})
        restored = client.get("/api/diagnosis").json()

    assert res.status_code == 200
    assert calls == [(REAL_CLIENT, DEMO_DID, [ADDRESS_POST, GYM_POST])]
    body = res.json()
    assert body["delete"] == [GYM_POST]
    assert body["failed"] == [ADDRESS_POST]
    # 消せなかった住所の投稿の分は崩れない
    assert "routine" in body["broken"]
    assert "station" not in body["broken"]
    # 消せた投稿だけを記録する
    assert restored["deleted"] == [GYM_POST]


def test_is_own_post_uri_accepts_only_the_session_accounts_posts() -> None:
    me = "did:plc:me"
    assert is_own_post_uri("at://did:plc:me/app.bsky.feed.post/3kabc", me)
    assert not is_own_post_uri("at://did:plc:other/app.bsky.feed.post/3kabc", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.like/3kabc", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/3k/x", me)
    assert not is_own_post_uri("at://did:plc:mex/app.bsky.feed.post/3kabc", me)


def test_is_own_post_uri_validates_rkey_charset() -> None:
    me = "did:plc:me"
    # 実在する形の rkey（TID やハイフン等）は許可
    assert is_own_post_uri("at://did:plc:me/app.bsky.feed.post/3jwdwj2ctlk26", me)
    assert is_own_post_uri("at://did:plc:me/app.bsky.feed.post/a.b-c_d~e", me)
    # rkey に許可外の文字（%・改行・空白・?）や、. / .. 単体が入るものは拒否
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/%2e%2e%2f3x", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/a\nb", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/a b", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/a?x=1", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/.", me)
    assert not is_own_post_uri("at://did:plc:me/app.bsky.feed.post/..", me)


class FakeBluesky:
    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.deleted: list[str] = []

    async def delete_post(self, post_uri: str) -> bool:
        if post_uri in self.failing:
            raise AtProtocolError
        self.deleted.append(post_uri)
        return True


def test_delete_own_posts_skips_others_posts_and_keeps_going_after_a_failure() -> None:
    me = "did:plc:me"
    mine = [f"at://{me}/app.bsky.feed.post/3k{i}" for i in range(3)]
    others = "at://did:plc:other/app.bsky.feed.post/3kx"
    fake = FakeBluesky(failing={mine[0]})

    deleted = asyncio.run(
        delete_own_posts(cast(AsyncClient, fake), me, [mine[0], others, mine[1], mine[2]])
    )

    assert deleted == [mine[1], mine[2]]
    assert fake.deleted == [mine[1], mine[2]]
