"""Paper execution adapter (spec sections 5/19).

Simulates fees, slippage, and latency — it must NEVER assume zero
transaction costs. This adapter must NEVER send a real network request to
an exchange; that invariant is enforced by a unit test (see
tests/test_execution_safety.py) that patches out httpx entirely and asserts
no call is made.
"""
from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.models.enums import ExecutionVenue, OrderStatus, Side

logger = get_logger(__name__)

# Idempotency guard: client_order_ids we have already filled in this process.
# A durable, DB-backed guard (unique constraint on Order.client_order_id) is
# the real safety net; this in-memory set catches same-process retries fast.
_SEEN_ORDER_IDS: set[str] = set()


class PaperExecutionAdapter(ExecutionEngine):
    venue = ExecutionVenue.PAPER

    def __init__(self) -> None:
        settings = get_settings()
        self._fee_rate = settings.paper_fee_rate
        self._slippage_bps = settings.paper_slippage_bps
        self._latency_ms = settings.paper_latency_ms

    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        if request.client_order_id in _SEEN_ORDER_IDS:
            logger.warning("paper_execution.duplicate_order_id_blocked", client_order_id=request.client_order_id)
            return ExecutionResult(
                client_order_id=request.client_order_id,
                status=OrderStatus.FAILED,
                filled_price=None,
                filled_quantity=0.0,
                fee=0.0,
                slippage_cost=0.0,
                latency_ms=0,
                raw_response={},
                rejection_reason="duplicate_client_order_id",
            )
        _SEEN_ORDER_IDS.add(request.client_order_id)

        await asyncio.sleep(self._latency_ms / 1000)

        slippage_direction = 1 if request.side == Side.LONG else -1
        slippage_pct = (self._slippage_bps / 10_000) * slippage_direction
        filled_price = request.reference_price * (1 + slippage_pct)
        slippage_cost = abs(filled_price - request.reference_price) * request.quantity

        notional = filled_price * request.quantity
        fee = notional * self._fee_rate

        return ExecutionResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.FILLED,
            filled_price=filled_price,
            filled_quantity=request.quantity,
            fee=fee,
            slippage_cost=slippage_cost,
            latency_ms=self._latency_ms,
            raw_response={"simulated": True, "reference_price": request.reference_price},
        )


def new_client_order_id(agent_id: str, decision_id: str) -> str:
    """Deterministic idempotency key: same (agent, decision) always yields
    the same order id, so a retried call cannot double-fill."""
    return f"{agent_id}:{decision_id}"
