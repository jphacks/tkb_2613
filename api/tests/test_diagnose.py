import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
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


def test_mock_diagnose_streams_each_demo_post_then_done(client: TestClient) -> None:
    _login(client)

    res = client.post("/api/diagnose")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    posts = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]
    assert _events(res.text) == [
        *(("post", {"post": post}) for post in posts),
        ("done", {"posts_seen": len(posts)}),
    ]


def test_diagnose_without_mock_is_not_implemented_yet() -> None:
    settings = Settings(mock_mode=False, demo_fixture_path=FIXTURE)
    with _client(settings) as client:
        # 本物のログインを避けるため、モックでログインしてから設定だけ本番扱いにする
        client.app.dependency_overrides[get_settings] = lambda: Settings(mock_mode=True)  # type: ignore[attr-defined]
        _login(client)
        client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]

        assert client.post("/api/diagnose").status_code == 501


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
