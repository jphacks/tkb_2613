import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tkb_api.bluesky import SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.routes import delete, detect, diagnose, session, share, simulate
from tkb_api.shares import ShareStore


class NoStoreMiddleware:
    """api のすべての応答に Cache-Control: no-store, no-transform を付ける。

    途中の中継（Vercel の CDN など）に保存させない。ログイン状態の応答がキャッシュされると、
    別の人に他人のログイン情報が返るおそれがあるため。
    no-transform は中継に圧縮させないため。画面の /api を中継する Next.js は、ブラウザが gzip を
    受け付けると応答を圧縮し、診断の SSE を最後までためこんで一度に送ってしまう。
    応答本文には触らないので、SSE もためこまずにそのまま流れる。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store, no-transform"
            await send(message)

        await self.app(scope, receive, send_no_store)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    # 既定の応答は送られてきた値（パスワードなど）をそのまま返すので、場所と理由だけにする
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in errors]
    return JSONResponse({"detail": detail}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _configure_logging() -> None:
    """診断の所要時間を INFO で出す。uvicorn は自分のロガーしか設定しないため。

    ログに出すのは件数と秒数だけにする。リクエスト本文・投稿の本文・写真は出さない。
    """
    for name in ("tkb_api", "tkb_detect"):
        app_logger = logging.getLogger(name)
        if app_logger.handlers:
            continue
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)


def create_app(
    settings: Settings | None = None,
    sessions: SessionStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        store = cast(SessionStore | None, getattr(app.state, "sessions", None))
        if store is not None:
            store.close()
        shares = cast(ShareStore | None, getattr(app.state, "shares", None))
        if shares is not None:
            shares.close()

    app = FastAPI(title="tkb_2613 API", lifespan=lifespan)
    app.state.sessions = (
        sessions if sessions is not None else SessionStore(settings.session_ttl_minutes * 60)
    )
    app.state.shares = ShareStore(settings.share_db_path, settings.share_ttl_minutes * 60)
    app.add_exception_handler(RequestValidationError, _validation_error)

    app.add_middleware(NoStoreMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(detect.router)
    app.include_router(session.router)
    app.include_router(diagnose.router)
    app.include_router(simulate.router)
    app.include_router(delete.router)
    app.include_router(share.router)

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "mock_mode": settings.mock_mode}

    return app


app = create_app()
