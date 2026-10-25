"""明示的な閲覧リンクだけが、別ブラウザや API 再起動後に読める。"""

import stat
from pathlib import Path

from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.shares import ShareStore
from tkb_engine.gazetteer import Gazetteer

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
PASSWORD = "test password"  # noqa: S105  架空のテスト値


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: Gazetteer()
    return TestClient(app)


def test_result_link_requires_the_owners_finished_diagnosis_and_is_read_only(
    tmp_path: Path,
) -> None:
    settings = Settings(
        mock_mode=True,
        demo_fixture_path=FIXTURE,
        mock_event_interval_seconds=0,
        share_db_path=tmp_path / "private" / "shares.sqlite3",
    )
    with _client(settings) as owner:
        assert owner.post("/api/result-link").status_code == 401
        assert owner.post("/api/shared-result", json={"token": "x" * 43}).status_code == 404
        owner.post("/api/session", json={"handle": "demo", "password": PASSWORD})
        assert owner.post("/api/result-link").status_code == 404
        assert owner.post("/api/diagnose").status_code == 200
        response = owner.post("/api/result-link")
        assert response.status_code == 200
        token = response.json()["token"]
        assert len(token) >= 32
        assert stat.S_IMODE(settings.share_db_path.stat().st_mode) == 0o600

    # API プロセスが作り直されても、リンクを知る人はログインなしで閲覧できる。
    with _client(settings) as viewer:
        shared = viewer.post("/api/shared-result", json={"token": token})
        assert shared.status_code == 200
        assert shared.headers["cache-control"] == "no-store, no-transform"
        assert shared.json()["posts"]
        assert shared.json()["conclusions"]
        assert shared.json()["plan"]["posts"]
        assert viewer.post("/api/delete", json={"delete": []}).status_code == 401
        assert viewer.post("/api/simulate", json={"delete": []}).status_code == 401
        assert viewer.post("/api/shared-result", json={"token": "y" * 43}).status_code == 404


def test_result_link_expires(tmp_path: Path) -> None:
    now = 1000.0
    store = ShareStore(tmp_path / "shares.sqlite3", 60, clock=lambda: now)
    token = store.create({"posts": []}, "did:plc:owner")
    assert store.get(token) == {"posts": []}
    now += 60
    assert store.get(token) is None
    store.close()


def test_only_the_owner_can_revoke_a_result_link(tmp_path: Path) -> None:
    store = ShareStore(tmp_path / "shares.sqlite3", 60)
    token = store.create({"posts": []}, "did:plc:owner")
    store.revoke(token, "did:plc:other")
    assert store.get(token) is not None
    store.revoke(token, "did:plc:owner")
    assert store.get(token) is None
    store.close()
