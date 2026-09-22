"""MarketDataService — the single shared market-data pipeline (spec 6).

500 agents never fetch market data themselves. This service is the only
writer of `market_candles`, and the only reader of `HyperliquidClient`. It
provides:
  - `sync_recent_candles`: idempotent upsert of the latest candles
  - `get_recent_candles`: a pandas frame for the feature engine
  - `is_stale`: whether the last known candle is too old to trade on
"""
from __future__ import annotations

import time

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.market.hyperliquid_client import HyperliquidClient
from app.models.market import MarketCandle

logger = get_logger(__name__)

STALE_DATA_THRESHOLD_SECONDS = 180  # spec 41: stop new trades if data is stale


class MarketDataService:
    def __init__(self, client: HyperliquidClient | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = client or HyperliquidClient()
        self._symbol = settings.market_symbol
        self._timeframe = settings.market_timeframe

    async def aclose(self) -> None:
        await self._client.aclose()

    async def sync_recent_candles(self, db: AsyncSession, lookback_candles: int = 500) -> int:
        """Fetches the last `lookback_candles` candles and upserts them.
        Returns the number of rows inserted/updated. Duplicate candles
        (same symbol/timeframe/open_time) are overwritten idempotently
        rather than duplicated (spec 6: duplicate prevention)."""
        interval_ms = HyperliquidClient.timeframe_to_ms(self._timeframe)
        end_ms = HyperliquidClient.now_ms()
        start_ms = end_ms - interval_ms * lookback_candles

        raw = await self._client.get_candles(self._symbol, self._timeframe, start_ms, end_ms)
        if not raw:
            logger.warning("market_data.empty_response", symbol=self._symbol)
            return 0

        self._check_gaps(raw, interval_ms)

        # Funding/open interest are point-in-time exchange values.  They are
        # persisted with the most recently confirmed candle as the best
        # available attribution; a failure here must not turn a healthy
        # historical-candle recovery into a tradeable data set with invented
        # funding values.
        funding_context: dict = {}
        try:
            funding_context = await self._client.get_meta_and_funding(self._symbol)
        except Exception as exc:
            logger.warning("market_data.funding_context_unavailable", error=str(exc))

        funding_rate = _as_float(funding_context.get("funding"))
        open_interest = _as_float(funding_context.get("openInterest"))
        rows = [
            {
                "symbol": self._symbol,
                "timeframe": self._timeframe,
                "open_time": int(c["t"]),
                "close_time": int(c["T"]),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
                "trade_count": int(c.get("n", 0)) or None,
                "is_final": int(c["T"]) <= end_ms,
                "funding_rate": funding_rate if int(c["T"]) <= end_ms else None,
                "open_interest": open_interest if int(c["T"]) <= end_ms else None,
                "source": "hyperliquid",
            }
            for c in raw
        ]

        stmt = pg_insert(MarketCandle).values(rows)
        update_cols = {
            col: getattr(stmt.excluded, col)
            for col in ("close_time", "open", "high", "low", "close", "volume", "trade_count", "is_final", "funding_rate", "open_interest")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "open_time"], set_=update_cols
        )
        await db.execute(stmt)
        await db.commit()
        return len(rows)

    def _check_gaps(self, raw: list[dict], interval_ms: int) -> None:
        for prev, curr in zip(raw, raw[1:]):
            if int(curr["t"]) - int(prev["t"]) != interval_ms:
                logger.warning(
                    "market_data.gap_detected",
                    symbol=self._symbol,
                    prev_open=prev["t"],
                    curr_open=curr["t"],
                    expected_interval_ms=interval_ms,
                )

    async def get_recent_candles(
        self, db: AsyncSession, limit: int = 300, *, confirmed_only: bool = True
    ) -> pd.DataFrame:
        """Return oldest-to-newest candles. Trading callers must use the
        default confirmed-only path; mutable bars are available only to
        explicitly labelled display/recovery callers."""
        stmt = (
            select(MarketCandle)
            .where(MarketCandle.symbol == self._symbol, MarketCandle.timeframe == self._timeframe)
            .order_by(MarketCandle.open_time.desc())
            .limit(limit)
        )
        if confirmed_only:
            stmt = stmt.where(MarketCandle.is_final.is_(True))
        result = await db.execute(stmt)
        candles = list(reversed(result.scalars().all()))
        if not candles:
            return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
        return pd.DataFrame(
            [
                {
                    "open_time": c.open_time,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "funding_rate": c.funding_rate,
                    "open_interest": c.open_interest,
                }
                for c in candles
            ]
        )

    async def latest_candle_age_seconds(self, db: AsyncSession) -> float | None:
        stmt = (
            select(MarketCandle.close_time)
            .where(
                MarketCandle.symbol == self._symbol,
                MarketCandle.timeframe == self._timeframe,
                MarketCandle.is_final.is_(True),
            )
            .order_by(MarketCandle.open_time.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        close_time = result.scalar_one_or_none()
        if close_time is None:
            return None
        return time.time() - (close_time / 1000)

    async def is_stale(self, db: AsyncSession) -> bool:
        age = await self.latest_candle_age_seconds(db)
        if age is None:
            return True
        return age > STALE_DATA_THRESHOLD_SECONDS


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
