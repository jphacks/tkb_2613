"""診断。ログインした本人の投稿を読み、結果を Server-Sent Events で 1 件ずつ流す。

イベントの形は web/src/types/diagnose.ts と同時に変更すること。
  event: post         data: {"post": 投稿}                          投稿ごと
  event: clues        data: {"post_id", "clues": [手がかり], "error"} 手がかりの取り出しが終わった順
  event: conclusions  data: {"clues": [全手がかり], "conclusions": [{"rule", "attribute",
                             "value", "clue_indices", "note"}]}      最後に1回。番号は clues の並び
  event: done         data: {"posts_seen": 件数}

MOCK_MODE=1 のときは、架空のデモ用アカウントの投稿と手がかりを流す
（Bluesky にもモデルにも接続しない）。
MOCK_MODE=0 のときは、セッションの DID 本人の投稿を Bluesky から直近 MAX_POSTS 件取り、
写真を cdn.bsky.app から取って手がかりを取り出し、推理する。
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from tkb_api import bluesky
from tkb_api.bluesky import BlueskySession, PostsFetcher
from tkb_api.config import Settings, get_settings
from tkb_api.pipeline import diagnose_events, load_gazetteer, mock_extractions, real_extractions
from tkb_api.routes.session import current_session
from tkb_common.schemas import Post
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor, build_extractor
from tkb_engine.gazetteer import Gazetteer

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


async def _stream(events: AsyncIterator[tuple[str, dict[str, Any]]]) -> AsyncIterator[str]:
    async for event, data in events:
        yield _sse(event, data)


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


ExtractorFactory = Callable[[], Extractor]


def get_extractor_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtractorFactory:
    """手がかりを取り出す部品は、本番の診断で使うときに作る。

    接続先の確認（第三者の AI サービスを拒否するなど）は作るときに行うので、
    ログインの確認やモックの診断より先に失敗しないようにする。
    """

    def build() -> Extractor:
        return build_extractor(
            mock_mode=settings.mock_mode,
            vlm_base_url=settings.vlm_base_url,
            vlm_api_key=settings.vlm_api_key.get_secret_value(),
            vlm_model=settings.vlm_model,
            ocr_base_url=settings.ocr_base_url,
        )

    return build


def _build_extractor(factory: ExtractorFactory) -> Extractor:
    try:
        return factory()
    except DetectError:
        # 接続先の URL などは応答に入れない
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "画像を読むモデルの接続先が設定されていません"
        ) from None


@lru_cache(maxsize=4)
def _cached_gazetteer(data_dir: Path) -> Gazetteer:
    return load_gazetteer(data_dir)


def get_gazetteer(settings: Annotated[Settings, Depends(get_settings)]) -> Gazetteer:
    return _cached_gazetteer(settings.gazetteer_dir)


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
    extractor_factory: Annotated[ExtractorFactory, Depends(get_extractor_factory)],
    gazetteer: Annotated[Gazetteer, Depends(get_gazetteer)],
) -> StreamingResponse:
    if settings.mock_mode:
        posts = _load_demo_posts(settings)
        interval = settings.mock_event_interval_seconds
        extractions = mock_extractions(settings.demo_fixture_path, posts, interval)
    else:
        posts = await _fetch_own_posts(session, settings, fetch_posts)
        interval = 0
        extractions = real_extractions(_build_extractor(extractor_factory), posts)
    events = diagnose_events(posts, extractions, gazetteer, interval)
    return StreamingResponse(
        _with_keep_alive(_stream(events), settings.sse_keepalive_seconds),
        media_type="text/event-stream",
        # 途中の中継（プロキシ）にためこまれず、1 件ずつ届くようにする
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
