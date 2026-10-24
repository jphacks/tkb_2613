from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tkb_api.bluesky_auth import BlueskyAuthenticator
from tkb_api.config import Settings, get_settings
from tkb_api.routes import detect, session
from tkb_api.sessions import SessionStore


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    authenticator: BlueskyAuthenticator | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        store = cast(SessionStore | None, getattr(app.state, "session_store", None))
        if store is not None:
            store.close()

    app = FastAPI(title="tkb_2613 API", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_store = session_store if session_store is not None else SessionStore()
    app.state.authenticator = authenticator if authenticator is not None else BlueskyAuthenticator()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(detect.router)
    app.include_router(session.router)

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "mock_mode": settings.mock_mode}

    return app


app = create_app()
