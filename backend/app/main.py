"""FastAPI application entrypoint.

This process serves the read API and realtime feed for the dashboard. The
actual trading loop (market ingestion -> council -> agents -> risk ->
execution -> fitness -> evolution) runs as a separate background worker
(see scripts/run_cycle.py) so an API restart never interrupts trading —
this is deliberate, not an oversight; see docs/architecture.md.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import validate_api_keys_config

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("app.startup", trading_mode=settings.trading_mode.value, agent_count=settings.agent_count)
    try:
        validate_api_keys_config(settings)
    except ValueError as exc:
        # Refuse to start rather than serve 500s (or, worse, run half-configured).
        logger.error("app.api_keys_invalid", detail=str(exc))
        raise RuntimeError(f"invalid API_KEYS configuration: {exc}") from exc
    if settings.api_auth_required and not settings.api_keys.get_secret_value():
        logger.warning("app.api_auth_no_keys_configured", detail="every protected request will be rejected; set API_KEYS")
    if not settings.api_auth_required:
        logger.warning("app.api_auth_disabled", detail="API_AUTH_REQUIRED=false — development only")
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Autonomous Evolutionary Crypto Trading Laboratory",
        version="0.1.0",
        lifespan=lifespan,
        # The API surface is not public information: docs only when explicitly enabled.
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # API keys travel in headers, never cookies
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        # The dashboard is one self-contained page (inline script/style, same-origin API only).
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.include_router(api_router)

    @app.get("/livez", include_in_schema=False)
    async def livez():
        # Unauthenticated, data-free liveness probe for process supervisors.
        return {"status": "alive"}

    @app.get("/")
    async def frontend():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
