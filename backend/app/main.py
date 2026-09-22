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

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("app.startup", trading_mode=settings.trading_mode.value, agent_count=settings.agent_count)
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Autonomous Evolutionary Crypto Trading Laboratory",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/")
    async def frontend():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
