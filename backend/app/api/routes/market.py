from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.enums import MarketRegime
from app.models.market import MarketCandle, MarketRegimeRecord
from app.schemas.api import CandlePoint, MarketSnapshot

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("", response_model=MarketSnapshot)
async def get_market_snapshot(db: AsyncSession = Depends(get_db)):
    """The last CONFIRMED (closed) candle is the source of truth; the still-forming
    candle is exposed separately as `live_price` for display only."""
    settings = get_settings()
    base = select(MarketCandle).where(MarketCandle.symbol == settings.market_symbol, MarketCandle.timeframe == settings.market_timeframe)
    confirmed = (await db.execute(base.where(MarketCandle.is_final.is_(True)).order_by(MarketCandle.open_time.desc()).limit(1))).scalar_one_or_none()
    if confirmed is None:
        raise HTTPException(status_code=404, detail="no confirmed market data available yet")
    forming = (await db.execute(base.where(MarketCandle.is_final.is_(False), MarketCandle.open_time > confirmed.open_time)
                                .order_by(MarketCandle.open_time.desc()).limit(1))).scalar_one_or_none()

    regime = (await db.execute(
        select(MarketRegimeRecord).where(MarketRegimeRecord.symbol == settings.market_symbol,
                                         MarketRegimeRecord.timeframe == settings.market_timeframe)
        .order_by(MarketRegimeRecord.candle_open_time.desc()).limit(1))).scalar_one_or_none()
    age = time.time() - confirmed.close_time / 1000
    return MarketSnapshot(
        symbol=confirmed.symbol, close_price=confirmed.close, timeframe=confirmed.timeframe,
        regime=regime.regime if regime else MarketRegime.UNCERTAIN, regime_confidence=regime.confidence if regime else 0.0,
        candle_open_time=confirmed.open_time, confirmed_candle_close_time=confirmed.close_time,
        volatility_percentile=(regime.detail or {}).get("volatility_percentile", 0.0) if regime else 0.0,
        volume_ratio=(regime.detail or {}).get("volume_ratio", 0.0) if regime else 0.0,
        data_freshness_seconds=age, market_data_stale=age > settings.data_stale_threshold_seconds,
        live_price=forming.close if forming else None, live_candle_open_time=forming.open_time if forming else None,
    )


@router.get("/history", response_model=list[CandlePoint])
async def get_market_history(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, le=500),
):
    settings = get_settings()
    stmt = (
        select(MarketCandle.open_time, MarketCandle.close)
        .where(MarketCandle.symbol == settings.market_symbol, MarketCandle.timeframe == settings.market_timeframe,
               MarketCandle.is_final.is_(True))
        .order_by(MarketCandle.open_time.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [CandlePoint(open_time=open_time, close=close) for open_time, close in reversed(rows)]
