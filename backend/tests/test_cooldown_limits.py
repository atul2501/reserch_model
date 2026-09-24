"""Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.trading import Position
from app.schemas.strategy_dna import CooldownConfig, StopLossConfig, TakeProfitConfig
from tests.helpers_agents import MINUTE, cycle, make_agents, make_context, make_dna

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


def _dna(**kw):
    return make_dna(stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(enabled=False), **kw)


async def _trade_round_trip(db, eng, i, prev, *, exit_close=101.0):
    """entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx."""
    entry = make_context(i, 100.0, rsi=65.0)
    await cycle(db, eng, entry, prev)
    exit_ = make_context(i + 1, exit_close, rsi=30.0)
    await cycle(db, eng, exit_, entry)
    return exit_


async def test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(db_session):
    (agent,) = await make_agents(db_session, [_dna(cooldown=CooldownConfig(bars_after_loss=3, bars_after_win=0))])
    eng = PaperExecutionAdapter()
    last = await _trade_round_trip(db_session, eng, 1, None, exit_close=90.0)    # losing trade closes on bar 2
    await db_session.refresh(agent)
    assert agent.cooldown_until is not None
    # bars 3 and 4: still cooling down (3 bars after the bar-2 close => free from bar 5's open)
    for i in (3, 4):
        ctx = make_context(i, 100.0, rsi=65.0)
        await cycle(db_session, eng, ctx, last)
        last = ctx
    decs = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id).order_by(Decision.market_candle_open_time))).scalars().all()
    assert [d.risk_reasoning.get("skipped") for d in decs if d.market_candle_open_time in (make_context(3, 1).candle_open_time, make_context(4, 1).candle_open_time)] == ["cooldown_active"] * 2
    assert (await db_session.execute(select(Position).where(Position.agent_id == agent.id, Position.is_open.is_(True)))).first() is None
    # After the cooldown the agent may trade again.
    ctx6 = make_context(6, 100.0, rsi=65.0)
    await cycle(db_session, eng, ctx6, last)
    assert (await db_session.execute(select(Position).where(Position.agent_id == agent.id, Position.is_open.is_(True)))).first() is not None


async def test_cooldown_is_counted_in_bars_of_the_configured_timeframe(db_session):
    (agent,) = await make_agents(db_session, [_dna(cooldown=CooldownConfig(bars_after_loss=2, bars_after_win=2))])
    eng = PaperExecutionAdapter()
    await _trade_round_trip(db_session, eng, 1, None, exit_close=90.0)
    await db_session.refresh(agent)
    exit_bar_open = make_context(2, 1).candle_open_time
    # an exit in bar X blocks entry signals for bars X .. X+N-1 (same rule as the backtest)
    assert agent.cooldown_until.timestamp() * 1000 == pytest.approx(exit_bar_open + 2 * MINUTE, abs=1)


async def test_no_cooldown_configured_allows_immediate_reentry(db_session):
    (agent,) = await make_agents(db_session, [_dna()])
    eng = PaperExecutionAdapter()
    last = await _trade_round_trip(db_session, eng, 1, None)
    await cycle(db_session, eng, make_context(3, 100.0, rsi=65.0), last)
    assert (await db_session.execute(select(Position).where(Position.agent_id == agent.id, Position.is_open.is_(True)))).first() is not None


async def test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day(db_session):
    (agent,) = await make_agents(db_session, [_dna(max_trades_per_day=2)])
    eng = PaperExecutionAdapter()
    last = None
    for i in (1, 3, 5):                       # three entry attempts on the same UTC day
        last = await _trade_round_trip(db_session, eng, i, last)
    await db_session.refresh(agent)
    assert agent.trade_count == 2 and agent.daily_trade_count == 2
    decs = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id, Decision.risk_reasoning["skipped"].as_string() == "max_trades_per_day_reached"))).scalars().all()
    assert len(decs) == 1

    # Same agent, next UTC day: the counter resets and it may trade again.
    from tests.helpers_agents import T0
    day_bars = 24 * 60
    next_day = make_context(day_bars + 10, 100.0, rsi=65.0)
    assert (next_day.candle_open_time - T0) >= 86_400_000 - 3_600_000
    await cycle(db_session, eng, next_day, last)
    await db_session.refresh(agent)
    assert agent.daily_trade_count == 1 and agent.trade_count == 3
