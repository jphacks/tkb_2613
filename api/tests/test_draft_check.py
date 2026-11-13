import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from atproto import AsyncClient
from fastapi.testclient import TestClient
from PIL import Image

from tkb_api.bluesky import Diagnosis, LoginResult, SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.limits import JST, DiagnoseLimiter, PublicWindow
from tkb_api.main import create_app
from tkb_api.routes import draft_check as draft_check_route
from tkb_api.routes.diagnose import get_clock, get_extractor_factory
from tkb_api.routes.session import SESSION_COOKIE, get_login
from tkb_common.schemas import Clue, ClueSource, ClueType, Post, PostImage
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig

ME = "did:plc:draftchecktest0000000000"
CLIENT = cast(AsyncClient, object())
PASSWORD = "draft-check-test-password"  # noqa: S105
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DEMO_POSTS = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]
DEMO_POST_COUNT = len(DEMO_POSTS)
DRAFT = "draft:ephemeral"


class RecordingExtractor(Extractor):
    def __init__(self) -> None:
        super().__init__(VlmClient(VlmConfig(base_url="", api_key="", model="")))
        self.seen: list[tuple[str, str, int]] = []

    async def model_reachable(self, timeout_s: float) -> bool:
        return True

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.seen.append((post.post_id, post.text, len(images)))
        return _clues_for(post, has_images=bool(images))


class UnreachableExtractor(RecordingExtractor):
    async def model_reachable(self, timeout_s: float) -> bool:
        return False


def _clues_for(post: Post, *, has_images: bool) -> list[Clue]:
    """本文があれば本文そのものを地名の手がかりに、写真だけなら店の手がかりにする。"""
    if post.text.strip():
        return [
            Clue(
                post_id=post.post_id,
                image_index=None,
                type=ClueType.PLACE_TEXT,
                value=post.text,
                region=None,
                confidence=0.8,
                source=ClueSource.TEXT,
            )
        ]
    if has_images:
        return [
            Clue(
                post_id=post.post_id,
                image_index=0,
                type=ClueType.SHOP,
                value="喫茶青",
                region=None,
                confidence=0.7,
                source=ClueSource.VLM,
            )
        ]
    return []


def _post(post_id: str, text: str) -> Post:
    return Post(
        post_id=post_id,
        text=text,
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        images=[],
    )


def _png(size: int = 1) -> bytes:
    png = BytesIO()
    Image.new("RGB", (size, size), "white").save(png, format="PNG")
    return png.getvalue()


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD}
    )
    assert response.status_code == 200


def _store(client: TestClient) -> SessionStore:
    store: SessionStore = client.app.state.sessions  # type: ignore[attr-defined]
    return store


def _limiter(client: TestClient) -> DiagnoseLimiter:
    limiter: DiagnoseLimiter = client.app.state.diagnose_limiter  # type: ignore[attr-defined]
    return limiter


def _diagnosed(client: TestClient, posts: list[Post], deleted: tuple[str, ...] = ()) -> None:
    """posts を診断済み（手がかりを読んだ）の状態にする。モデルは呼ばない。"""
    clues = [clue for post in posts for clue in _clues_for(post, has_images=bool(post.images))]
    _store(client).set_diagnosis(
        client.cookies[SESSION_COOKIE],
        Diagnosis(posts=tuple(posts), clues=tuple(clues), deleted=deleted),
    )


@contextmanager
def _client(
    posts: list[Post] | None = None,
    extractor: RecordingExtractor | None = None,
    settings: Settings | None = None,
) -> Iterator[tuple[TestClient, RecordingExtractor]]:
    """本番モードでログインした状態。posts を渡せば、それを診断済みにしておく。"""

    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=ME, client=CLIENT)

    actual_settings = settings or Settings(mock_mode=False, max_posts=5)
    actual_extractor = extractor or RecordingExtractor()
    app = create_app(actual_settings)
    app.dependency_overrides[get_settings] = lambda: actual_settings
    app.dependency_overrides[get_login] = lambda: login
    app.dependency_overrides[get_extractor_factory] = lambda: lambda: actual_extractor
    with TestClient(app) as client:
        _login(client)
        if posts is not None:
            _diagnosed(client, posts)
        yield client, actual_extractor


@contextmanager
def _mock_client(*, diagnosed: bool = True) -> Iterator[TestClient]:
    settings = Settings(mock_mode=True, demo_fixture_path=FIXTURE)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    def unexpected_extractor() -> Extractor:
        pytest.fail("mock mode must not build or call an extractor")

    app.dependency_overrides[get_extractor_factory] = lambda: unexpected_extractor
    with TestClient(app) as client:
        _login(client)
        if diagnosed:
            posts = [Post.model_validate(p) for p in DEMO_POSTS]
            _store(client).set_diagnosis(
                client.cookies[SESSION_COOKIE], Diagnosis(posts=tuple(posts), clues=())
            )
        yield client


def _photo_body(photo: bytes, text: str = "", content_type: str = "image/png") -> dict[str, Any]:
    return {
        "text": text,
        "photo_base64": base64.b64encode(photo).decode("ascii"),
        "photo_content_type": content_type,
    }


