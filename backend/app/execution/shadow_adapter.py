"""Shadow execution (spec phase 26) — NOT "paper with a different label".

Consumes REAL market data (the live L2 order book), runs the exact same
decision pipeline as live, and NEVER sends an order. For every hypothetical
order it records:

  * the fill a real market order would have received by walking the actual
    book (average price, partial fill when depth is insufficient);
  * slippage versus the signal price;
  * the price actually available after the assumed order-to-book latency
    (a second snapshot) -> "expected vs actual market execution";
  * measured book-fetch latency and the latency we assume live would incur.

Hypothetical positions/PnL then follow the normal accounting with those fills,
so SHADOW StageMetrics feed the reality gap against PAPER/BACKTEST.

Safety: this module can only call the public read endpoint (`l2Book`). It has
no wallet, no signing and no order endpoint; tests assert no request other than
an `info` read is ever made.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.execution.fillmodel import fee_rate_for, slipped_price, slippage_bps
from app.models.enums import ExecutionVenue, OrderStatus, Side

logger = get_logger(__name__)


@dataclass(frozen=True)
class L2Book:
    time_ms: int
    bids: tuple[tuple[float, float], ...]   # (price, size), best first
    asks: tuple[tuple[float, float], ...]

    @property
    def mid(self) -> float | None:
        return (self.bids[0][0] + self.asks[0][0]) / 2 if self.bids and self.asks else None


class BookProvider(Protocol):
    async def get_l2_book(self, coin: str) -> dict: ...


def parse_book(raw: dict, max_levels: int = 20) -> L2Book:
    levels = raw.get("levels") or [[], []]
    bids = tuple((float(l["px"]), float(l["sz"])) for l in levels[0][:max_levels])
    asks = tuple((float(l["px"]), float(l["sz"])) for l in levels[1][:max_levels])
    return L2Book(int(raw.get("time", 0)), bids, asks)


def walk_book(levels: tuple[tuple[float, float], ...], quantity: float) -> tuple[float | None, float]:
    """Volume-weighted fill of `quantity` across `levels`. Returns (avg_price, filled_qty)."""
    remaining, notional, filled = quantity, 0.0, 0.0
    for px, sz in levels:
        take = min(remaining, sz)
        notional += take * px
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return (notional / filled if filled > 0 else None), filled


class ShadowExecutionAdapter(ExecutionEngine):
    venue = ExecutionVenue.SHADOW

    def __init__(self, book_provider: BookProvider | None = None, *, own_client: bool = False) -> None:
        s = get_settings()
        self._s = s
        if book_provider is None:
            from app.market.hyperliquid_client import HyperliquidClient
            book_provider = HyperliquidClient()
            own_client = True
        self._provider = book_provider
        self._own_client = own_client
        self._cache: tuple[float, L2Book, L2Book | None, float] | None = None  # (fetched_at, book, after_latency, fetch_ms)
        self._lock = asyncio.Lock()
        self._seen: set[str] = set()

    async def aclose(self) -> None:
        if self._own_client and hasattr(self._provider, "aclose"):
            await self._provider.aclose()

    async def _snapshot(self, coin: str) -> tuple[L2Book, L2Book | None, float]:
        """One (book, book-after-latency) pair shared by all agents within the TTL."""
        async with self._lock:
            now = time.monotonic()
            if self._cache and now - self._cache[0] < self._s.shadow_book_ttl_seconds:
                return self._cache[1], self._cache[2], self._cache[3]
            t0 = time.monotonic()
            book = parse_book(await self._provider.get_l2_book(coin), self._s.shadow_max_book_levels)
            fetch_ms = (time.monotonic() - t0) * 1000
            after: L2Book | None = None
            await asyncio.sleep(self._s.shadow_assumed_latency_ms / 1000)
            try:
                after = parse_book(await self._provider.get_l2_book(coin), self._s.shadow_max_book_levels)
            except Exception as exc:  # the comparison snapshot is best-effort
                logger.warning("shadow.after_latency_book_failed", error=str(exc))
            self._cache = (time.monotonic(), book, after, fetch_ms)
            return book, after, fetch_ms

    def _fail(self, request: ExecutionRequest, reason: str, extra: dict | None = None) -> ExecutionResult:
        return ExecutionResult(
            client_order_id=request.client_order_id, status=OrderStatus.FAILED, filled_price=None, filled_quantity=0.0,
            fee=0.0, slippage_cost=0.0, latency_ms=0, raw_response={"shadow": True, "rejected": reason, **(extra or {})},
            rejection_reason=reason,
        )

    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        # NEVER an exchange write: only the public book is read; the fill is hypothetical.
        if request.client_order_id in self._seen:
            return self._fail(request, "duplicate_client_order_id")
        self._seen.add(request.client_order_id)

        buying = (request.side == Side.LONG) != request.reduce_only     # entering long / covering short buys
        try:
            book, after, fetch_ms = await self._snapshot(request.symbol)
        except Exception as exc:
            if request.reduce_only:  # an exit must never be stranded by a data outage: fall back to the cost model
                return self._fallback_exit(request, str(exc))
            return self._fail(request, "book_unavailable", {"error": str(exc)[:200]})

        levels = book.asks if buying else book.bids
        avg_px: float | None
        if request.order_kind == "take_profit":
            avg_px, filled = request.reference_price, request.quantity          # resting limit fills at its level  # noqa
        else:
            avg_px, filled = walk_book(levels, request.quantity)
        if avg_px is None or filled <= 0:
            return self._fail(request, "no_liquidity")

        status = OrderStatus.FILLED if filled >= request.quantity - 1e-9 else OrderStatus.PARTIALLY_FILLED
        if request.reduce_only and status == OrderStatus.PARTIALLY_FILLED:
            # a position must be fully closable: fill the remainder at the deepest level touched
            avg_px = (avg_px * filled + levels[-1][0] * (request.quantity - filled)) / request.quantity
            filled, status = request.quantity, OrderStatus.FILLED
        fee = avg_px * filled * fee_rate_for(request.order_kind, taker=self._s.paper_fee_rate, maker=self._s.paper_maker_fee_rate)
        adverse = 1 if buying else -1
        slip_bps = adverse * (avg_px / request.reference_price - 1) * 10_000 if request.reference_price else 0.0
        observed = after.mid if after is not None else None
        latency_ms = int(fetch_ms + self._s.shadow_assumed_latency_ms)
        return ExecutionResult(
            client_order_id=request.client_order_id, status=status, filled_price=avg_px, filled_quantity=filled, fee=fee,
            slippage_cost=abs(avg_px - request.reference_price) * filled, latency_ms=latency_ms,
            raw_response={
                "shadow": True, "sent_to_exchange": False, "expected_fill_price": avg_px,
                "reference_price": request.reference_price, "slippage_bps": slip_bps,
                "book_time_ms": book.time_ms, "best_bid": book.bids[0][0] if book.bids else None,
                "best_ask": book.asks[0][0] if book.asks else None, "depth_levels_used": len(levels),
                "observed_mid_after_latency": observed,
                "drift_after_latency_bps": ((observed / book.mid - 1) * 10_000) if observed and book.mid else None,
                "book_fetch_ms": fetch_ms, "assumed_latency_ms": self._s.shadow_assumed_latency_ms,
            },
        )

    def _fallback_exit(self, request: ExecutionRequest, error: str) -> ExecutionResult:
        bps = slippage_bps(request.order_kind, request.reference_price * request.quantity, base_bps=self._s.paper_slippage_bps,
                           impact_bps_per_10k=self._s.paper_slippage_impact_bps_per_10k, stop_multiplier=self._s.paper_stop_slippage_multiplier)
        px = slipped_price(request.reference_price, request.side, reduce_only=True, bps=bps)
        fee = px * request.quantity * fee_rate_for(request.order_kind, taker=self._s.paper_fee_rate, maker=self._s.paper_maker_fee_rate)
        return ExecutionResult(
            client_order_id=request.client_order_id, status=OrderStatus.FILLED, filled_price=px, filled_quantity=request.quantity,
            fee=fee, slippage_cost=abs(px - request.reference_price) * request.quantity, latency_ms=self._s.shadow_assumed_latency_ms,
            raw_response={"shadow": True, "sent_to_exchange": False, "fallback": "cost_model_book_unavailable", "error": error[:200]},
        )
