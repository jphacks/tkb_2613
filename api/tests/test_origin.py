"""元に戻せない操作は、本体の画面（CORS_ORIGINS）からの要求だけを受け付ける。"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tkb_api.bluesky import Diagnosis, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.session import SESSION_COOKIE
from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import Gazetteer

SITE = "https://d111.cloudfront.net"
PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
POSTS = [Post.model_validate(p) for p in DOC["posts"]]
CLUES = [Clue.model_validate(c) for c in DOC["clues"]]

# 元に戻せない操作（消す・ログアウト・閲覧リンクを作る／取り消す）
IRREVERSIBLE = [
    ("POST", "/api/delete", {"delete": [POSTS[0].post_id]}),
    ("DELETE", "/api/session", None),
    ("POST", "/api/result-link", None),
    ("DELETE", "/api/result-link", {"token": "a" * 43}),
]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        mock_mode=True,
        cors_origins=[SITE],
        demo_fixture_path=FIXTURE,
        share_db_path=tmp_path / "shares.sqlite3",
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: Gazetteer()
    with TestClient(app) as c:
        res = c.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
        assert res.status_code == 200
        store: SessionStore = c.app.state.sessions  # type: ignore[attr-defined]
        store.set_diagnosis(
            c.cookies[SESSION_COOKIE], Diagnosis(posts=tuple(POSTS), clues=tuple(CLUES))
        )
        yield c


@pytest.mark.parametrize(("method", "path", "body"), IRREVERSIBLE)
@pytest.mark.parametrize("origin", ["https://evil.example", "null", None])
def test_irreversible_operations_refuse_other_sites(
    client: TestClient, method: str, path: str, body: object, origin: str | None
) -> None:
    headers = {} if origin is None else {"Origin": origin}

    res = client.request(method, path, json=body, headers=headers)

    assert res.status_code == 403
    assert res.json()["detail"] == "同じサイトから操作してください"
    # 何も起きていない（ログイン中のまま、診断も残っている）
    assert client.get("/api/session").status_code == 200
    assert client.get("/api/diagnosis").json()["deleted"] == []


@pytest.mark.parametrize(("method", "path", "body"), IRREVERSIBLE)
def test_irreversible_operations_accept_the_site_itself(
    client: TestClient, method: str, path: str, body: object
) -> None:
    res = client.request(method, path, json=body, headers={"Origin": f"{SITE}/"})

    assert res.status_code in {200, 204}


def test_reads_do_not_need_an_origin(client: TestClient) -> None:
    assert client.get("/api/session").status_code == 200
    assert client.get("/api/diagnosis").status_code == 200
    assert client.post("/api/simulate", json={"delete": []}).status_code == 200
