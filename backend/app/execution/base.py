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

    @property
    def fill_timing(self) -> str:
        """`immediate`: an order is filled when submitted (shadow/live: against the real book, now).
        `next_open`: an order decided on the close of bar N is filled at the OPEN of bar N+1 (paper research model)."""
        return "immediate"

    # --- rollback-aware idempotency -------------------------------------------------------------
    # An order id is "claimed" when an order is submitted, BEFORE the database transaction that records it
    # commits. If that transaction (an agent's savepoint, or the whole cycle) rolls back, the id must be
    # released again; otherwise the deterministic retry of the same candle would be refused as a duplicate
    # (silently suppressing entries and, worse, stranding exits). Ids claimed in a transaction that
    # commits stay claimed for good.
    def _seen_ids(self) -> set[str]:
        return set()  # engines with an in-process guard override this

    def _track(self, agent_id: str, client_order_id: str) -> None:
        self.__dict__.setdefault("_uncommitted", {}).setdefault(agent_id, set()).add(client_order_id)

    def discard_uncommitted(self, agent_id: str | None = None) -> None:
        """The transaction holding these orders rolled back: release their ids (one agent, or every agent)."""
        tracked: dict[str, set[str]] = self.__dict__.setdefault("_uncommitted", {})
        agents = list(tracked) if agent_id is None else [agent_id]
        for a in agents:
            self._seen_ids().difference_update(tracked.pop(a, set()))

    def commit_cycle(self) -> None:
        """The cycle's transaction committed: the claimed ids are now durable (DB unique constraint)."""
        self.__dict__.setdefault("_uncommitted", {}).clear()

    @abstractmethod
    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        """Submits an order and returns its fill result. Implementations
        MUST be idempotent on `client_order_id` — resubmitting the same id
        after a network retry must never produce a second fill."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any network resources (no-op for pure-simulation engines)."""
        return None
