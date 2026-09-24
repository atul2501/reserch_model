"""Paper execution adapter v2 (spec sections 5/19; phase 7).

A research-grade fill model, not "instant fill at the wanted price":

  * adverse slippage = base bps + size-aware impact; stop/liquidation orders
    slip more (they execute into a moving market); resting take-profit limit
    orders pay no slippage and the maker fee;
  * simulated latency (reported, optional price drift) — no real sleeping;
  * quantity rounded down to the lot size; min-notional and random rejects;
  * partial fills (configurable probability / minimum fraction);
  * fees on the FILLED notional;
  * idempotent on `client_order_id` (in-process set + the DB unique constraint).

Everything is deterministic per order: the RNG is seeded from
(`paper_random_seed`, `client_order_id`), so replays reproduce fills exactly
regardless of iteration order. NEVER performs network I/O (enforced by tests).
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import random

from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.execution.fillmodel import fee_rate_for, slipped_price, slippage_bps
from app.models.enums import ExecutionVenue, OrderStatus

logger = get_logger(__name__)

# Idempotency guard: client_order_ids already filled in this process. The
# durable guard is the UNIQUE constraint on Order.client_order_id.
_SEEN_ORDER_IDS: set[str] = set()


class PaperExecutionAdapter(ExecutionEngine):
    venue = ExecutionVenue.PAPER

    def __init__(self) -> None:
        settings = get_settings()
        self._s = settings
        self._fee_rate = settings.paper_fee_rate
        self._slippage_bps = settings.paper_slippage_bps
        self._latency_ms = settings.paper_latency_ms

    @property
    def fill_timing(self) -> str:
        return "next_open" if self._s.paper_fill_timing == "next_open" else "immediate"

    def _seen_ids(self) -> set[str]:
        return _SEEN_ORDER_IDS

    # -- helpers ---------------------------------------------------------- #
    def _rng(self, client_order_id: str) -> random.Random:
        digest = hashlib.sha256(f"{self._s.paper_random_seed}:{client_order_id}".encode()).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    def _floor_to_step(self, quantity: float) -> float:
        step = self._s.paper_quantity_step
        if step <= 0:
            return quantity
        return math.floor(quantity / step + 1e-9) * step

    def _reject(self, request: ExecutionRequest, reason: str, latency_ms: int = 0) -> ExecutionResult:
        return ExecutionResult(
            client_order_id=request.client_order_id, status=OrderStatus.FAILED, filled_price=None,
            filled_quantity=0.0, fee=0.0, slippage_cost=0.0, latency_ms=latency_ms,
            raw_response={"simulated": True, "rejected": reason}, rejection_reason=reason,
        )

    def slippage_bps_for(self, request: ExecutionRequest, quantity: float | None = None) -> float:
        """Adverse slippage (bps) for this order (shared model, see fillmodel). Priced on the quantity that is
        actually FILLED (after lot rounding), exactly like the backtest."""
        qty = request.quantity if quantity is None else quantity
        return slippage_bps(
            request.order_kind, request.reference_price * qty,
            base_bps=self._slippage_bps, impact_bps_per_10k=self._s.paper_slippage_impact_bps_per_10k,
            stop_multiplier=self._s.paper_stop_slippage_multiplier,
        )

    # -- interface -------------------------------------------------------- #
    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        s = self._s
        if request.client_order_id in _SEEN_ORDER_IDS:
            logger.warning("paper_execution.duplicate_order_id_blocked", client_order_id=request.client_order_id)
            return self._reject(request, "duplicate_client_order_id")
        _SEEN_ORDER_IDS.add(request.client_order_id)
        self._track(request.agent_id, request.client_order_id)

        rng = self._rng(request.client_order_id)
        latency_ms = max(0, int(rng.gauss(s.paper_latency_ms, s.paper_latency_jitter_ms))) if s.paper_latency_jitter_ms else s.paper_latency_ms
        if s.paper_simulate_latency_sleep:
            await asyncio.sleep(latency_ms / 1000)

        # Exits must always be able to fully close a position, so reduce-only
        # orders are never rounded down to the lot size (dust would strand it).
        quantity = request.quantity if request.reduce_only else self._floor_to_step(request.quantity)
        if quantity <= 0:
            return self._reject(request, "quantity_below_lot_size", latency_ms)
        if request.reference_price <= 0:
            return self._reject(request, "invalid_reference_price", latency_ms)
        if not request.reduce_only and s.paper_min_order_notional and quantity * request.reference_price < s.paper_min_order_notional:
            return self._reject(request, "below_min_order_notional", latency_ms)
        # Exits must always be able to fill (an agent must be able to close);
        # random rejects only affect new entries.
        if not request.reduce_only and s.paper_reject_probability and rng.random() < s.paper_reject_probability:
            return self._reject(request, "simulated_exchange_reject", latency_ms)

        filled_quantity = quantity
        status = OrderStatus.FILLED
        if (
            not request.reduce_only
            and s.paper_partial_fill_probability
            and rng.random() < s.paper_partial_fill_probability
        ):
            fraction = rng.uniform(s.paper_partial_fill_min_fraction, 0.999)
            partial = self._floor_to_step(quantity * fraction)
            if partial > 0:
                filled_quantity, status = partial, OrderStatus.PARTIALLY_FILLED

        drift = (s.paper_latency_drift_bps_per_sec / 10_000) * (latency_ms / 1000) * rng.uniform(-1, 1)
        filled_price = slipped_price(
            request.reference_price * (1 + drift), request.side, reduce_only=request.reduce_only,
            bps=self.slippage_bps_for(request, quantity),
        )
        slippage_cost = abs(filled_price - request.reference_price) * filled_quantity

        fee_rate = fee_rate_for(request.order_kind, taker=self._fee_rate, maker=s.paper_maker_fee_rate)
        fee = filled_price * filled_quantity * fee_rate

        return ExecutionResult(
            client_order_id=request.client_order_id, status=status, filled_price=filled_price,
            filled_quantity=filled_quantity, fee=fee, slippage_cost=slippage_cost, latency_ms=latency_ms,
            raw_response={
                "simulated": True, "reference_price": request.reference_price, "order_kind": request.order_kind,
                "slippage_bps": self.slippage_bps_for(request, quantity), "requested_quantity": request.quantity,
            },
        )


def new_client_order_id(agent_id: str, decision_id: str, action: str = "entry") -> str:
    """Deterministic idempotency key: same (agent, decision, action) always yields the same order id, so a
    retried call cannot double-fill. The decision id is itself derived from (agent, candle) (see
    `decision_id_for`), so the key is stable across cycle retries, restarts and competing workers."""
    return f"{agent_id}:{decision_id}" if action == "entry" else f"{agent_id}:{decision_id}:{action}"
