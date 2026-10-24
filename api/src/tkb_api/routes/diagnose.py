"""診断。ログインした本人の投稿を読み、結果を Server-Sent Events で 1 件ずつ流す。

イベントの形は web/src/types/diagnose.ts と同時に変更すること。
  event: post  data: {"post": 投稿}
  event: done  data: {"posts_seen": 件数}

今はモックだけ。MOCK_MODE=1 のとき、架空のデモ用アカウントの投稿をそのまま流す。
投稿の Pydantic モデル（tkb_common に追加予定）ができたら、それを通してから流す。
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from tkb_api.bluesky import BlueskySession
from tkb_api.config import Settings, get_settings
from tkb_api.routes.session import current_session

router = APIRouter(prefix="/api")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _load_demo_posts(settings: Settings) -> list[dict[str, Any]]:
    try:
        doc = json.loads(settings.demo_fixture_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # パスはエラーの文言に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "モック用のデータを読み込めませんでした"
        ) from None
    posts: list[dict[str, Any]] = doc["posts"]
    return posts


async def _stream(posts: list[dict[str, Any]], interval: float) -> AsyncIterator[str]:
    for post in posts:
        yield _sse("post", {"post": post})
        await asyncio.sleep(interval)
    yield _sse("done", {"posts_seen": len(posts)})


@router.post("/diagnose")
async def diagnose(
    _session: Annotated[BlueskySession, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    if not settings.mock_mode:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "まだモックでしか診断できません")

    posts = _load_demo_posts(settings)
    return StreamingResponse(
        _stream(posts, settings.mock_event_interval_seconds),
        media_type="text/event-stream",
        # 途中の中継（プロキシ）にためこまれず、1 件ずつ届くようにする
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