# --- 認証・診断済みであること ---


def test_draft_check_requires_session() -> None:
    settings = Settings(mock_mode=False)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        response = client.post("/api/draft-check", json={"text": "同じ表記"})
    assert response.status_code == 401


def test_draft_check_before_diagnosis_returns_409_without_calling_the_model() -> None:
    with _client() as (client, extractor):
        response = client.post("/api/draft-check", json={"text": "根津駅"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "diagnosis_required"
    assert extractor.seen == []


def test_mock_draft_check_before_diagnosis_returns_409() -> None:
    with _mock_client(diagnosed=False) as client:
        response = client.post("/api/draft-check", json={"text": "夜勤明け"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "diagnosis_required"


# --- モック ---


def test_mock_draft_check_matches_fixture_clue_text_without_extractor_or_network() -> None:
    with _mock_client() as client:
        response = client.post("/api/draft-check", json={"text": "今日は夜勤明けに投稿した"})
    assert response.status_code == 200
    data = response.json()
    assert data["mock_mode"] is True
    assert data["posts_checked"] == DEMO_POST_COUNT
    assert any(overlap["clue"]["value"] == "夜勤明け" for overlap in data["overlaps"])
    match = next(overlap for overlap in data["overlaps"] if overlap["clue"]["value"] == "夜勤明け")
    assert len(match["evidence"]) == 2
    assert any(
        "架空投稿" in notice
        and "文字列どうしの部分一致" in notice
        and "意味は判定しません" in notice
        for notice in data["notices"]
    )


def test_mock_draft_check_discloses_that_photo_is_not_analyzed() -> None:
    with _mock_client() as client:
        response = client.post("/api/draft-check", json=_photo_body(_png()))
    assert response.status_code == 200
    data = response.json()
    assert data["mock_mode"] is True
    assert data["overlaps"] == []
    assert any("写真を解析していません" in notice for notice in data["notices"])


# --- 本番モード：照合 ---


def test_draft_check_calls_the_model_only_for_the_draft() -> None:
    posts = [
        _post(f"at://{ME}/app.bsky.feed.post/one", "  根津駅  "),
        _post(f"at://{ME}/app.bsky.feed.post/two", "根津駅"),
        _post("at://did:plc:other/app.bsky.feed.post/three", "unrelated"),
    ]
    with _client(posts) as (client, extractor):
        response = client.post("/api/draft-check", json={"text": "根津駅"})

    assert response.status_code == 200
    # 過去の投稿は診断で読んだ手がかりを使う。モデルに読ませるのは下書きの1件だけ
    assert extractor.seen == [(DRAFT, "根津駅", 0)]
    data = response.json()
    assert data["posts_checked"] == 2
    assert data["mock_mode"] is False
    assert data["notices"] == []
    assert len(data["overlaps"]) == 1
    assert data["overlaps"][0]["clue"]["value"] == "根津駅"
    assert {item["post_id"] for item in data["overlaps"][0]["evidence"]} == {
        f"at://{ME}/app.bsky.feed.post/one",
        f"at://{ME}/app.bsky.feed.post/two",
    }


def test_draft_check_ignores_posts_deleted_after_the_diagnosis() -> None:
    one = _post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")
    two = _post(f"at://{ME}/app.bsky.feed.post/two", "根津駅")
    with _client() as (client, _extractor):
        _diagnosed(client, [one, two], deleted=(one.post_id,))
        response = client.post("/api/draft-check", json={"text": "根津駅"})

    assert response.status_code == 200
    data = response.json()
    assert data["posts_checked"] == 1
    assert [item["post_id"] for item in data["overlaps"][0]["evidence"]] == [two.post_id]


def test_draft_check_does_not_echo_unmatched_sensitive_draft_text() -> None:
    marker = "PRIVATE-DRAFT-CONTENT-93218"
    with _client([_post(f"at://{ME}/app.bsky.feed.post/one", "別の投稿")]) as (client, _):
        response = client.post("/api/draft-check", json={"text": marker})
    assert response.status_code == 200
    assert marker not in response.text
    assert response.json()["overlaps"] == []


def test_draft_check_does_not_match_same_value_with_a_different_clue_type() -> None:
    class DifferentTypeExtractor(RecordingExtractor):
        async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
            self.seen.append((post.post_id, post.text, len(images)))
            return [
                Clue(
                    post_id=post.post_id,
                    image_index=None,
                    type=ClueType.ORG_TEXT,
                    value="同じ表記",
                    region=None,
                    confidence=0.8,
                    source=ClueSource.TEXT,
                )
            ]

    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "同じ表記")]
    with _client(posts, DifferentTypeExtractor()) as (client, _):
        response = client.post("/api/draft-check", json={"text": "同じ表記"})
    assert response.status_code == 200
    assert response.json()["overlaps"] == []


def test_draft_check_matches_photo_without_text() -> None:
    photo = _png(2)
    post = Post(
        post_id=f"at://{ME}/app.bsky.feed.post/one",
        text="",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
        images=[
            PostImage(
                index=0,
                url="https://cdn.bsky.app/img/feed_fullsize/existing",
                alt="",
                width=2,
                height=2,
            )
        ],
    )
    with _client([post]) as (client, extractor):
        response = client.post("/api/draft-check", json=_photo_body(photo))
    assert response.status_code == 200
    assert response.json()["overlaps"][0]["clue"]["type"] == "shop"
    assert extractor.seen == [(DRAFT, "", 1)]


# --- 本番モード：歯止め ---


def test_draft_check_returns_503_when_the_slots_are_full_and_does_not_count() -> None:
    settings = Settings(mock_mode=False, max_concurrent_diagnoses=1, diagnose_daily_limit=1)
    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")]
    with _client(posts, settings=settings) as (client, extractor):
        other = _limiter(client).acquire("someone-else", "did:plc:other")
        busy = client.post("/api/draft-check", json={"text": "根津駅"})
        assert busy.status_code == 503
        assert busy.json()["detail"]["code"] == "busy"
        assert extractor.seen == []

        other.release()
        assert client.post("/api/draft-check", json={"text": "根津駅"}).status_code == 200
        # 枠は返し、1日の回数には数えない
        assert _limiter(client).active == 0
        assert _limiter(client).used_today(ME) == 0


def test_draft_check_is_allowed_after_the_daily_diagnosis_limit() -> None:
    settings = Settings(mock_mode=False, diagnose_daily_limit=1)
    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")]
    with _client(posts, settings=settings) as (client, _):
        lease = _limiter(client).acquire("earlier", ME)
        lease.count()
        lease.release()
        assert client.post("/api/draft-check", json={"text": "根津駅"}).status_code == 200


def test_draft_check_in_the_same_session_as_a_running_diagnosis_returns_409() -> None:
    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")]
    with _client(posts) as (client, extractor):
        running = _limiter(client).acquire(client.cookies[SESSION_COOKIE], ME)
        response = client.post("/api/draft-check", json={"text": "根津駅"})
        running.release()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_running"
    assert extractor.seen == []


def test_draft_check_returns_503_when_the_model_is_unreachable() -> None:
    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")]
    with _client(posts, UnreachableExtractor()) as (client, extractor):
        response = client.post("/api/draft-check", json={"text": "根津駅"})
        assert _limiter(client).active == 0
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "model_unavailable"
    assert extractor.seen == []


def test_draft_check_outside_the_public_hours_returns_503() -> None:
    window = PublicWindow(
        start=datetime(2026, 11, 15, 10, tzinfo=JST), end=datetime(2026, 11, 15, 18, tzinfo=JST)
    )
    settings = Settings(mock_mode=False, public_windows=[window])
    posts = [_post(f"at://{ME}/app.bsky.feed.post/one", "根津駅")]
    after = datetime(2026, 11, 15, 20, tzinfo=JST)
    with _client(posts, settings=settings) as (client, extractor):
        client.app.dependency_overrides[get_clock] = lambda: lambda: after  # type: ignore[attr-defined]
        response = client.post("/api/draft-check", json={"text": "根津駅"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "closed"
    assert extractor.seen == []


def test_photo_is_validated_outside_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    async def fake_to_thread(func: Any, *args: Any) -> Any:
        called.append(func)
        return func(*args)

    monkeypatch.setattr("tkb_api.routes.draft_check.asyncio.to_thread", fake_to_thread)
    with _client([]) as (client, _):
        response = client.post("/api/draft-check", json=_photo_body(_png()))
    assert response.status_code == 200
    assert draft_check_route._validate_photo in called


def test_request_limit_fits_a_20mib_photo_in_base64() -> None:
    encoded = 4 * -(-draft_check_route.MAX_IMAGE_BYTES // 3)
    assert encoded < draft_check_route.MAX_REQUEST_BYTES < 29 * 1024 * 1024


# --- 入力の検証（本文を応答に出さない） ---


def test_draft_check_rejects_mismatched_photo_type_without_echoing_body() -> None:
    with _client([]) as (client, _):
        response = client.post(
            "/api/draft-check",
            json=_photo_body(_png(), text="PRIVATE-MARKER", content_type="image/jpeg"),
        )
    assert response.status_code == 415
    assert "PRIVATE-MARKER" not in response.text


def test_draft_check_rejects_malformed_base64_without_echoing_content() -> None:
    marker = "PRIVATE-BASE64-MARKER"
    with _client([]) as (client, _):
        response = client.post(
            "/api/draft-check",
            json={"text": "", "photo_base64": marker, "photo_content_type": "image/png"},
        )
    assert response.status_code == 422
    assert marker not in response.text


def test_draft_check_enforces_text_limit_without_echoing_content() -> None:
    marker = "PRIVATE-LIMIT-MARKER"
    body = f"{marker}{'x' * 10_000}"
    with _client([]) as (client, _):
        response = client.post("/api/draft-check", json={"text": body})
    assert response.status_code == 422
    assert marker not in response.text
