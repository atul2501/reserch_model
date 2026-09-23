"""Stops / take-profit / trailing in the WORKER (spec phase 10). Pure bar
evaluation plus end-to-end decision-loop behaviour. Assumptions documented in
app/agents/position_manager.py are pinned here."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.position_manager import Bar, PositionLevels, advance_extremes, evaluate_bar, trailing_is_active
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import Side
from app.models.trading import Order, Position, Trade
from app.schemas.strategy_dna import StopLossConfig, TakeProfitConfig, TrailingStopConfig
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


def L(**kw):
    base = dict(side=Side.LONG, entry_price=100.0, stop_loss_price=98.0, take_profit_price=104.0, trailing_distance=None,
                trailing_activation_pct=0.0, trailing_active=False, peak_price=100.0, trough_price=100.0, liquidation_price=None)
    base.update(kw)
    return PositionLevels(**base)


# ---- pure bar evaluation -------------------------------------------------- #
def test_stop_hit_long_and_short():
    assert evaluate_bar(L(), Bar(100, 101, 97.5, 99)).exit_reason == "stop_loss"
    s = evaluate_bar(L(side=Side.SHORT, stop_loss_price=102.0, take_profit_price=96.0), Bar(100, 102.5, 99, 101))
    assert s.exit_reason == "stop_loss" and s.trigger_price == 102.0


def test_take_profit_hit():
    t = evaluate_bar(L(), Bar(100, 104.5, 99.5, 104))
    assert t.exit_reason == "take_profit" and t.order_kind == "take_profit" and t.reference_price == 104.0


def test_bar_touching_both_stop_and_tp_takes_the_stop_conservatively():
    t = evaluate_bar(L(), Bar(100, 105, 97, 101))
    assert t.exit_reason == "stop_loss"


def test_gap_through_stop_fills_at_the_open_not_the_level():
    t = evaluate_bar(L(), Bar(95.0, 96, 94, 95))       # opened 3 below the stop
    assert t.exit_reason == "stop_loss" and t.reference_price == 95.0 and t.trigger_price == 98.0


def test_gap_through_take_profit_gets_no_price_improvement():
    t = evaluate_bar(L(), Bar(108.0, 109, 107, 108))
    assert t.exit_reason == "take_profit" and t.reference_price == 104.0


def test_nothing_triggers_inside_the_range():
    assert evaluate_bar(L(), Bar(100, 103, 99, 101)) is None


def test_trailing_stop_trails_prior_peak_only():
    lv = L(stop_loss_price=90.0, take_profit_price=None, trailing_distance=2.0, peak_price=110.0)
    assert evaluate_bar(lv, Bar(109, 109.5, 107.5, 108)).exit_reason == "trailing_stop"    # 110-2=108, low 107.5 <= 108
    assert evaluate_bar(lv, Bar(110, 112, 108.5, 111)) is None                             # bar's own new high 112 not used yet
    peak, trough, active = advance_extremes(lv, Bar(110, 112, 108.5, 111))
    assert peak == 112 and active is True


def test_trailing_arms_only_after_activation_pct():
    lv = L(stop_loss_price=None, take_profit_price=None, trailing_distance=1.0, trailing_activation_pct=2.0, peak_price=101.0)
    assert trailing_is_active(lv) is False
    assert evaluate_bar(lv, Bar(100, 100.5, 99, 99.5)) is None                 # not armed -> no trailing exit
    assert trailing_is_active(L(trailing_distance=1.0, trailing_activation_pct=2.0, peak_price=102.5)) is True


def test_trailing_short_mirrors():
    lv = L(side=Side.SHORT, stop_loss_price=None, take_profit_price=None, trailing_distance=2.0, trough_price=90.0)
    assert evaluate_bar(lv, Bar(91, 92.5, 90.5, 92)).exit_reason == "trailing_stop"        # 90+2=92, high 92.5 >= 92


def test_liquidation_is_treated_as_the_first_adverse_level_when_nearest():
    t = evaluate_bar(L(stop_loss_price=90.0, liquidation_price=97.0), Bar(100, 101, 96.5, 97))
    assert t.exit_reason == "liquidation" and t.order_kind == "liquidation"


# ---- end-to-end through the decision loop -------------------------------- #
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "paper_latency_ms", 0)
    monkeypatch.setattr(get_settings(), "paper_latency_jitter_ms", 0)


async def _open(db, dna, close=100.0):
    (agent,) = await make_agents(db, [dna])
    eng = PaperExecutionAdapter()
    ctx = make_context(1, close, rsi=65.0, atr=0.5)
    await cycle(db, eng, ctx)
    pos = (await db.execute(select(Position).where(Position.agent_id == agent.id))).scalar_one()
    return agent, eng, ctx, pos


async def test_worker_applies_stop_loss_from_dna(db_session):
    dna = make_dna(stop_loss=StopLossConfig(method="atr_multiple", value=2.0), take_profit=TakeProfitConfig(enabled=False))
    agent, eng, ctx1, pos = await _open(db_session, dna)
    assert pos.stop_loss_price == pytest.approx(pos.entry_price - 1.0)          # 2 x ATR(0.5)
    ctx2 = make_context(2, 99.0, rsi=65.0, high=100.2, low=98.0, open_=99.9)    # stop at ~99.0 breached
    await cycle(db_session, eng, ctx2, ctx1)
    await db_session.refresh(pos)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert pos.is_open is False and trade.exit_reason == "stop_loss" and trade.net_pnl < 0
    exit_order = (await db_session.execute(select(Order).where(Order.reduce_only.is_(True)))).scalar_one()
    assert exit_order.order_kind == "stop" and trade.exit_order_id == exit_order.id


async def test_worker_applies_take_profit_from_dna(db_session):
    dna = make_dna(stop_loss=StopLossConfig(method="atr_multiple", value=2.0), take_profit=TakeProfitConfig(method="risk_reward_multiple", value=2.0))
    agent, eng, ctx1, pos = await _open(db_session, dna)
    assert pos.take_profit_price == pytest.approx(pos.entry_price + 2.0)       # 2R with a 1.0 stop distance
    ctx2 = make_context(2, 102.5, rsi=65.0, high=103.0, low=100.0, open_=100.5)
    await cycle(db_session, eng, ctx2, ctx1)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert trade.exit_reason == "take_profit" and trade.net_pnl > 0
    assert trade.exit_price == pytest.approx(pos.take_profit_price)             # limit fill: no slippage


async def test_worker_trailing_stop_arms_then_exits(db_session):
    dna = make_dna(stop_loss=StopLossConfig(method="fixed_pct", value=10.0), take_profit=TakeProfitConfig(enabled=False),
                   trailing_stop=TrailingStopConfig(enabled=True, activation_pct=1.0, trail_pct=1.0))
    agent, eng, ctx, pos = await _open(db_session, dna)
    assert pos.trailing_stop_distance == pytest.approx(pos.entry_price * 0.01)
    prev = ctx
    # Rally +3%: arms trailing, peak advances.
    ctx2 = make_context(2, 103.0, rsi=65.0, high=103.2, low=100.5, open_=100.5)
    await cycle(db_session, eng, ctx2, prev)
    await db_session.refresh(pos)
    assert pos.is_open and pos.trailing_active and pos.peak_price == pytest.approx(103.2)
    # Pullback through peak - 1% (~102.17): exit via trailing stop.
    ctx3 = make_context(3, 102.0, rsi=65.0, high=103.0, low=101.9, open_=102.9)
    await cycle(db_session, eng, ctx3, ctx2)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert trade.exit_reason == "trailing_stop" and trade.net_pnl > 0


async def test_gap_down_fills_at_the_open_in_the_worker(db_session):
    dna = make_dna(stop_loss=StopLossConfig(method="atr_multiple", value=2.0), take_profit=TakeProfitConfig(enabled=False))
    agent, eng, ctx1, pos = await _open(db_session, dna)
    ctx2 = make_context(2, 94.0, rsi=65.0, high=95.0, low=93.5, open_=95.0)     # gaps 4 below the stop
    await cycle(db_session, eng, ctx2, ctx1)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price < pos.stop_loss_price - 2.0                          # filled near 95 (open), not at ~99
