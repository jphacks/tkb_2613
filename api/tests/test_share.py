"""明示的な閲覧リンクだけが、別ブラウザや API 再起動後に読める。"""

import logging
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.share import _candidate_snapshot
from tkb_api.shares import ShareStore
from tkb_common.schemas import PROFILE_DIAGNOSED_ATTRIBUTES
from tkb_engine.gazetteer import Gazetteer

# ブラウザは POST・DELETE に Origin を付ける（元に戻せない操作は Origin を確かめる）
BROWSER_ORIGIN = {"Origin": "http://localhost:3000"}

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
PASSWORD = "test password"  # noqa: S105  架空のテスト値


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: Gazetteer()
    return TestClient(app, headers=BROWSER_ORIGIN)


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
        if os.name == "posix":
            assert stat.S_IMODE(settings.share_db_path.stat().st_mode) == 0o600

    # API プロセスが作り直されても、リンクを知る人はログインなしで閲覧できる。
    with _client(settings) as viewer:
        shared = viewer.post("/api/shared-result", json={"token": token})
        assert shared.status_code == 200
        assert shared.headers["cache-control"] == "no-store, no-transform"
        assert shared.json()["posts"]
        assert "conclusions" not in shared.json()
        assert len(shared.json()["profile_claims"]) == len(PROFILE_DIAGNOSED_ATTRIBUTES)
        assert shared.json()["plan"]["posts"]
        assert viewer.post("/api/delete", json={"delete": []}).status_code == 401
        assert viewer.post("/api/simulate", json={"delete": []}).status_code == 401
        assert viewer.post("/api/shared-result", json={"token": "y" * 43}).status_code == 404


def test_old_candidate_share_drops_redundant_conclusions_without_recomputing() -> None:
    legacy_conclusion = {
        "rule": "W1",
        "attribute": "home_walk_area",
        "value": "根津駅から徒歩4分",
        "clue_indices": [1],
        "note": "legacy saved value",
    }
    payload = {
        "posts": [],
        "clues": [],
        "profile_claims": [
            {
                "attribute": "home_nearest_station",
                "status": "unknown",
                "candidates": [],
                "candidate_pool": [],
                "conflicting_evidence": [],
                "reason": "no_grounded_rule",
            }
        ],
        "conclusions": [legacy_conclusion],
        "plan": {
            "delete": [],
            "broken": [],
            "before": [legacy_conclusion],
            "after": [legacy_conclusion],
            "posts": [],
        },
    }

    result = _candidate_snapshot(payload)

    assert "conclusions" not in result
    assert result["profile_claims"] == payload["profile_claims"]
    assert result["plan"] == payload["plan"]


def test_legacy_shared_links_are_returned_unchanged_until_expiry(tmp_path: Path) -> None:
    settings = _mock_settings(tmp_path / "legacy.sqlite3", share_enabled=True)
    legacy = {
        "posts": [],
        "clues": [],
        "conclusions": [
            {
                "rule": "R3",
                "attribute": "routine",
                "value": "毎週火曜",
                "clue_indices": [],
                "note": "",
            }
        ],
        "plan": {
            "delete": [],
            "broken": ["routine"],
            "before": [
                {
                    "rule": "R3",
                    "attribute": "routine",
                    "value": "火曜の夜勤",
                    "clue_indices": [],
                    "note": "保存済み",
                }
            ],
            "after": [
                {
                    "rule": "R3",
                    "attribute": "routine",
                    "value": "火曜の夜勤",
                    "clue_indices": [],
                    "note": "保存済み",
                }
            ],
            "posts": [],
        },
    }
    with _client(settings) as client:
        store: ShareStore = client.app.state.shares  # type: ignore[attr-defined]
        token = store.create(legacy, "did:plc:legacy")
        response = client.post("/api/shared-result", json={"token": token})
        assert response.status_code == 200
        assert response.json() == legacy
        # Reading does not rewrite or expire the saved snapshot.
        assert store.get(token) == legacy


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


# --- SHARE_ENABLED=0（公開中の本番） ---


def test_features_tell_the_screen_whether_result_links_are_on(tmp_path: Path) -> None:
    for enabled in (True, False):
        settings = Settings(share_enabled=enabled, share_db_path=tmp_path / f"{enabled}.sqlite3")
        with _client(settings) as client:
            res = client.get("/api/features")  # ログインなしで読める
            assert res.status_code == 200
            assert res.json() == {
                "share_enabled": enabled,
                "auth_mode": "app_password",
                "public_web_lookup_available": True,  # 既定はモック
                "photo_place_web_lookup_available": False,
                "commons_reference_lookup_available": False,  # 既定off・モックでは使わない
            }
            assert res.headers["cache-control"] == "no-store, no-transform"


def test_result_links_are_refused_and_nothing_is_saved_when_disabled(tmp_path: Path) -> None:
    db = tmp_path / "private" / "shares.sqlite3"
    settings = Settings(
        mock_mode=True,
        demo_fixture_path=FIXTURE,
        mock_event_interval_seconds=0,
        share_db_path=db,
        share_enabled=False,
    )
    with _client(settings) as client:
        # ログインしていなければ、これまでどおり先に 401
        assert client.post("/api/result-link").status_code == 401
        client.post("/api/session", json={"handle": "demo", "password": PASSWORD})
        assert client.post("/api/diagnose").status_code == 200

        responses = [
            client.post("/api/result-link"),
            client.request("DELETE", "/api/result-link", json={"token": "x" * 43}),
            client.post("/api/shared-result", json={"token": "x" * 43}),
        ]

    for res in responses:
        assert res.status_code == 404
        assert res.json()["detail"]["code"] == "share_disabled"
    assert not db.exists()
    assert not db.parent.exists()


def _mock_settings(db: Path, *, share_enabled: bool) -> Settings:
    return Settings(
        mock_mode=True,
        demo_fixture_path=FIXTURE,
        mock_event_interval_seconds=0,
        share_db_path=db,
        share_enabled=share_enabled,
    )


def test_links_made_before_turning_it_off_cannot_be_read(tmp_path: Path) -> None:
    db = tmp_path / "shares.sqlite3"
    with _client(_mock_settings(db, share_enabled=True)) as owner:
        owner.post("/api/session", json={"handle": "demo", "password": PASSWORD})
        owner.post("/api/diagnose")
        token = owner.post("/api/result-link").json()["token"]

    with _client(_mock_settings(db, share_enabled=False)) as viewer:
        res = viewer.post("/api/shared-result", json={"token": token})

    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "share_disabled"


def test_login_is_checked_before_the_feature_switch(tmp_path: Path) -> None:
    settings = _mock_settings(tmp_path / "shares.sqlite3", share_enabled=False)
    with _client(settings) as client:
        client.cookies.set("tkb_session", "not-a-real-session")  # 無効・期限切れの Cookie
        created = client.post("/api/result-link")
        revoked = client.request("DELETE", "/api/result-link", json={"token": "x" * 43})

    assert created.status_code == 401
    assert revoked.status_code == 401


def test_startup_log_says_whether_result_links_are_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tkb_api")
    create_app(_mock_settings(tmp_path / "a.sqlite3", share_enabled=False))
    app = create_app(_mock_settings(tmp_path / "b.sqlite3", share_enabled=True))
    app.state.shares.close()  # lifespan を通していないので、ここで閉じる
    assert "閲覧リンク：オフ（SHARE_ENABLED）" in caplog.text
    assert "閲覧リンク：オン（SHARE_ENABLED）" in caplog.text
