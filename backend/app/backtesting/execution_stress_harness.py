"""Execution-quality stress testing: delay, partial fills, and missed
fills, run through the real `ExecutionEngine` interface rather than
`run_backtest`'s inlined fee/slippage math.

`run_backtest` doesn't use `ExecutionEngine` at all — it's a second,
parallel cost model, so market/parameter stress (adversarial.py) and
execution stress (this module) are deliberately two separate code paths
rather than unifying `run_backtest` onto the adapter interface (a much
larger refactor touching walk-forward and every existing backtest caller).
This harness's job is narrower and more honest about it: it proves
`PARTIALLY_FILLED`/`FAILED`/`CANCELLED` — statuses `ExecutionResult`'s
schema has always supported but `PaperExecutionAdapter` never produced —
actually get exercised under stress, and reports fill-quality stats. It
does not simulate a strategy's P&L under execution stress; pairing that
with a specific DNA is future work.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import ExecutionVenue, OrderStatus


class StressedExecutionAdapter(ExecutionEngine):
    """Wraps PaperExecutionAdapter and stochastically injects partial
    fills, missed fills, and extra latency on top of its normal fee/
    slippage simulation — never bypasses it, only adds failure modes on
    top."""

    venue = ExecutionVenue.PAPER

    def __init__(
        self,
        *,
        partial_fill_probability: float = 0.0,
        partial_fill_min_pct: float = 0.3,
        missed_fill_probability: float = 0.0,
        extra_latency_ms: int = 0,
        rng: random.Random | None = None,
        inner: ExecutionEngine | None = None,
    ) -> None:
        self._inner = inner or PaperExecutionAdapter()
        self._partial_fill_probability = partial_fill_probability
        self._partial_fill_min_pct = partial_fill_min_pct
        self._missed_fill_probability = missed_fill_probability
        self._extra_latency_ms = extra_latency_ms
        self._rng = rng or random.Random(0)

    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        if self._rng.random() < self._missed_fill_probability:
            return ExecutionResult(
                client_order_id=request.client_order_id,
                status=OrderStatus.CANCELLED,
                filled_price=None,
                filled_quantity=0.0,
                fee=0.0,
                slippage_cost=0.0,
                latency_ms=self._extra_latency_ms,
                raw_response={"simulated": True, "stress": "missed_fill"},
                rejection_reason="simulated_missed_fill",
            )

        result = await self._inner.submit_order(request)
        result.latency_ms += self._extra_latency_ms

        if result.status == OrderStatus.FILLED and self._rng.random() < self._partial_fill_probability:
            fill_pct = self._rng.uniform(self._partial_fill_min_pct, 1.0)
            return ExecutionResult(
                client_order_id=result.client_order_id,
                status=OrderStatus.PARTIALLY_FILLED,
                filled_price=result.filled_price,
                filled_quantity=result.filled_quantity * fill_pct,
                fee=result.fee * fill_pct,
                slippage_cost=result.slippage_cost * fill_pct,
                latency_ms=result.latency_ms,
                raw_response={**result.raw_response, "stress": "partial_fill", "fill_pct": fill_pct},
            )
        return result


@dataclass
class ExecutionStressResult:
    total_orders: int
    filled_count: int
    partially_filled_count: int
    missed_count: int
    avg_latency_ms: float
    results: list[ExecutionResult] = field(default_factory=list)

    @property
    def fill_rate(self) -> float:
        return self.filled_count / self.total_orders if self.total_orders else 0.0

    @property
    def missed_rate(self) -> float:
        return self.missed_count / self.total_orders if self.total_orders else 0.0


async def run_execution_stress_scenario(
    requests: list[ExecutionRequest], adapter: ExecutionEngine
) -> ExecutionStressResult:
    """Submits every request through `adapter` sequentially and aggregates
    fill-quality stats. Use a `StressedExecutionAdapter` to see the effect
    of degraded execution conditions vs. a plain `PaperExecutionAdapter` as
    a baseline comparison."""
    results = [await adapter.submit_order(r) for r in requests]
    filled = sum(1 for r in results if r.status == OrderStatus.FILLED)
    partial = sum(1 for r in results if r.status == OrderStatus.PARTIALLY_FILLED)
    missed = sum(1 for r in results if r.status in (OrderStatus.CANCELLED, OrderStatus.FAILED))
    avg_latency = (sum(r.latency_ms for r in results) / len(results)) if results else 0.0
    return ExecutionStressResult(
        total_orders=len(results),
        filled_count=filled,
        partially_filled_count=partial,
        missed_count=missed,
        avg_latency_ms=avg_latency,
        results=results,
    )
