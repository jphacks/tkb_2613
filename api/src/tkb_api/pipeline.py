"""診断の流れ：投稿 → 手がかりの取り出し（detect）→ 推理（engine）→ 危ない投稿（engine.plan）。

ルート（routes/diagnose.py）から使う。SSE の文字列の組み立てはルートの仕事で、ここは
イベント名と data の組を順に返す。
写真は cdn.bsky.app からメモリに取ってくるだけで、ディスクにもログにも残さない。
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from tkb_common.schemas import BSKY_CDN_PREFIX, Clue, Post
from tkb_detect.batch import PostExtraction, extract_posts
from tkb_detect.extract import Extractor
from tkb_engine.gazetteer import Gazetteer, Knowledge
from tkb_engine.planner import Simulation, plan, simulate
from tkb_engine.rules import infer

logger = logging.getLogger(__name__)

BSKY_CDN_HOST = urlparse(BSKY_CDN_PREFIX).hostname
# Bluesky の写真は 1MB 前後。大きすぎるものは読まない
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_FETCH_TIMEOUT_S = 20.0

Event = tuple[str, dict[str, Any]]


class ImageFetchError(Exception):
    """写真を取ってこられなかった。URL などの中身は文言に入れない。"""


async def fetch_images(post: Post) -> list[bytes]:
    """投稿の写真を post.images の順に取ってくる。取りに行くのは cdn.bsky.app だけ。"""
    images = []
    async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT_S, follow_redirects=False) as client:
        for image in post.images:
            parsed = urlparse(image.url)
            if parsed.scheme != "https" or parsed.hostname != BSKY_CDN_HOST:
                raise ImageFetchError("写真の取得先が cdn.bsky.app ではありません")
            images.append(await _download(client, image.url))
    return images


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    try:
        async with client.stream("GET", url) as res:
            res.raise_for_status()
            chunks, size = [], 0
            async for chunk in res.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise ImageFetchError("写真が大きすぎます")
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError as e:
        raise ImageFetchError(type(e).__name__) from e


def load_gazetteer(data_dir: Path) -> Gazetteer:
    """data-prep の表と知識表を読む。読めなければ空の表にして、その表を使うルールだけを飛ばす。

    知識表（指定ゴミ袋・収集地区・大学）はリポジトリにあるので、data-prep の表がなくても使う。
    """
    knowledge = load_knowledge()
    try:
        return Gazetteer.load(data_dir, knowledge=knowledge)
    except (OSError, ValueError, KeyError) as e:
        logger.warning(
            "推理の表を読めませんでした（%s）。最寄り駅のルールは使いません", type(e).__name__
        )
        return Gazetteer(knowledge=knowledge)


def load_knowledge() -> Knowledge:
    try:
        return Knowledge.load()
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(
            "知識表を読めませんでした（%s）。市区町村・収集地区・学校のルールは使いません",
            type(e).__name__,
        )
        return Knowledge()


def demo_extractions(fixture_path: Path, posts: Sequence[Post]) -> list[PostExtraction]:
    """MOCK_MODE 用。デモ用データの手がかりを投稿ごとにまとめる（モデルには接続しない）。"""
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    clues = [Clue.model_validate(c) for c in doc["clues"]]
    return [
        PostExtraction(post_id=p.post_id, clues=[c for c in clues if c.post_id == p.post_id])
        for p in posts
    ]


async def _replay(
    extractions: Sequence[PostExtraction], interval: float
) -> AsyncIterator[PostExtraction]:
    for extraction in extractions:
        await asyncio.sleep(interval)
        yield extraction


def simulation_json(sim: Simulation, clues: Sequence[Clue]) -> dict[str, Any]:
    """消したらどうなるかを、画面に渡す形にする。

    after の clue_indices は、消したあとの手がかりの番号から、clues（診断の全手がかり）での
    番号に直す。画面は conclusions イベントの clues をそのまま使える。
    """
    gone = set(sim.delete)
    kept = [i for i, c in enumerate(clues) if c.post_id not in gone]
    return {
        "delete": sim.delete,
        "broken": sim.broken,
        "after": [
            {**asdict(c), "clue_indices": [kept[i] for i in c.clue_indices]} for c in sim.after
        ],
    }


def plan_json(clues: Sequence[Clue], posts: Sequence[Post], gazetteer: Gazetteer) -> dict[str, Any]:
    """危ない投稿と、それを全部消したときの結果。投稿ごとに、それだけを消したときに崩れる項目も添える。"""
    proposal = plan(clues, posts, gazetteer)
    per_post = [
        {"post_id": post_id, "broken": simulate(clues, posts, gazetteer, [post_id]).broken}
        for post_id in proposal.delete
    ]
    return {**simulation_json(proposal, clues), "posts": per_post}


async def diagnose_events(
    posts: Sequence[Post],
    extractions: AsyncIterator[PostExtraction],
    gazetteer: Gazetteer,
    interval: float = 0,
    on_finished: Callable[[list[Clue]], None] | None = None,
) -> AsyncIterator[Event]:
    """診断のイベントを順に返す。

    post（投稿ごと）→ clues（手がかりの取り出しが終わった順）→ conclusions（推理）
    → plan（危ない投稿）→ done
    conclusions の clue_indices は、同じイベントの clues の並びでの番号。plan の after も同じ番号。
    on_finished は推理まで終わったときに全手がかりで呼ぶ（セッションに置いて simulate に使う）。
    """
    for post in posts:
        yield "post", {"post": post.model_dump(mode="json")}
        await asyncio.sleep(interval)

    all_clues: list[Clue] = []
    async for extraction in extractions:
        all_clues.extend(extraction.clues)
        yield "clues", extraction.model_dump(mode="json")

    conclusions = infer(all_clues, list(posts), gazetteer)
    yield (
        "conclusions",
        {
            "clues": [c.model_dump(mode="json") for c in all_clues],
            "conclusions": [asdict(c) for c in conclusions],
        },
    )
    yield "plan", plan_json(all_clues, posts, gazetteer)
    if on_finished is not None:
        on_finished(all_clues)
    yield "done", {"posts_seen": len(posts)}


def real_extractions(extractor: Extractor, posts: Sequence[Post]) -> AsyncIterator[PostExtraction]:
    return extract_posts(extractor, posts, fetch_images)


def mock_extractions(
    fixture_path: Path, posts: Sequence[Post], interval: float
) -> AsyncIterator[PostExtraction]:
    return _replay(demo_extractions(fixture_path, posts), interval)
