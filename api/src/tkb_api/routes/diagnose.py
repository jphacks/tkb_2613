"""診断。ログインした本人の投稿を読み、結果を Server-Sent Events で 1 件ずつ流す。

イベントの形は web/src/types/diagnose.ts と同時に変更すること。
  event: post  data: {"post": 投稿}
  event: done  data: {"posts_seen": 件数}

MOCK_MODE=1 のときは、架空のデモ用アカウントの投稿を Post の形で確かめてから流す。
MOCK_MODE=0 のときは、セッションの DID 本人の投稿を Bluesky から直近 MAX_POSTS 件取って流す。
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, PostsFetcher
from tkb_api.config import Settings, get_settings
from tkb_api.routes.session import current_session
from tkb_common.schemas import Post

router = APIRouter(prefix="/api")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_demo_posts(settings: Settings) -> list[Post]:
    try:
        doc = json.loads(settings.demo_fixture_path.read_text(encoding="utf-8"))
        return [Post.model_validate(p) for p in doc["posts"]]
    except (OSError, ValueError, KeyError, TypeError):
        # pydantic の ValidationError は ValueError の仲間。パスや中身はエラーの文言に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用のデータを読み込めませんでした"
        ) from None


async def _stream(posts: list[Post], interval: float) -> AsyncIterator[str]:
    for post in posts:
        yield _sse("post", {"post": post.model_dump(mode="json")})
        await asyncio.sleep(interval)
    yield _sse("done", {"posts_seen": len(posts)})


async def _with_keep_alive(source: AsyncIterator[str], interval: float) -> AsyncIterator[str]:
    """source の間が interval 秒より空いたら、SSE のコメント（: keep-alive）を送る。

    途中の中継（Vercel、Tailscale、Cloudflare）に、止まった接続だと思われて切られないようにする。
    画面はコメント行を読み飛ばす。
    """
    pending = asyncio.ensure_future(anext(source))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk
            pending = asyncio.ensure_future(anext(source))
    finally:
        pending.cancel()


def get_fetch_posts() -> PostsFetcher:
    return bluesky.fetch_own_posts


async def _fetch_own_posts(
    session: BlueskySession, settings: Settings, fetch_posts: PostsFetcher
) -> list[Post]:
    if session.client is None:
        # モックでログインしたあとに MOCK_MODE=0 で起動し直した場合など
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインし直してください")
    try:
        return await fetch_posts(session.client, session.did, settings.max_posts)
    except bluesky.BlueskyUnavailableError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Bluesky から投稿を取得できませんでした"
        ) from None


@router.post("/diagnose")
async def diagnose(
    session: Annotated[BlueskySession, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    fetch_posts: Annotated[PostsFetcher, Depends(get_fetch_posts)],
) -> StreamingResponse:
    if settings.mock_mode:
        posts = _load_demo_posts(settings)
        interval = settings.mock_event_interval_seconds
    else:
        posts = await _fetch_own_posts(session, settings, fetch_posts)
        interval = 0
    return StreamingResponse(
        _with_keep_alive(_stream(posts, interval), settings.sse_keepalive_seconds),
        media_type="text/event-stream",
        # 途中の中継（プロキシ）にためこまれず、1 件ずつ届くようにする
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
