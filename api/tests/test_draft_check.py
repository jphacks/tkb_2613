import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from atproto import AsyncClient
from fastapi.testclient import TestClient
from PIL import Image

from tkb_api.bluesky import LoginResult, PostsFetcher
from tkb_api.config import Settings, get_settings
from tkb_api.main import create_app
from tkb_api.routes import draft_check as draft_check_route
from tkb_api.routes.diagnose import get_extractor_factory, get_fetch_posts
from tkb_api.routes.session import get_login
from tkb_common.schemas import Clue, ClueSource, ClueType, Post, PostImage
from tkb_detect.extract import Extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig

ME = "did:plc:draftchecktest0000000000"
CLIENT = cast(AsyncClient, object())
PASSWORD = "draft-check-test-password"  # noqa: S105
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
DEMO_POST_COUNT = len(json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"])


class RecordingExtractor(Extractor):
    def __init__(self) -> None:
        super().__init__(VlmClient(VlmConfig(base_url="", api_key="", model="")))
        self.seen: list[tuple[str, str, int]] = []

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.seen.append((post.post_id, post.text, len(images)))
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
        if images:
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


def _client(posts: list[Post], extractor: RecordingExtractor | None = None) -> TestClient:
    async def login(handle: str, _password: str) -> LoginResult:
        return LoginResult(handle=handle, did=ME, client=CLIENT)

    async def fetch(client: AsyncClient, did: str, limit: int) -> list[Post]:
        assert client is CLIENT
        assert did == ME
        assert limit == 5
        return posts

    settings = Settings(mock_mode=False, max_posts=5)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_login] = lambda: login
    app.dependency_overrides[get_fetch_posts] = lambda: cast(PostsFetcher, fetch)
    actual_extractor = extractor or RecordingExtractor()
    app.dependency_overrides[get_extractor_factory] = lambda: lambda: actual_extractor
    return TestClient(app)


def _mock_client() -> TestClient:
    settings = Settings(mock_mode=True, demo_fixture_path=FIXTURE)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    async def unexpected_fetch(_client: AsyncClient, _did: str, _limit: int) -> list[Post]:
        pytest.fail("mock mode must not fetch Bluesky posts")

    def unexpected_extractor() -> Extractor:
        pytest.fail("mock mode must not build or call an extractor")

    app.dependency_overrides[get_fetch_posts] = lambda: unexpected_fetch
    app.dependency_overrides[get_extractor_factory] = lambda: unexpected_extractor
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/session", json={"handle": "alice.bsky.social", "password": PASSWORD}
    )
    assert response.status_code == 200


def test_draft_check_requires_session() -> None:
    with _client([_post("at://did:plc:me/app.bsky.feed.post/one", "同じ表記")]) as client:
        response = client.post("/api/draft-check", json={"text": "同じ表記"})
    assert response.status_code == 401


def test_mock_draft_check_matches_fixture_clue_text_without_extractor_or_network() -> None:
    with _mock_client() as client:
        _login(client)
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
    png = BytesIO()
    Image.new("RGB", (1, 1), "white").save(png, format="PNG")
    with _mock_client() as client:
        _login(client)
        response = client.post(
            "/api/draft-check",
            json={
                "text": "",
                "photo_base64": base64.b64encode(png.getvalue()).decode("ascii"),
                "photo_content_type": "image/png",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["mock_mode"] is True
    assert data["overlaps"] == []
    assert any("写真を解析していません" in notice for notice in data["notices"])


def test_draft_check_returns_only_exact_observation_matches_for_own_posts() -> None:
    posts = [
        _post(f"at://{ME}/app.bsky.feed.post/one", "  根津駅  "),
        _post(f"at://{ME}/app.bsky.feed.post/two", "根津駅"),
        _post("at://did:plc:other/app.bsky.feed.post/three", "unrelated"),
    ]
    extractor = RecordingExtractor()
    with _client(posts, extractor) as client:
        _login(client)
        response = client.post("/api/draft-check", json={"text": "根津駅"})

    assert response.status_code == 200
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
    assert all("other" not in post_id for post_id, _, _ in extractor.seen)
    assert extractor.seen[0][0] == "draft:ephemeral"


def test_draft_check_does_not_echo_unmatched_sensitive_draft_text() -> None:
    marker = "PRIVATE-DRAFT-CONTENT-93218"
    with _client([_post("at://did:plc:me/app.bsky.feed.post/one", "別の投稿")]) as client:
        _login(client)
        response = client.post("/api/draft-check", json={"text": marker})
    assert response.status_code == 200
    assert marker not in response.text
    assert response.json()["overlaps"] == []


def test_draft_check_does_not_match_same_value_with_a_different_clue_type() -> None:
    class DifferentTypeExtractor(RecordingExtractor):
        async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
            if post.post_id == "draft:ephemeral":
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
            return await super().extract_post(post, images)

    posts = [_post("at://did:plc:me/app.bsky.feed.post/one", "同じ表記")]
    with _client(posts, DifferentTypeExtractor()) as client:
        _login(client)
        response = client.post("/api/draft-check", json={"text": "同じ表記"})
    assert response.status_code == 200
    assert response.json()["overlaps"] == []


def test_draft_check_matches_photo_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    png = BytesIO()
    Image.new("RGB", (2, 2), "white").save(png, format="PNG")
    photo = png.getvalue()
    extractor = RecordingExtractor()
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

    async def fake_fetch_images(_post: Post) -> list[bytes]:
        return [photo]

    monkeypatch.setattr(draft_check_route, "fetch_images", fake_fetch_images)
    with _client([post], extractor) as client:
        _login(client)
        response = client.post(
            "/api/draft-check",
            json={
                "text": "",
                "photo_base64": base64.b64encode(photo).decode("ascii"),
                "photo_content_type": "image/png",
            },
        )
    assert response.status_code == 200
    assert response.json()["overlaps"][0]["clue"]["type"] == "shop"
    assert ("draft:ephemeral", "", 1) in extractor.seen


def test_draft_check_rejects_mismatched_photo_type_without_echoing_body() -> None:
    png = BytesIO()
    Image.new("RGB", (1, 1), "white").save(png, format="PNG")
    with _client([]) as client:
        _login(client)
        response = client.post(
            "/api/draft-check",
            json={
                "text": "PRIVATE-MARKER",
                "photo_base64": base64.b64encode(png.getvalue()).decode("ascii"),
                "photo_content_type": "image/jpeg",
            },
        )
    assert response.status_code == 415
    assert "PRIVATE-MARKER" not in response.text


def test_draft_check_rejects_malformed_base64_without_echoing_content() -> None:
    marker = "PRIVATE-BASE64-MARKER"
    with _client([]) as client:
        _login(client)
        response = client.post(
            "/api/draft-check",
            json={"text": "", "photo_base64": marker, "photo_content_type": "image/png"},
        )
    assert response.status_code == 422
    assert marker not in response.text


def test_draft_check_enforces_text_limit_without_echoing_content() -> None:
    marker = "PRIVATE-LIMIT-MARKER"
    body = f"{marker}{'x' * 10_000}"
    with _client([]) as client:
        _login(client)
        response = client.post("/api/draft-check", json={"text": body})
    assert response.status_code == 422
    assert marker not in response.text
