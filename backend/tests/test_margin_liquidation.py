"""Margin & liquidation (spec phase 9): explicit margin model; leverage is a
real exposure multiplier; agents are liquidated; no unlimited notional."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.analytics.pnl_engine import compute_liquidation_price
from app.core.config import get_settings
from app.execution.margin import margin_state
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import AgentStatus, Side
from app.models.trading import Order, Position, Trade
from app.schemas.strategy_dna import PositionSizing, RiskProfile, StopLossConfig, TakeProfitConfig
from tests.helpers_agents import cycle, make_agents, make_context, make_dna

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills

MMR = 0.025


def test_margin_state_flat_account():
    m = margin_state(balance=100.0, maintenance_margin_rate=MMR)
    assert (m.equity, m.used_margin, m.available_margin, m.liquidation_price, m.liquidatable) == (100.0, 0.0, 100.0, None, False)


def test_margin_state_with_position_fields():
    m = margin_state(balance=100.0, maintenance_margin_rate=MMR, side=Side.LONG, quantity=2.0, entry_price=100.0,
                     mark_price=95.0, initial_margin=40.0)
    assert m.unrealized_pnl == pytest.approx(-10.0)
    assert m.equity == pytest.approx(90.0)
    assert m.used_margin == 40.0 and m.available_margin == pytest.approx(50.0)
    assert m.maintenance_margin == pytest.approx(MMR * 95 * 2)
    assert m.liquidatable is False


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_liquidation_price_is_where_equity_meets_maintenance_margin(side):
    liq = compute_liquidation_price(side=side, entry_price=100.0, quantity=5.0, balance=100.0, maintenance_margin_rate=MMR)
    m = margin_state(balance=100.0, maintenance_margin_rate=MMR, side=side, quantity=5.0, entry_price=100.0, mark_price=liq)
    assert m.equity == pytest.approx(m.maintenance_margin, rel=1e-9)
    beyond = liq * (0.999 if side == Side.LONG else 1.001)
    assert margin_state(balance=100.0, maintenance_margin_rate=MMR, side=side, quantity=5.0, entry_price=100.0, mark_price=beyond).liquidatable


def test_fully_collateralised_long_has_no_liquidation_price():
    assert compute_liquidation_price(side=Side.LONG, entry_price=100.0, quantity=0.5, balance=100.0, maintenance_margin_rate=MMR) is None


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


def _levered_dna(**kw):
    return make_dna(
        risk_profile=RiskProfile(max_leverage=5.0, max_position_fraction=0.5), leverage_limit=5.0,
        position_sizing=PositionSizing(method="fraction_of_equity", fraction_of_equity=0.5),
        stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(enabled=False), **kw)


async def test_leverage_multiplies_notional_but_margin_stays_within_the_cap(db_session):
    (agent,) = await make_agents(db_session, [_levered_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    order = (await db_session.execute(select(Order).where(Order.agent_id == agent.id))).scalar_one()
    # DNA wants margin 50% x 5x = $250 notional, but gross exposure is hard-capped at
    # max_exposure_multiple (2x equity) -> $200 notional on $40 of margin.
    assert order.requested_notional == pytest.approx(250.0)
    assert order.approved_notional == pytest.approx(200.0, rel=0.02)
    assert order.initial_margin == pytest.approx(40.0, rel=0.02)
    assert order.leverage == 5.0
    assert order.requested_notional is not None and order.risk_amount is not None and order.quantity > 0


async def test_notional_never_exceeds_available_margin_times_leverage(db_session):
    (agent,) = await make_agents(db_session, [_levered_dna()], balance=100.0)
    agent.balance = 20.0          # agent already lost most of its cash (risk anchors reset so only margin binds)
    agent.equity = agent.peak_equity = agent.day_start_equity = 20.0
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    order = (await db_session.execute(select(Order).where(Order.agent_id == agent.id))).scalar_one()
    assert order.approved_notional <= 20.0 * 0.5 * 5.0 + 1e-6      # (equity x margin cap) x leverage
    assert order.approved_notional <= 20.0 * 2.0 + 1e-6            # and never above the gross exposure cap


async def test_liquidation_closes_the_position_charges_penalty_and_can_kill_the_agent(db_session):
    (agent,) = await make_agents(db_session, [_levered_dna()])
    eng = PaperExecutionAdapter()
    ctx1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, ctx1)
    pos = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalar_one()
    assert pos.liquidation_price is not None and pos.liquidation_price < pos.entry_price
    # Crash straight through the liquidation price.
    crash = make_context(2, 50.0, rsi=65.0, high=99.0, low=45.0, open_=98.0)
    await cycle(db_session, eng, crash, ctx1)
    await db_session.refresh(agent)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    exit_order = (await db_session.execute(select(Order).where(Order.reduce_only.is_(True)))).scalar_one()
    assert trade.exit_reason == "liquidation" and exit_order.order_kind == "liquidation"
    assert trade.fees > 0 and trade.net_pnl < 0
    assert agent.balance >= 0.0
    # Account was wiped out: the agent dies permanently, with the reason recorded.
    assert agent.status == AgentStatus.DEAD and agent.death_reason == "liquidated"
    assert agent.final_equity is not None and agent.death_timestamp is not None
    assert agent.final_pnl == pytest.approx(agent.final_equity - agent.starting_balance)


async def test_dead_agents_are_never_processed_again_or_revived(db_session):
    (agent,) = await make_agents(db_session, [_levered_dna()])
    eng = PaperExecutionAdapter()
    ctx1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, ctx1)
    await cycle(db_session, eng, make_context(2, 50.0, rsi=65.0, high=99.0, low=45.0, open_=98.0), ctx1)
    await db_session.refresh(agent)
    assert agent.status == AgentStatus.DEAD
    before = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id))).scalars().all()
    processed = await cycle(db_session, eng, make_context(3, 100.0, rsi=70.0))
    after = (await db_session.execute(select(Decision).where(Decision.agent_id == agent.id))).scalars().all()
    assert processed == 0 and len(after) == len(before)
    await db_session.refresh(agent)
    assert agent.status == AgentStatus.DEAD


async def test_ordinary_stop_out_is_not_a_liquidation(db_session):
    dna = make_dna(stop_loss=StopLossConfig(method="atr_multiple", value=2.0), take_profit=TakeProfitConfig(enabled=False))
    (agent,) = await make_agents(db_session, [dna])
    eng = PaperExecutionAdapter()
    ctx1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, ctx1)
    await cycle(db_session, eng, make_context(2, 98.0, rsi=65.0, high=100.0, low=97.5, open_=99.9), ctx1)
    await db_session.refresh(agent)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert trade.exit_reason == "stop_loss" and agent.status == AgentStatus.ACTIVE
