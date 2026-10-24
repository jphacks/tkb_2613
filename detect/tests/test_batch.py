import asyncio
from collections.abc import Awaitable, Callable

import pytest

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.batch import (
    CONCURRENCY,
    EXTRACT_FAILED_MESSAGE,
    FETCH_FAILED_MESSAGE,
    PostExtraction,
    extract_posts,
)
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor, build_extractor
from tkb_detect.vlm_client import VlmClient, VlmConfig


def _post(n: int, n_images: int = 0) -> Post:
    return Post.model_validate(
        {
            "post_id": f"at://did:plc:xxxx/app.bsky.feed.post/{n}",
            "text": f"投稿{n}",
            "created_at": "2026-10-20T08:31:00+09:00",
            "images": [
                {
                    "index": i,
                    "url": f"https://cdn.bsky.app/img/{n}/{i}",
                    "alt": "",
                    "width": 10,
                    "height": 10,
                }
                for i in range(n_images)
            ],
        }
    )


def _clue(post: Post) -> Clue:
    return Clue(
        post_id=post.post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value=post.text,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


class FakeExtractor(Extractor):
    """投稿ごとに待ち時間や失敗を変えられる偽物。同時に動いた件数も数える。"""

    def __init__(
        self,
        delays: dict[str, float] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        super().__init__(VlmClient(VlmConfig(base_url="", api_key="", model="")))
        self.delays = delays or {}
        self.errors = errors or {}
        self.running = 0
        self.max_running = 0
        self.started: list[str] = []
        self.cancelled: list[str] = []
        self.received_images: dict[str, list[bytes]] = {}

    async def extract_post(self, post: Post, images: list[bytes]) -> list[Clue]:
        self.started.append(post.post_id)
        self.received_images[post.post_id] = images
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(self.delays.get(post.post_id, 0.01))
            if post.post_id in self.errors:
                raise self.errors[post.post_id]
            return [_clue(post)]
        except asyncio.CancelledError:
            self.cancelled.append(post.post_id)
            raise
        finally:
            self.running -= 1


async def _no_images(_post: Post) -> list[bytes]:
    return []


def _fetch_by_index() -> Callable[[Post], Awaitable[list[bytes]]]:
    async def fetch(post: Post) -> list[bytes]:
        return [f"{post.post_id}#{img.index}".encode() for img in post.images]

    return fetch


async def _collect(
    extractor: Extractor,
    posts: list[Post],
    fetch: Callable[[Post], Awaitable[list[bytes]]] = _no_images,
    concurrency: int = CONCURRENCY,
) -> list[PostExtraction]:
    stream = extract_posts(extractor, posts, fetch, concurrency=concurrency)
    return [r async for r in stream]


@pytest.mark.anyio
async def test_returns_one_result_per_post_with_clues() -> None:
    posts = [_post(n) for n in range(6)]

    results = await _collect(FakeExtractor(), posts)

    assert sorted(r.post_id for r in results) == sorted(p.post_id for p in posts)
    assert all(r.error is None and len(r.clues) == 1 for r in results)


@pytest.mark.anyio
async def test_runs_at_most_four_posts_at_once() -> None:
    extractor = FakeExtractor()

    await _collect(extractor, [_post(n) for n in range(12)])

    assert CONCURRENCY == 4
    assert extractor.max_running == 4


@pytest.mark.anyio
async def test_yields_results_in_the_order_they_finish() -> None:
    slow, fast = _post(0), _post(1)
    extractor = FakeExtractor(delays={slow.post_id: 0.2, fast.post_id: 0.01})

    results = await _collect(extractor, [slow, fast])

    assert [r.post_id for r in results] == [fast.post_id, slow.post_id]


@pytest.mark.anyio
async def test_one_failure_does_not_stop_the_others() -> None:
    posts = [_post(n) for n in range(4)]
    extractor = FakeExtractor(
        errors={
            posts[1].post_id: DetectError("VLM に接続できませんでした: ReadTimeout"),
            posts[2].post_id: RuntimeError("本文：秘密の内容"),
        }
    )

    results = {r.post_id: r for r in await _collect(extractor, posts)}

    assert results[posts[0].post_id].error is None
    assert results[posts[1].post_id].error == "VLM に接続できませんでした: ReadTimeout"
    # DetectError 以外は、中身を出さず決まった文言にする
    assert results[posts[2].post_id].error == EXTRACT_FAILED_MESSAGE
    assert results[posts[3].post_id].error is None
    assert results[posts[1].post_id].clues == []


@pytest.mark.anyio
async def test_fetch_failure_is_reported_for_that_post_only() -> None:
    ok, broken = _post(0, n_images=1), _post(1, n_images=1)

    async def fetch(post: Post) -> list[bytes]:
        if post.post_id == broken.post_id:
            raise OSError("https://cdn.bsky.app/img/1/0 に接続できません")
        return [b"img"]

    results = {r.post_id: r for r in await _collect(FakeExtractor(), [ok, broken], fetch)}

    assert results[ok.post_id].error is None
    assert results[broken.post_id].error == FETCH_FAILED_MESSAGE


@pytest.mark.anyio
async def test_passes_fetched_images_and_skips_fetch_without_images() -> None:
    with_images, text_only = _post(0, n_images=2), _post(1)
    calls: list[str] = []
    fetch = _fetch_by_index()

    async def counting_fetch(post: Post) -> list[bytes]:
        calls.append(post.post_id)
        return await fetch(post)

    extractor = FakeExtractor()
    await _collect(extractor, [with_images, text_only], counting_fetch)

    assert calls == [with_images.post_id]
    assert extractor.received_images[with_images.post_id] == [
        f"{with_images.post_id}#0".encode(),
        f"{with_images.post_id}#1".encode(),
    ]
    assert extractor.received_images[text_only.post_id] == []


@pytest.mark.anyio
async def test_stopping_early_cancels_the_remaining_work() -> None:
    posts = [_post(n) for n in range(8)]
    extractor = FakeExtractor(delays={p.post_id: 0.5 for p in posts[1:]})
    stream = extract_posts(extractor, posts, _no_images)

    first = await anext(stream)
    await stream.aclose()  # SSE が切れたとき

    assert first.post_id == posts[0].post_id
    assert extractor.running == 0
    # 始まっていたもののうち、終わった1件以外はすべて取り消される
    assert set(extractor.cancelled) == set(extractor.started) - {first.post_id}
    # 1件目が終わって空いた枠の分（5件目）までしか始まらない
    assert len(extractor.started) <= CONCURRENCY + 1 < len(posts)


@pytest.mark.anyio
async def test_empty_post_list_yields_nothing() -> None:
    assert await _collect(FakeExtractor(), []) == []


@pytest.mark.anyio
async def test_rejects_concurrency_below_one() -> None:
    with pytest.raises(ValueError):
        await _collect(FakeExtractor(), [_post(0)], concurrency=0)


def test_result_serializes_to_json_for_sse() -> None:
    post = _post(0)
    result = PostExtraction(post_id=post.post_id, clues=[_clue(post)])

    assert result.model_dump(mode="json") == {
        "post_id": post.post_id,
        "clues": [
            {
                "post_id": post.post_id,
                "image_index": None,
                "type": "routine_text",
                "value": "投稿0",
                "region": None,
                "confidence": 0.9,
                "source": "text",
            }
        ],
        "error": None,
    }


@pytest.mark.anyio
async def test_works_with_the_real_extractor_in_mock_mode() -> None:
    extractor = build_extractor(
        mock_mode=True, vlm_base_url="", vlm_api_key="", vlm_model="", ocr_base_url=""
    )

    results = await _collect(extractor, [_post(0), _post(1)])

    assert [r.error for r in results] == [None, None]
