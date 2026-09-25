"""Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close look-ahead.

    bar N close: signal -> persisted PENDING order (no fill, no position, no cash movement)
    bar N+1:     filled at N+1's OPEN (+ slippage), managed on N+1's own range, exits likewise."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import OrderStatus, Side
from app.models.trading import Order, Position, Trade
from tests.helpers_agents import MINUTE, T0, cycle, make_agents, make_context, make_dna

SLIP = 2.0005 / 10_000   # base 2 bps + 0.5 bps per $10k of (tiny) notional


async def _orders(db):
    return (await db.execute(select(Order).order_by(Order.created_at))).scalars().all()


async def _pos(db):
    return (await db.execute(select(Position))).scalars().all()


async def test_signal_creates_a_pending_order_and_no_position_or_cash_movement(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    assert eng.fill_timing == "next_open"
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.PENDING and order.signal_candle_open_time == T0 + MINUTE
    assert order.filled_price is None and order.approved_notional == pytest.approx(10.0)
    assert order.intent["atr"] == 0.5 and order.intent["entry_regime"] == "TREND_UP"
    assert await _pos(db_session) == []
    await db_session.refresh(agent)
    assert agent.balance == 100.0 and agent.trade_count == 0 and agent.fees_paid == 0.0
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.order_id == order.id


async def test_pending_entry_fills_at_the_next_bars_open_not_the_signal_close(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    # next bar opens at 101 (a gap up from the 100 signal close), trades 100.5-103, closes 102
    await cycle(db_session, eng, make_context(2, 102.0, open_=101.0, high=103.0, low=100.5, rsi=50.0), prev=None)
    (order,) = await _orders(db_session)
    (pos,) = await _pos(db_session)
    assert order.status == OrderStatus.FILLED
    assert order.filled_price == pytest.approx(101.0 * (1 + SLIP), rel=1e-4)        # the OPEN plus slippage ...
    assert order.filled_price != pytest.approx(100.0, abs=0.5)                        # ... never the signal-bar close
    assert pos.entry_price == pytest.approx(order.filled_price) and pos.is_open and pos.side == Side.LONG
    assert pos.opened_at.timestamp() * 1000 == T0 + 2 * MINUTE                        # the fill bar's open time
    assert pos.entry_candle_open_time == T0 + 2 * MINUTE
    # the quantity is the approved NOTIONAL converted at the fill price
    assert pos.quantity == pytest.approx(10.0 / 101.0, abs=0.011)
    assert pos.last_processed_open_time == T0 + 2 * MINUTE                            # managed on its own fill bar
    await db_session.refresh(agent)
    assert agent.trade_count == 1 and agent.fees_paid == pytest.approx(order.fee) and agent.balance == pytest.approx(100.0 - order.fee)


async def test_the_position_is_managed_on_its_own_fill_bar(db_session):
    """Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the very bar the entry filled."""
    await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(2, 96.0, open_=101.0, high=101.5, low=95.0, rsi=50.0))
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert trade.exit_reason == "stop_loss" and trade.net_pnl < 0
    assert (await _pos(db_session))[0].is_open is False


async def test_signal_exit_is_pending_and_executes_at_the_next_open(db_session):
    await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(2, 100.5, open_=100.2, high=100.8, low=100.1, rsi=50.0))   # filled, holding
    (pos,) = await _pos(db_session)
    assert pos.is_open
    await cycle(db_session, eng, make_context(3, 100.4, open_=100.5, high=100.7, low=100.2, rsi=30.0))   # exit SIGNAL on the close
    await db_session.refresh(pos)
    assert pos.is_open and pos.pending_exit_signal_time == T0 + 3 * MINUTE                              # pending, not executed
    assert (await db_session.execute(select(Trade))).scalars().all() == []
    await cycle(db_session, eng, make_context(4, 99.0, open_=105.0, high=105.2, low=98.9, rsi=50.0))    # next bar opens at 105
    await db_session.refresh(pos)
    (trade,) = (await db_session.execute(select(Trade))).scalars().all()
    assert not pos.is_open and trade.exit_reason == "exit_rules"
    assert trade.exit_price == pytest.approx(105.0 * (1 - SLIP), rel=1e-4)                              # the OPEN, not the signal close


async def test_pending_entry_is_cancelled_when_entries_are_halted_at_the_fill_bar(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(2, 100.0, rsi=50.0), trading_halt_override="kill_switch")
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.CANCELLED and order.rejection_reason.startswith("entries_halted")
    assert await _pos(db_session) == []
    await db_session.refresh(agent)
    assert agent.balance == 100.0 and agent.fees_paid == 0.0


async def test_a_pending_entry_that_was_not_filled_on_the_next_bar_is_never_filled_late(db_session):
    await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(3, 100.0, rsi=50.0))            # bar 2 never happened for this worker
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.CANCELLED and order.rejection_reason == "expired_unfilled"
    assert await _pos(db_session) == []


async def test_stale_pending_orders_of_agents_outside_the_loop_are_expired(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    agent.status = __import__("app.models.enums", fromlist=["AgentStatus"]).AgentStatus.PAUSED   # no longer processed
    await db_session.commit()
    await cycle(db_session, eng, make_context(4, 100.0, rsi=50.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.CANCELLED and order.rejection_reason == "expired_unfilled"


async def test_rejected_pending_entry_at_the_open_is_recorded_not_opened(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_reject_probability", 1.0)
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(2, 100.0, rsi=50.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.FAILED and order.rejection_reason == "simulated_exchange_reject"
    assert await _pos(db_session) == []
    await db_session.refresh(agent)
    assert agent.balance == 100.0


async def test_min_notional_rejects_a_sub_ten_dollar_order(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 10.0)
    from app.schemas.strategy_dna import PositionSizing

    await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))   # 5% x $100 equity = a $5 order, below the $10 minimum
    await cycle(db_session, eng, make_context(2, 100.0, rsi=50.0))
    # refused at decision time (see test_min_notional_decision_time.py); the adapter's own check at the fill is the
    # backstop, covered in test_paper_execution_v2.py
    assert await _orders(db_session) == []


def test_production_realism_defaults_are_not_silently_disabled():
    from app.core.config import Settings

    f = Settings.model_fields
    assert f["paper_min_order_notional"].default == 10.0            # Hyperliquid's real minimum
    assert f["paper_reject_probability"].default > 0
    assert f["paper_partial_fill_probability"].default > 0
    assert f["paper_latency_drift_bps_per_sec"].default > 0
    assert f["paper_fill_timing"].default == "next_open"
    with pytest.raises(ValueError):
        Settings(paper_fill_timing="whenever")
