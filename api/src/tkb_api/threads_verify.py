"""Threads 画像診断の実機検証用ヘルパー。件数だけを出す。

実行: THREADS_ACCESS_TOKEN を環境変数に設定して
    uv run python -m tkb_api.threads_verify --limit 3 --mode both

- --mode text  画像なし（THREADS_IMAGE_DIAGNOSIS=0 相当）
- --mode image 画像あり（THREADS_IMAGE_DIAGNOSIS=1 相当）
- --mode both  同じ投稿を text → image の順に処理して並べる（既定。比較用）
投稿は1回だけ取得し、text は画像を外したコピーで処理するので、差は画像の有無だけになる。

標準出力は件数だけ。投稿本文・画像・画像URL・トークン・手がかりの値・投稿IDは出さない。
失敗の理由も例外の型名までで、メッセージは出さない。
"""

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from tkb_api.config import get_settings
from tkb_api.threads_poc import ThreadsPocError, fetch_own_posts, fetch_threads_images
from tkb_common.schemas import Post
from tkb_detect.batch import PostExtraction, extract_posts
from tkb_detect.extract import build_extractor

DEFAULT_LIMIT = 3
MAX_LIMIT = 10
MODES = ("text", "image", "both")


@dataclass(frozen=True)
class Counts:
    posts: int
    posts_with_image: int
    clues: int
    image_clues: int
    text_clues: int
    failed_posts: int


def summarize(posts: Sequence[Post], extractions: Sequence[PostExtraction]) -> Counts:
    """画像由来の手がかり = image_index を持つもの（source が ocr / vlm）。"""
    clues = [clue for extraction in extractions for clue in extraction.clues]
    image_clues = sum(clue.image_index is not None for clue in clues)
    return Counts(
        posts=len(posts),
        posts_with_image=sum(bool(post.images) for post in posts),
        clues=len(clues),
        image_clues=image_clues,
        text_clues=len(clues) - image_clues,
        failed_posts=sum(extraction.error is not None for extraction in extractions),
    )


def format_counts(label: str, counts: Counts) -> str:
    return (
        f"[{label}] 投稿 {counts.posts} 件（画像つき {counts.posts_with_image}）、"
        f"手がかり {counts.clues} 件"
        f"（画像由来 {counts.image_clues}、本文由来 {counts.text_clues}）、"
        f"抽出失敗 {counts.failed_posts} 件"
    )


def strip_images(posts: Sequence[Post]) -> list[Post]:
    return [post.model_copy(update={"images": []}) for post in posts]


async def _unused_fetch(_post: Post) -> list[bytes]:
    return []


async def run(limit: int, mode: str) -> int:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token.strip():
        raise ThreadsPocError("THREADS_ACCESS_TOKEN が設定されていません")
    settings = get_settings()
    extractor = build_extractor(
        mock_mode=False,
        vlm_base_url=settings.vlm_base_url,
        vlm_api_key=settings.vlm_api_key.get_secret_value(),
        vlm_model=settings.vlm_model,
        ocr_base_url=settings.ocr_base_url,
        allowed_hosts=settings.model_allowed_host_suffixes.split(","),
        text_backend=settings.threads_text_backend,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )
    if not await extractor.model_reachable(settings.model_probe_timeout_seconds):
        print("モデルに接続できません（GPU が起動していないか、設定の誤り）", file=sys.stderr)
        return 2
    _owner, posts = await fetch_own_posts(token, limit, include_images=True)
    if not posts:
        print("診断対象の投稿は 0 件です")
        return 0

    failed = 0
    if mode in ("text", "both"):
        text_posts = strip_images(posts)
        results = [r async for r in extract_posts(extractor, text_posts, _unused_fetch)]
        counts = summarize(text_posts, results)
        print(format_counts("画像なし", counts))
        failed += counts.failed_posts
    if mode in ("image", "both"):
        results = [
            r
            async for r in extract_posts(
                extractor, posts, fetch_threads_images, image_fetch_fallback_to_text=True
            )
        ]
        counts = summarize(posts, results)
        print(format_counts("画像あり", counts))
        failed += counts.failed_posts
    return 1 if failed else 0


def _limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"--limit は 1〜{MAX_LIMIT} にしてください")
    return number


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Threads 画像診断の件数だけの検証")
    parser.add_argument("--limit", type=_limit, default=DEFAULT_LIMIT)
    parser.add_argument("--mode", choices=MODES, default="both")
    args = parser.parse_args(argv)
    # httpx は署名つき URL をログに出しうる。件数以外は何も出さない
    logging.disable(logging.CRITICAL)
    try:
        code = asyncio.run(run(args.limit, args.mode))
    except ThreadsPocError as exc:
        print(str(exc), file=sys.stderr)
        code = 1
    except Exception as exc:
        # 例外のメッセージには URL・本文・トークンが混ざりうるので型名だけ出す
        print(f"検証に失敗しました（{type(exc).__name__}）", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
