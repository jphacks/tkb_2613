from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tkb_api.config import Settings, get_settings
from tkb_api.routes import detect


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="tkb_2613 API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(detect.router)

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {"status": "ok", "mock_mode": settings.mock_mode}

    return app


app = create_app()
