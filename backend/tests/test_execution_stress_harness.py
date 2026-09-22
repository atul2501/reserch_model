"""Execution-quality stress testing: StressedExecutionAdapter injects
partial fills, missed fills, and extra latency on top of the real
PaperExecutionAdapter, exercising order statuses (PARTIALLY_FILLED,
CANCELLED) the schema has always supported but nothing ever produced."""
from __future__ import annotations

import random

import pytest

from app.backtesting.execution_stress_harness import (
    StressedExecutionAdapter,
    run_execution_stress_scenario,
)
from app.execution.base import ExecutionRequest
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import OrderStatus, Side


def _requests(n: int) -> list[ExecutionRequest]:
    return [
        ExecutionRequest(
            client_order_id=f"stress-{i}-{random.random()}",
            agent_id="agent-1",
            symbol="SOL",
            side=Side.LONG,
            quantity=1.0,
            leverage=1.0,
            reference_price=100.0,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_plain_paper_adapter_baseline_always_fills():
    adapter = PaperExecutionAdapter()
    result = await run_execution_stress_scenario(_requests(10), adapter)
    assert result.filled_count == 10
    assert result.partially_filled_count == 0
    assert result.missed_count == 0
    assert result.fill_rate == 1.0


@pytest.mark.asyncio
async def test_missed_fill_probability_produces_cancelled_orders():
    adapter = StressedExecutionAdapter(missed_fill_probability=1.0, rng=random.Random(1))
    result = await run_execution_stress_scenario(_requests(5), adapter)
    assert result.missed_count == 5
    assert result.filled_count == 0
    assert all(r.status == OrderStatus.CANCELLED for r in result.results)


@pytest.mark.asyncio
async def test_partial_fill_probability_produces_partially_filled_orders_with_reduced_quantity():
    adapter = StressedExecutionAdapter(partial_fill_probability=1.0, partial_fill_min_pct=0.3, rng=random.Random(2))
    requests = _requests(5)
    result = await run_execution_stress_scenario(requests, adapter)
    assert result.partially_filled_count == 5
    for req, res in zip(requests, result.results):
        assert res.status == OrderStatus.PARTIALLY_FILLED
        assert 0.0 < res.filled_quantity < req.quantity


@pytest.mark.asyncio
async def test_extra_latency_is_added_on_top_of_base_latency():
    baseline = await run_execution_stress_scenario(_requests(3), PaperExecutionAdapter())
    stressed_adapter = StressedExecutionAdapter(extra_latency_ms=500, rng=random.Random(3))
    stressed = await run_execution_stress_scenario(_requests(3), stressed_adapter)
    assert stressed.avg_latency_ms == pytest.approx(baseline.avg_latency_ms + 500, abs=1)


@pytest.mark.asyncio
async def test_stressed_adapter_never_bypasses_the_real_fee_and_slippage_simulation():
    """A filled order under stress must still carry the same fee/slippage
    model as plain PaperExecutionAdapter — stress adds failure modes on
    top, it never removes the underlying cost simulation."""
    adapter = StressedExecutionAdapter(missed_fill_probability=0.0, partial_fill_probability=0.0, rng=random.Random(4))
    result = await run_execution_stress_scenario(_requests(3), adapter)
    assert all(r.status == OrderStatus.FILLED for r in result.results)
    assert all(r.fee > 0 for r in result.results)
