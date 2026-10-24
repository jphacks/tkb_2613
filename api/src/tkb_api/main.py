from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tkb_api.bluesky import SessionStore
from tkb_api.config import Settings, get_settings
from tkb_api.routes import detect, diagnose, session


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    # 既定の応答は送られてきた値（パスワードなど）をそのまま返すので、場所と理由だけにする
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in errors]
    return JSONResponse({"detail": detail}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def create_app(
    settings: Settings | None = None,
    sessions: SessionStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        store = cast(SessionStore | None, getattr(app.state, "sessions", None))
        if store is not None:
            store.close()

    app = FastAPI(title="tkb_2613 API", lifespan=lifespan)
    app.state.sessions = (
        sessions if sessions is not None else SessionStore(settings.session_ttl_minutes * 60)
    )
    app.add_exception_handler(RequestValidationError, _validation_error)

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

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "mock_mode": settings.mock_mode}

    return app


app = create_app()
