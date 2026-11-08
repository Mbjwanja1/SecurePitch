from fastapi import FastAPI

from app import __version__
from app.config import load_settings
from app.crypto.signer import Signer, signer_from_env
from app.middleware import RequestGate
from app.ratelimit import UploadLimiter
from app.routers import approvals, clubs, health, statements
from app.supabase import Supabase


def _signer() -> Signer | None:
    """The platform signer (SIGNER=local or kms). Missing settings mean sealing is unavailable,
    not that the engine won't start: everything before sealing still works."""
    try:
        return signer_from_env()
    except (KeyError, ValueError):
        return None


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
    app.include_router(statements.router)
    app.include_router(clubs.router)
    app.include_router(approvals.router)
    app.state.signer = _signer()
    app.state.upload_limiter = UploadLimiter()
    app.state.supabase = (
        Supabase(settings.supabase_url, settings.supabase_key)
        if settings.supabase_url and settings.supabase_key
        else None
    )

    public_paths = {"/health"} | ({"/docs", "/openapi.json"} if settings.is_dev else set())
    # Outermost layer: checks the key and body size before any request body is read.
    app.add_middleware(
        RequestGate,
        internal_key=settings.internal_key,
        public_paths=public_paths,
        max_body_bytes=settings.max_body_bytes,
    )
    return app


app = create_app()
