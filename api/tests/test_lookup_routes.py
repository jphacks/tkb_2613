import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tkb_api.bluesky import Diagnosis, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes.diagnose import get_gazetteer
from tkb_api.routes.lookup import get_http_client, get_resolver
from tkb_api.routes.session import SESSION_COOKIE
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine.gazetteer import Gazetteer

PASSWORD = "correct horse battery staple"  # noqa: S105  テスト用の架空の値
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "eval" / "fixtures" / "demo_observations.json"
LOOKUP_FIXTURE = ROOT / "eval" / "fixtures" / "demo_web_lookup.json"
SEARXNG = "http://searxng.test"
POST_ID = "at://did:plc:mockdemoaccount/app.bsky.feed.post/1"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "mock_mode": True,
        "web_lookup_enabled": True,
        "demo_fixture_path": FIXTURE,
        "demo_lookup_path": LOOKUP_FIXTURE,
        "mock_event_interval_seconds": 0,
        "search_base_url": SEARXNG,
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_gazetteer] = lambda: Gazetteer()

    async def resolve(host: str) -> list[str]:
        return ["93.184.215.14"]

    async def http_client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient() as client:
            yield client

    app.dependency_overrides[get_resolver] = lambda: resolve
    app.dependency_overrides[get_http_client] = http_client
    return TestClient(app)


def _login(client: TestClient) -> str:
    res = client.post("/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD})
    assert res.status_code == 200
    return str(client.cookies[SESSION_COOKIE])


def _store(client: TestClient) -> SessionStore:
    store: SessionStore = client.app.state.sessions  # type: ignore[attr-defined]
    return store


def _clue(type_: ClueType, value: str) -> Clue:
    return Clue(
        post_id=POST_ID,
        image_index=None,
        type=type_,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def _diagnosis_with_name() -> Diagnosis:
    post = Post.model_validate(
        {"post_id": POST_ID, "text": "", "created_at": "2026-10-17T21:00:00+09:00", "images": []}
    )
    return Diagnosis(
        posts=(post,),
        clues=(
            _clue(ClueType.NAME_TEXT, "山田 はるき 様"),
            _clue(ClueType.AGE_TEXT, "25歳になりました"),
            _clue(ClueType.ORG_TEXT, "架空大学"),
        ),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(_settings()) as c:
        yield c


def test_lookup_is_off_by_default() -> None:
    with _client(_settings(web_lookup_enabled=False)) as c:
        _login(c)
        assert c.post("/api/lookup").status_code == 404
        assert c.post("/api/lookup/photo").status_code == 404


def test_lookup_requires_login(client: TestClient) -> None:
    assert client.post("/api/lookup").status_code == 401


def test_lookup_requires_a_diagnosis(client: TestClient) -> None:
    _login(client)

    assert client.post("/api/lookup").status_code == 409


def test_lookup_takes_no_name_from_the_client(client: TestClient) -> None:
    _login(client)
    client.post("/api/diagnose")

    res = client.post("/api/lookup", json={"full_name": "誰か 別人"})

    assert res.status_code == 200
    assert "別人" not in res.text


def test_mock_lookup_returns_the_fictional_result_then_a_silhouette(client: TestClient) -> None:
    _login(client)
    assert client.post("/api/lookup/photo").status_code == 409
    client.post("/api/diagnose")

    body = client.post("/api/lookup").json()
    photo = client.post("/api/lookup/photo")

    expected = json.loads(LOOKUP_FIXTURE.read_text(encoding="utf-8"))
    assert body["found"] is True
    assert body["url"] == expected["url"]
    assert body["matched"] == ["school", "age"]
    assert photo.status_code == 200
    assert photo.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in photo.headers["content-security-policy"]


def test_a_new_diagnosis_drops_the_lookup(client: TestClient) -> None:
    _login(client)
    client.post("/api/diagnose")
    client.post("/api/lookup")
    client.post("/api/diagnose")

    assert client.post("/api/lookup/photo").status_code == 409


@respx.mock
def test_real_lookup_searches_with_the_inferred_name_and_fetches_the_photo() -> None:
    respx.get(f"{SEARXNG}/search").respond(
        json={
            "results": [
                {
                    "url": "https://example.com/u",
                    "title": "山田 はるき - 架空大学",
                    "content": "25歳",
                }
            ]
        }
    )
    respx.get("https://example.com/u").respond(
        html='<html><head><title>山田 はるき</title><meta property="og:image" '
        'content="https://example.com/face.jpg"></head></html>'
    )
    respx.get("https://example.com/face.jpg").respond(
        content=b"jpeg", headers={"content-type": "image/jpeg"}
    )
    settings = _settings(mock_mode=False, vlm_base_url="http://vllm.test/v1")

    with _client(settings) as c:
        _store(c).set_diagnosis(_login_real(c), _diagnosis_with_name())
        body = c.post("/api/lookup").json()
        photo = c.post("/api/lookup/photo")

    assert body["found"] is True
    assert body["query"] == '"山田はるき" 架空大学'
    assert body["matched"] == ["school", "age"]
    assert photo.content == b"jpeg"
    assert respx.calls.call_count == 3


def test_real_lookup_needs_a_full_name() -> None:
    settings = _settings(mock_mode=False, vlm_base_url="http://vllm.test/v1")
    with _client(settings) as c:
        diagnosis = Diagnosis(
            posts=_diagnosis_with_name().posts, clues=(_clue(ClueType.NAME_TEXT, "はるき"),)
        )
        _store(c).set_diagnosis(_login_real(c), diagnosis)

        assert c.post("/api/lookup").status_code == 409


def _login_real(client: TestClient) -> str:
    """本番モードのログインは Bluesky に行くので、セッションを直接作って Cookie に入れる。"""
    session_id = _store(client).create(
        LoginResult(handle="alice.bsky.social", did="did:plc:a", client=None)
    )
    client.cookies.set(SESSION_COOKIE, session_id)
    return session_id
