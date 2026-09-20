"""Thin async client for Hyperliquid's public `info` REST endpoint and
websocket feed. This is the ONLY place in the codebase allowed to talk to
Hyperliquid directly (spec section 6) — everything else goes through
MarketDataService.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}


class HyperliquidError(RuntimeError):
    pass


class HyperliquidClient:
    """Wraps Hyperliquid's `/info` endpoint. Live order placement (the
    exchange-signing `/exchange` endpoint) is intentionally NOT implemented
    here yet — see app.execution.live_adapter for the documented interface
    that will require wallet signing before TRADING_MODE=live can place
    real orders."""

    def __init__(self, base_url: str | None = None, timeout: float = 15.0) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.hyperliquid_api_url).rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _post_info(self, payload: dict[str, Any]) -> Any:
        resp = await self._client.post("/info", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_candles(
        self, coin: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[dict[str, Any]]:
        """Returns raw Hyperliquid candle dicts:
        {"t": open_ms, "T": close_ms, "o","h","l","c","v","n" (trade count)}."""
        payload = {
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_time_ms, "endTime": end_time_ms},
        }
        try:
            data = await self._post_info(payload)
        except httpx.HTTPStatusError as exc:
            raise HyperliquidError(f"candleSnapshot failed: {exc}") from exc
        if not isinstance(data, list):
            raise HyperliquidError(f"unexpected candleSnapshot response shape: {type(data)}")
        return data

    async def get_meta_and_funding(self, coin: str) -> dict[str, Any]:
        """Fetches perp metadata + current funding/open-interest context."""
        try:
            meta = await self._post_info({"type": "metaAndAssetCtxs"})
        except httpx.HTTPStatusError as exc:
            raise HyperliquidError(f"metaAndAssetCtxs failed: {exc}") from exc

        universe = meta[0].get("universe", []) if meta else []
        ctxs = meta[1] if len(meta) > 1 else []
        for idx, asset in enumerate(universe):
            if asset.get("name") == coin and idx < len(ctxs):
                return ctxs[idx]
        return {}

    @staticmethod
    def timeframe_to_ms(timeframe: str) -> int:
        if timeframe not in _TIMEFRAME_MS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        return _TIMEFRAME_MS[timeframe]

    @staticmethod
    def now_ms() -> int:
        return int(time.time() * 1000)
