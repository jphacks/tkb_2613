"""Threads テスターの本人投稿をローカルで診断する読み取り専用 PoC。

実行: THREADS_ACCESS_TOKEN を環境変数に設定して uv run python -m tkb_api.threads_poc
トークン、投稿本文、推定値は標準出力にもログにも出さない。
"""

import asyncio
import os
import sys
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from tkb_api.config import get_settings
from tkb_api.pipeline import diagnose_events, load_gazetteer, real_extractions
from tkb_common.schemas import THREADS_MEDIA_HOST_SUFFIXES, Post
from tkb_detect.batch import extract_posts
from tkb_detect.extract import build_extractor

THREADS_API = "https://graph.threads.com/v1.0"
MAX_POSTS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class ThreadsPocError(Exception):
    """応答本文やトークンを含まない、利用者向けのエラー。"""


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ThreadsPocError("Threads API の応答形式が不正です")
    return value


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return _object(response.json())
    except httpx.HTTPStatusError as exc:
        raise ThreadsPocError(
            f"Threads API が HTTP {exc.response.status_code} を返しました"
        ) from None
    except (httpx.RequestError, ValueError):
        raise ThreadsPocError("Threads API の取得または応答の解析に失敗しました") from None


def _threads_image_url(item: dict[str, Any], include_image: bool) -> str | None:
    if not include_image or item.get("media_type") != "IMAGE":
        return None
    value = item.get("media_url")
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(
        host == suffix or host.endswith(f".{suffix}") for suffix in THREADS_MEDIA_HOST_SUFFIXES
    ):
        return None
    return value


def to_post(item: dict[str, Any], *, include_image: bool = False) -> Post | None:
    """本文と、明示的に有効な場合だけ単一画像を共通型へ変換する。"""
    text = item.get("text")
    image_url = _threads_image_url(item, include_image)
    if text is not None and not isinstance(text, str):
        raise ThreadsPocError("Threads 投稿の形式が不正です")
    if not isinstance(text, str):
        text = ""
    if not text.strip() and image_url is None:
        return None
    post_id = item.get("id")
    timestamp = item.get("timestamp")
    if not isinstance(post_id, str) or not post_id or not isinstance(timestamp, str):
        raise ThreadsPocError("Threads 投稿の形式が不正です")
    try:
        images = (
            []
            if image_url is None
            else [{"index": 0, "url": image_url, "alt": "", "width": 1, "height": 1}]
        )
        return Post.model_validate(
            {
                "post_id": f"threads:{post_id}",
                "text": text,
                "created_at": timestamp,
                "images": images,
            }
        )
    except ValidationError:
        raise ThreadsPocError("Threads 投稿の日時が不正です") from None


async def fetch_own_posts(
    token: str, limit: int = MAX_POSTS, *, include_images: bool = False
) -> tuple[str, list[Post]]:
    if not token.strip():
        raise ThreadsPocError("THREADS_ACCESS_TOKEN が設定されていません")
    if not 1 <= limit <= 100:
        raise ValueError("limit は 1〜100 にしてください")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=THREADS_API, headers=headers, timeout=20, follow_redirects=False, trust_env=False
    ) as client:
        profile = await _get(client, "/me", {"fields": "id,username"})
        user_id = profile.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise ThreadsPocError("Threads の本人 ID を確認できませんでした")

        posts: list[Post] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        while len(posts) < limit:
            fields = "id,text,timestamp,media_type"
            if include_images:
                fields += ",media_url"
            params: dict[str, Any] = {
                "fields": fields,
                "limit": min(50, limit - len(posts)),
            }
            if cursor is not None:
                params["after"] = cursor
            page = await _get(client, "/me/threads", params)
            items = page.get("data")
            if not isinstance(items, list):
                raise ThreadsPocError("Threads の投稿一覧の形式が不正です")
            for raw in items:
                post = to_post(_object(raw), include_image=include_images)
                if post is not None and post.post_id not in seen_ids:
                    posts.append(post)
                    seen_ids.add(post.post_id)
                    if len(posts) == limit:
                        break
            paging = page.get("paging")
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(next_cursor, str) or not next_cursor or not items:
                break
            if next_cursor in seen_cursors:
                raise ThreadsPocError("Threads のページ送りが繰り返されました")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return user_id, posts


async def fetch_threads_images(post: Post) -> list[bytes]:
    """許可済みMeta CDNからThreadsの画像1枚だけをメモリへ取得する。"""
    if len(post.images) > 1:
        raise ThreadsPocError("Threads の画像は1枚だけ診断できます")
    result: list[bytes] = []
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, trust_env=False, headers={"Accept": "image/*"}
    ) as client:
        for image in post.images:
            url = _threads_image_url(
                {"media_type": "IMAGE", "media_url": image.url}, include_image=True
            )
            if url is None:
                raise ThreadsPocError("Threads の画像取得先を確認できませんでした")
            try:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if not media_type.startswith("image/"):
                        raise ThreadsPocError("Threads の画像形式を確認できませんでした")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ThreadsPocError("Threads の画像が大きすぎます")
                        chunks.append(chunk)
                    result.append(b"".join(chunks))
            except httpx.HTTPError:
                # URLや応答本文は例外・ログへ出さない。
                raise ThreadsPocError("Threads の画像を取得できませんでした") from None
    return result


async def run() -> int:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token.strip():
        raise ThreadsPocError("THREADS_ACCESS_TOKEN が設定されていません")
    settings = get_settings()
    _user_id, posts = await fetch_own_posts(token, include_images=settings.threads_image_diagnosis)
    if not posts:
        print("診断対象の本文付き投稿は 0 件です")
        return 0

    extractor = build_extractor(
        mock_mode=False,
        vlm_base_url=settings.vlm_base_url,
        vlm_api_key=settings.vlm_api_key.get_secret_value(),
        vlm_model=settings.vlm_model,
        ocr_base_url=settings.ocr_base_url,
        allowed_hosts=settings.model_allowed_host_suffixes.split(","),
        text_backend=settings.text_backend,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )
    gazetteer = load_gazetteer(settings.gazetteer_dir)
    clue_count = conclusion_count = failed = 0
    extractions = (
        extract_posts(extractor, posts, fetch_threads_images)
        if settings.threads_image_diagnosis
        else real_extractions(extractor, posts)
    )
    async for event, data in diagnose_events(posts, extractions, gazetteer):
        if event == "clues":
            failed += data["error"] is not None
        elif event == "conclusions":
            clue_count = len(data["clues"])
            conclusion_count = len(data["conclusions"])
        # post / plan の内容は表示しない。plan はメモリ内の仮除外計算だけ。
    print(
        f"Threads 本人 ID を確認。投稿 {len(posts)} 件、手がかり {clue_count} 件、"
        f"推定 {conclusion_count} 件、抽出失敗 {failed} 件。"
    )
    return 1 if failed else 0


def main() -> None:
    try:
        code = asyncio.run(run())
    except ThreadsPocError as exc:
        print(str(exc), file=sys.stderr)
        code = 1
    except Exception:
        # モデル設定や接続の例外にも URL・本文・トークンが混ざる可能性がある。
        print("診断の準備または実行に失敗しました", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
