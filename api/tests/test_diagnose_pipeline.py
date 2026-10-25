from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tkb_api.pipeline import (
    MAX_IMAGE_BYTES,
    ImageFetchError,
    demo_extractions,
    diagnose_events,
    fetch_images,
    load_gazetteer,
)
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.batch import PostExtraction
from tkb_engine.gazetteer import Gazetteer

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
CDN = "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx"


def _post(n_images: int, text: str = "本文") -> Post:
    return Post.model_validate(
        {
            "post_id": "at://did:plc:xxxx/app.bsky.feed.post/1",
            "text": text,
            "created_at": "2026-10-20T08:31:00+09:00",
            "images": [
                {"index": i, "url": f"{CDN}/{i}@jpeg", "alt": "", "width": 10, "height": 10}
                for i in range(n_images)
            ],
        }
    )


@pytest.mark.anyio
async def test_fetches_images_in_order_from_the_cdn() -> None:
    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").respond(content=b"first")
        router.get(f"{CDN}/1@jpeg").respond(content=b"second")

        assert await fetch_images(_post(2)) == [b"first", b"second"]


@pytest.mark.anyio
async def test_retries_temporary_cdn_failure() -> None:
    calls = 0

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, content=b"image")

    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").mock(side_effect=respond)

        assert await fetch_images(_post(1)) == [b"image"]
    assert calls == 2


@pytest.mark.anyio
async def test_refuses_hosts_other_than_the_cdn() -> None:
    # Post の検証を通り抜けた URL があっても、取りに行く前に止める
    post = _post(1)
    sneaky = post.images[0].model_copy(update={"url": "https://cdn.bsky.app.evil.test/a"})
    post = post.model_copy(update={"images": [sneaky]})

    with respx.mock(assert_all_called=False) as router, pytest.raises(ImageFetchError):
        await fetch_images(post)
    assert router.calls.call_count == 0


@pytest.mark.anyio
async def test_rejects_images_that_are_too_large() -> None:
    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").respond(content=b"x" * (MAX_IMAGE_BYTES + 1))

        with pytest.raises(ImageFetchError):
            await fetch_images(_post(1))


@pytest.mark.anyio
@pytest.mark.parametrize("reply", [httpx.Response(404), httpx.ConnectError("down")])
async def test_reports_download_failures_without_the_url(reply: Any) -> None:
    with respx.mock as router:
        route = router.get(f"{CDN}/0@jpeg")
        if isinstance(reply, Exception):
            route.mock(side_effect=reply)
        else:
            route.mock(return_value=reply)

        with pytest.raises(ImageFetchError) as excinfo:
            await fetch_images(_post(1))

    assert "cdn.bsky.app" not in str(excinfo.value)


def test_missing_tables_give_an_empty_gazetteer_with_the_knowledge(tmp_path: Path) -> None:
    gazetteer = load_gazetteer(tmp_path)

    assert gazetteer.stations == [] and gazetteer.postal == []
    # 知識表はリポジトリにあるので、data-prep の表がなくても読む
    assert gazetteer.knowledge.trash_bags


def test_demo_extractions_group_fixture_clues_by_post() -> None:
    import json

    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts = [Post.model_validate(p) for p in doc["posts"]]

    extractions = demo_extractions(FIXTURE, posts)

    assert [e.post_id for e in extractions] == [p.post_id for p in posts]
    assert sum(len(e.clues) for e in extractions) == len(doc["clues"])
    assert all(c.post_id == e.post_id for e in extractions for c in e.clues)


async def _stream(items: list[PostExtraction]) -> AsyncIterator[PostExtraction]:
    for item in items:
        yield item


@pytest.mark.anyio
async def test_events_keep_failed_posts_and_index_conclusions_into_all_clues() -> None:
    post = _post(0, text="毎週火曜はジム")
    clue = Clue(
        post_id=post.post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value="毎週火曜はジム",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    extractions = [
        PostExtraction(post_id="at://other", clues=[], error="写真を取得できませんでした"),
        PostExtraction(post_id=post.post_id, clues=[clue]),
    ]

    events = [e async for e in diagnose_events([post], _stream(extractions), Gazetteer())]

    assert [name for name, _ in events] == ["post", "clues", "clues", "conclusions", "plan", "done"]
    assert events[1][1]["error"] == "写真を取得できませんでした"
    result = events[3][1]
    assert result["clues"] == [clue.model_dump(mode="json")]
    routine = next(c for c in result["conclusions"] if c["attribute"] == "routine")
    assert routine["clue_indices"] == [0]
    assert set(routine) == {"rule", "attribute", "value", "clue_indices", "note"}


@pytest.mark.anyio
async def test_events_log_timings_without_post_contents(caplog: pytest.LogCaptureFixture) -> None:
    post = _post(2, text="毎週火曜はジム")
    clue = Clue(
        post_id=post.post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value="毎週火曜はジム",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    ticks = iter([10.0, 13.5, 13.5, 13.75])

    with caplog.at_level("INFO", logger="tkb_api"):
        events = [
            e
            async for e in diagnose_events(
                [post],
                _stream([PostExtraction(post_id=post.post_id, clues=[clue])]),
                Gazetteer(),
                clock=lambda: next(ticks),
            )
        ]

    assert events[-1][0] == "done"
    messages = [r.getMessage() for r in caplog.records]
    assert messages == [
        "診断 1/1 件目：3.5 秒（写真 2 枚、手がかり 1 件）",
        "診断の時間：手がかりの取り出し 3.5 秒（投稿 1 件、写真 2 枚、手がかり 1 件、失敗 0 件）"
        "、推理と危ない投稿 0.25 秒",
    ]
    # 投稿の ID・本文・手がかりの中身はログに出さない
    assert not any(post.post_id in m or "ジム" in m for m in messages)
