"""Execution engine abstraction (spec section 19).

Every trading mode (paper/shadow/live) implements the same interface so the
rest of the system (risk engine, PnL engine, agent lifecycle) is written
once and never branches on TRADING_MODE directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.enums import ExecutionVenue, OrderStatus, Side


@dataclass
class ExecutionRequest:
    client_order_id: str
    agent_id: str
    symbol: str
    side: Side
    quantity: float
    leverage: float
    reference_price: float
    # Exits are reduce-only and carry the kind of trigger that produced them,
    # because a stop/liquidation fills worse than a resting take-profit limit:
    #   market (entries, signal exits) | stop | take_profit | liquidation
    reduce_only: bool = False
    order_kind: str = "market"


@dataclass
class ExecutionResult:
    client_order_id: str
    status: OrderStatus
    filled_price: float | None
    filled_quantity: float
    fee: float
    slippage_cost: float
    latency_ms: int
    raw_response: dict
    rejection_reason: str | None = None


class ExecutionEngine(ABC):
    venue: ExecutionVenue

    @abstractmethod
    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        """Submits an order and returns its fill result. Implementations
        MUST be idempotent on `client_order_id` — resubmitting the same id
        after a network retry must never produce a second fill."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any network resources (no-op for pure-simulation engines)."""
        return None
