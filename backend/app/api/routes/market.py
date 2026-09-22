from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.market import MarketCandle, MarketRegimeRecord
from app.schemas.api import CandlePoint, MarketSnapshot

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("", response_model=MarketSnapshot)
async def get_market_snapshot(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    candle_stmt = (
        select(MarketCandle)
        .where(MarketCandle.symbol == settings.market_symbol, MarketCandle.timeframe == settings.market_timeframe)
        .order_by(MarketCandle.open_time.desc())
        .limit(1)
    )
    candle = (await db.execute(candle_stmt)).scalar_one_or_none()
    if candle is None:
        raise HTTPException(status_code=404, detail="no market data available yet")

    regime_stmt = (
        select(MarketRegimeRecord)
        .where(
            MarketRegimeRecord.symbol == settings.market_symbol,
            MarketRegimeRecord.timeframe == settings.market_timeframe,
        )
        .order_by(MarketRegimeRecord.candle_open_time.desc())
        .limit(1)
    )
    regime = (await db.execute(regime_stmt)).scalar_one_or_none()

    return MarketSnapshot(
        symbol=candle.symbol,
        close_price=candle.close,
        regime=regime.regime if regime else "UNCERTAIN",
        regime_confidence=regime.confidence if regime else 0.0,
        candle_open_time=candle.open_time,
        volatility_percentile=(regime.detail or {}).get("volatility_percentile", 0.0) if regime else 0.0,
        volume_ratio=(regime.detail or {}).get("volume_ratio", 0.0) if regime else 0.0,
    )


@router.get("/history", response_model=list[CandlePoint])
async def get_market_history(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, le=500),
):
    settings = get_settings()
    stmt = (
        select(MarketCandle.open_time, MarketCandle.close)
        .where(MarketCandle.symbol == settings.market_symbol, MarketCandle.timeframe == settings.market_timeframe)
        .order_by(MarketCandle.open_time.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [CandlePoint(open_time=open_time, close=close) for open_time, close in reversed(rows)]
