"""投稿をまとめて処理する。診断の SSE から async for でそのまま使う。

    async for result in extract_posts(extractor, posts, fetch_images):
        yield sse("clues", result.model_dump(mode="json"))

- 投稿は CONCURRENCY 件ずつ並列に処理し、終わった順に返す
- 1件が失敗しても止めず、その投稿だけ error に理由を入れて返す（clues は空）
- 画像を取ってくるのは呼び出し側の fetch_images（api が cdn.bsky.app から取る）。
  同時に取ってくるのも CONCURRENCY 件までなので、メモリに載る画像も限られる
- 受け取り側が途中でやめた（SSE が切れた）ら、残りの処理は取り消す
"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence

from pydantic import BaseModel, ConfigDict

from tkb_common.schemas import Clue, Post
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor

# RunPod の vLLM で、1件ずつより速く、待ち時間が延びすぎない並列数
CONCURRENCY = 4
FETCH_FAILED_MESSAGE = "写真を取得できませんでした"
EXTRACT_FAILED_MESSAGE = "手がかりを取り出せませんでした"

FetchImages = Callable[[Post], Awaitable[list[bytes]]]


class PostExtraction(BaseModel):
    """投稿1件の結果。error が None なら成功。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str
    clues: list[Clue]
    # 失敗したときの理由。投稿の本文や写真の中身は入れない
    error: str | None = None


async def extract_posts(
    extractor: Extractor,
    posts: Sequence[Post],
    fetch_images: FetchImages,
    *,
    concurrency: int = CONCURRENCY,
) -> AsyncGenerator[PostExtraction]:
    if concurrency < 1:
        raise ValueError("concurrency は 1 以上にすること")
    semaphore = asyncio.Semaphore(concurrency)

    async def run(post: Post) -> PostExtraction:
        async with semaphore:
            return await _extract_one(extractor, post, fetch_images)

    tasks = [asyncio.create_task(run(post)) for post in posts]
    try:
        for finished in asyncio.as_completed(tasks):
            yield await finished
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _extract_one(
    extractor: Extractor, post: Post, fetch_images: FetchImages
) -> PostExtraction:
    try:
        images = await fetch_images(post) if post.images else []
    except Exception:
        # 取得の失敗の中身（URL など）は返さない
        return PostExtraction(post_id=post.post_id, clues=[], error=FETCH_FAILED_MESSAGE)

    try:
        clues = await extractor.extract_post(post, images)
    except DetectError as e:
        # DetectError の文言には投稿の中身を入れていない
        return PostExtraction(post_id=post.post_id, clues=[], error=str(e))
    except Exception:
        return PostExtraction(post_id=post.post_id, clues=[], error=EXTRACT_FAILED_MESSAGE)
    return PostExtraction(post_id=post.post_id, clues=clues)
