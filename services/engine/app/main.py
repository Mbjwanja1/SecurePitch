from fastapi import FastAPI

from app import __version__
from app.config import load_settings
from app.routers import health


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="SecurePitch engine",
        version=__version__,
        # The engine is public through the tunnel; only show API docs in local development.
        docs_url="/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_dev else None,
    )
    app.state.settings = settings
    app.include_router(health.router)
    return app


app = create_app()
