from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.market.market_data_service import MarketDataService
from app.schemas.api import SystemHealth

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health", response_model=SystemHealth)
async def health(db: AsyncSession = Depends(get_db)):
    settings = get_settings()

    database_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    market_service = MarketDataService()
    stale = None
    age = None
    try:
        age = await market_service.latest_candle_age_seconds(db)
        stale = await market_service.is_stale(db)
    except Exception:
        pass
    finally:
        await market_service.aclose()

    return SystemHealth(
        database_ok=database_ok,
        hyperliquid_configured=bool(settings.hyperliquid_api_url),
        ollama_configured=bool(settings.ollama_base_url and settings.ollama_model),
        trading_mode=settings.trading_mode.value,
        market_data_stale=stale,
        last_candle_age_seconds=age,
    )
