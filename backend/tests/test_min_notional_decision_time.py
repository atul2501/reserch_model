"""Minimum order notional is enforced at DECISION time, not discovered a bar later at the fill.

Observed in production paper mode: 3,469 of ~4,900 entry orders (~70%) were approved by the Risk Engine, persisted as
PENDING, then FAILED at the next bar's open with `below_min_order_notional` (approved notional avg $6.35 vs the $10
exchange minimum on $100 agents). Each left a FAILED order row plus a Decision row mislabelled REJECTED with no reason.

The doomed order must never be created; the Decision must say why. P&L is unchanged (those orders never filled).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import OrderStatus, RiskDecision
from app.models.trading import Order
from app.schemas.strategy_dna import PositionSizing
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


async def _orders(db):
    return (await db.execute(select(Order))).scalars().all()


async def _decisions(db):
    return (await db.execute(select(Decision))).scalars().all()


async def test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 10.0)
    (agent,) = await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))   # 5% x $100 = a $5 order

    assert await _orders(db_session) == []                      # no PENDING (and later FAILED) order is ever created
    (decision,) = await _decisions(db_session)
    assert decision.risk_decision == RiskDecision.REJECTED
    assert decision.order_id is None
    assert "below_min_order_notional" in decision.risk_reasoning["reasons"]
    await db_session.refresh(agent)
    assert agent.balance == 100.0 and agent.trade_count == 0 and agent.daily_trade_count == 0


async def test_entry_at_the_minimum_still_creates_a_pending_order(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 10.0)
    await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.1))])   # exactly $10
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.PENDING


async def test_the_minimum_can_be_disabled_like_at_the_adapter(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 0.0)
    await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.PENDING


def test_check_mirrors_the_adapter_lot_rounding(monkeypatch):
    from app.execution.sizing import below_min_order_notional

    s = get_settings()
    monkeypatch.setattr(s, "paper_min_order_notional", 10.0)
    monkeypatch.setattr(s, "paper_quantity_step", 0.01)
    assert below_min_order_notional(9.99, 100.0) is True
    assert below_min_order_notional(10.0, 100.0) is False
    assert below_min_order_notional(10.009, 100.0) is False      # floors to 0.10 lots -> $10.00
    assert below_min_order_notional(10.5, 107.0) is True         # 0.098 -> floors to 0.09 lots -> $9.63
    assert below_min_order_notional(0.0, 100.0) is True
    monkeypatch.setattr(s, "paper_min_order_notional", 0.0)
    assert below_min_order_notional(0.01, 100.0) is False


async def test_backtest_currently_agrees_with_below_min_order_notional_at_a_real_nonzero_threshold(monkeypatch):
    """Initiative 1 (LIVE_BACKTEST_PARITY_PLAN.md), Phase 1.1 - characterization only, no
    production code changed.

    `app.backtesting.engine.run_backtest` reimplements the minimum-notional check inline
    (`qty * next_open < settings.paper_min_order_notional`, after its own lot-step rounding)
    instead of calling the shared `below_min_order_notional()` used everywhere else (the paper
    adapter, and decision_loop.py's decision-time check above). This is a real, if narrow,
    duplication (see LIVE_BACKTEST_PARITY_PLAN.md SS3-4) - but `test_live_backtest_parity.py`'s
    own `deterministic` fixture zeroes `paper_min_order_notional` before every live-vs-backtest
    comparison, so NO existing test exercises this path at a real, non-zero threshold in either
    direction. This test establishes - against the CURRENT, unmodified implementation - that
    backtest's inline logic already agrees with the shared function at both boundaries, using
    a real backtest run (not a synthetic notional) as the evidence. It must remain passing,
    unmodified in its assertions, as the reference point for Phase 1.2's proposed change (swapping
    the inline check for a direct call to below_min_order_notional)."""
    from app.backtesting.engine import run_backtest
    from app.execution.sizing import below_min_order_notional
    from tests.test_backtest_parity import KW, candles, ema_cross_dna

    settings = get_settings()
    c = candles(seed=3)                 # same fixture test_backtest_parity.py's own tests use with this DNA
    dna = ema_cross_dna(5, 20)          # proven to trade under KW (test_declared_indicator_periods_drive_backtest_behaviour)
    # Slippage fully zeroed HERE ONLY (a local kwarg override, KW itself is untouched, PLUS the
    # size-aware impact component, which is a Settings field, not a run_backtest parameter) so
    # BacktestTrade.entry_price (the post-slippage fill) is bit-identical to `next_open` (the
    # pre-slippage reference price the engine's own min-notional gate actually checks against) -
    # otherwise even a few bps of slippage can shift which side of an exact boundary a trade falls
    # on, which would be a bug in this test's arithmetic, not in the engine.
    monkeypatch.setattr(settings, "paper_slippage_impact_bps_per_10k", 0.0)
    kw = {**KW, "slippage_bps": 0.0}

    baseline = run_backtest(c, dna, **kw)
    assert baseline.trades, "scenario must actually trade for this test to mean anything"
    first = baseline.trades[0]
    first_notional = first.entry_price * first.quantity

    # ---- order notional AT the configured minimum (inclusive boundary): must still open ----
    monkeypatch.setattr(settings, "paper_min_order_notional", first_notional)
    at_minimum = run_backtest(c, dna, **kw)
    assert at_minimum.trades, "a notional exactly AT the minimum must not be rejected"
    assert at_minimum.trades[0].entry_index == first.entry_index
    assert at_minimum.trades[0].entry_price == pytest.approx(first.entry_price)
    assert at_minimum.trades[0].quantity == pytest.approx(first.quantity)
    # the shared reference function, given the same notional/price, agrees this is NOT below minimum
    assert below_min_order_notional(first_notional, first.entry_price) is False

    # ---- order notional BELOW the configured minimum: every entry must be rejected ----
    monkeypatch.setattr(settings, "paper_min_order_notional", first_notional * 1_000)
    starved = run_backtest(c, dna, **kw)
    assert starved.trades == [], "a minimum far above any attainable notional must block every entry, not just the first"
    # the shared reference function, given the same (now sub-minimum) notional/price, agrees
    assert below_min_order_notional(first_notional, first.entry_price) is True
