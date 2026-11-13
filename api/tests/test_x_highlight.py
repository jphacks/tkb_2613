"""集計しない表示（X_INFO_VIEW=highlight）。地名・駅名の位置だけを返し、値ごとに数えない。"""

from pathlib import Path
from typing import Any

import httpx
import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.x_public_info import post_highlights
from tkb_common.schemas import Post

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


def _post(text: str) -> Post:
    return Post.model_validate(
        {"post_id": "x:1", "text": text, "created_at": "2026-11-10T00:00:00Z", "images": []}
    )


def test_default_view_is_the_current_aggregate() -> None:
    assert Settings(_env_file=None).x_info_view == "aggregate"


def test_highlights_are_code_point_ranges_of_places_and_stations_only() -> None:
    text = "🍜 渋谷駅 日曜10時、東京都渋谷区、青空大学へ"
    found = post_highlights(_post(text))
    # 絵文字は1文字として数える。曜日・時刻・学校名は色を付けない
    assert [(h.category, text[h.start : h.end]) for h in found] == [
        ("station", "渋谷駅"),
        ("place", "東京都渋谷区"),
    ]
    assert found[0].start == 2


def _client(**settings: Any) -> httpx.AsyncClient:
    app = create_app(
        settings=Settings(
            _env_file=None,
            x_public_origin=ORIGIN,
            x_callback_url=f"{ORIGIN}/api/x/callback",
            gazetteer_dir=Path("/missing-x-gazetteer"),
            share_enabled=False,
            x_mock_mode=True,
            **settings,
        )
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


@pytest.mark.anyio
async def test_highlight_view_returns_positions_without_counting() -> None:
    async with _client(x_info_view="highlight") as client:
        assert (await client.get("/api/x/config")).json()["info_view"] == "highlight"
        await client.post("/api/x/mock/session", json={"consent": True}, headers=HEADERS)
        snapshot = (await client.post("/api/x/diagnose", headers=HEADERS)).json()

        assert snapshot["view"] == "highlight"
        assert snapshot["information"] == []  # 値ごとの集計は作らない
        assert "count" not in str(snapshot["highlights"])
        texts = {post["post_id"]: post["text"] for post in snapshot["posts"]}
        marked = {
            (post_id, texts[post_id][h["start"] : h["end"]])
            for post_id, items in snapshot["highlights"].items()
            for h in items
        }
        assert ("x:9001", "渋谷駅") in marked
        assert ("x:9002", "東京都渋谷区") in marked
        assert set(snapshot["highlights"]) == set(texts)

        compare = await client.post("/api/x/simulate", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert compare.status_code == 409  # 件数の比較は作らない
        rest = await client.post("/api/x/rediagnose", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert rest.status_code == 200
        assert rest.json()["view"] == "highlight"
        assert rest.json()["information"] == []
        assert set(rest.json()["highlights"]) == {"x:9002", "x:9003"}


@pytest.mark.anyio
async def test_aggregate_view_is_unchanged() -> None:
    async with _client() as client:
        assert (await client.get("/api/x/config")).json()["info_view"] == "aggregate"
        await client.post("/api/x/mock/session", json={"consent": True}, headers=HEADERS)
        snapshot = (await client.post("/api/x/diagnose", headers=HEADERS)).json()
        assert snapshot["view"] == "aggregate"
        assert "highlights" not in snapshot
        assert any(item["count"] == 2 for item in snapshot["information"])
        compare = await client.post("/api/x/simulate", json={"delete": ["x:9001"]}, headers=HEADERS)
        assert compare.status_code == 200


def test_unknown_view_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, x_info_view="count-everything")
