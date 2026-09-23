"""Glue between the WebSocket transport and the single candle store.

Adds ONE rule on top of MarketDataService's clock-based finality: when the
exchange starts streaming bar N+1, bar N is definitively closed, so the last
frame seen for N is re-upserted as confirmed (no waiting for the REST poll).
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.market.market_data_service import MarketDataService

logger = get_logger(__name__)


class WsCandleIngestor:
    def __init__(self, session_factory, market: MarketDataService) -> None:
        self._session_factory = session_factory
        self._market = market
        self._latest: dict | None = None

    async def __call__(self, raws: list[dict]) -> None:
        grace = get_settings().candle_finality_grace_ms
        async with self._session_factory() as db:
            for raw in sorted(raws, key=lambda r: int(r["t"])):
                if self._latest is not None and int(raw["t"]) > int(self._latest["t"]):
                    # The exchange moved on: the previous bar is closed.
                    await self._market.upsert_candles(db, [self._latest], now_ms=int(self._latest["T"]) + grace)
                if self._latest is None or int(raw["t"]) >= int(self._latest["t"]):
                    self._latest = raw
            await self._market.upsert_candles(db, raws)
