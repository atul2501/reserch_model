"""Regression: an entry that FILLS on a funding-settlement bar must not be lost.

Production evidence (backup 2026-10-02): 0 of 43,881 positions opened on an hour bar and all 397 entries signalled
at minute :59 ended CANCELLED/expired_unfilled. Mechanism: _fill_entry builds a Position whose `funding_accrued`
column default (0.0) is only applied at INSERT; the same cycle then manages the position, _accrue_funding finds the
hour's settlement due and does `None += payment` -> TypeError -> the agent's savepoint rolls back the fill.

Precondition (always true in production, 500 agents): ANOTHER position is already open when the cycle starts, because
run_decision_cycle only loads funding rates for positions that exist at cycle start. The tests reproduce exactly that.
"""
from __future__ import annotations

from datetime import datetime, timezone

import uuid

import pytest
from sqlalchemy import select

from app.agents.lifecycle import create_generation
from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.models.enums import OrderStatus, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import FundingPayment, Order, Position
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA
from app.worker import cycle as cycle_mod
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar

HOUR_BAR = 420               # T0 + 7h: FakeHyperliquid publishes a funding settlement exactly at this bar's open


@pytest.fixture
def paper(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", False)
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def _seed_always_long(db, n_agents: int = 1):
    ids = []
    for _ in range(n_agents):
        ids.append(await _always_long_version(db))
    await create_generation(db, generation_number=1, strategy_version_ids=ids, starting_balance=100.0)


async def _always_long_version(db):
    st = Strategy(code=f"S-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="t")
    db.add(st)
    await db.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM, direction_mode="long_only",
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="close", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)]),
        risk_profile=RiskProfile(max_leverage=1.0, max_position_fraction=0.5),
    )
    v = StrategyVersion(strategy_id=st.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db.add(v)
    await db.flush()
    return v.id


async def _open_position_for_first_agent(db, since_bar: int):
    """Agent #1 already holds a small open LONG (as hundreds of production agents do), opened before the hour."""
    from app.models.agent import Agent
    from app.models.enums import ExecutionVenue, Side
    agent = (await db.execute(select(Agent).order_by(Agent.identifier))).scalars().first()
    t = datetime.fromtimestamp((T0 + since_bar * INTERVAL) / 1000, tz=timezone.utc)
    db.add(Position(agent_id=agent.id, symbol="SOL", side=Side.LONG, quantity=0.01, entry_price=100.0, leverage=1.0,
                    initial_margin=1.0, maintenance_margin=0.01, peak_price=100.0, trough_price=100.0,
                    last_funding_time=t, entry_fee=0.0, entry_slippage_cost=0.0, funding_accrued=0.0,
                    entry_candle_open_time=T0 + since_bar * INTERVAL, venue=ExecutionVenue.PAPER, opened_at=t,
                    is_open=True, last_processed_open_time=T0 + since_bar * INTERVAL))
    await db.commit()
    return agent.id


async def _decide_then_fill(db, fill_bar: int):
    """Decide on bar fill_bar-1 (next_open), then process fill_bar."""
    fake = FakeHyperliquid(n_candles=fill_bar + 1)
    fake.hidden = {T0 + fill_bar * INTERVAL}
    await cycle_mod.run_pending_cycles(db, MarketDataService(fake, clock_ms=lambda: clock_after_bar(fill_bar - 1)), None,
                                       execution_engine=PaperExecutionAdapter())
    fake.hidden = set()
    await cycle_mod.run_pending_cycles(db, MarketDataService(fake, clock_ms=lambda: clock_after_bar(fill_bar)), None,
                                       execution_engine=PaperExecutionAdapter())
    db.expire_all()
    entry = (await db.execute(select(Order).where(Order.reduce_only.is_(False))
                              .order_by(Order.created_at))).scalars().first()
    positions = (await db.execute(select(Position))).scalars().all()
    payments = (await db.execute(select(FundingPayment))).scalars().all()
    return entry, positions, payments


def test_fixture_puts_a_funding_settlement_exactly_on_the_hour_bar():
    assert any(f["time"] == T0 + HOUR_BAR * INTERVAL for f in FakeHyperliquid(n_candles=HOUR_BAR + 1).funding)


async def test_signal_at_59_fills_on_the_funding_hour_bar(db_session, paper):
    """:59 signal -> :00 fill on a funding bar, while another agent holds a position (production condition):
    the fill must survive and the :00 settlement must be booked on the new position."""
    await _seed_always_long(db_session, n_agents=2)
    holder = await _open_position_for_first_agent(db_session, since_bar=HOUR_BAR - 30)
    await _decide_then_fill(db_session, HOUR_BAR)
    entries = (await db_session.execute(select(Order).where(Order.reduce_only.is_(False)))).scalars().all()
    new = [o for o in entries if o.agent_id != holder]
    assert len(new) == 1 and new[0].signal_candle_open_time == T0 + (HOUR_BAR - 1) * INTERVAL     # the :59 signal
    assert new[0].status == OrderStatus.FILLED, new[0].rejection_reason
    fresh = (await db_session.execute(select(Position).where(Position.agent_id == new[0].agent_id))).scalars().all()
    assert len(fresh) == 1, "the :00 funding-bar fill was lost"
    p = fresh[0]
    assert p.entry_candle_open_time == T0 + HOUR_BAR * INTERVAL       # opened ON the :00 funding bar
    pays = (await db_session.execute(select(FundingPayment).where(FundingPayment.position_id == p.id))).scalars().all()
    assert len(pays) == 1 and pays[0].funding_time_ms == T0 + HOUR_BAR * INTERVAL
    assert p.funding_accrued == pytest.approx(pays[0].payment)
    held = (await db_session.execute(select(FundingPayment).where(FundingPayment.agent_id == holder))).scalars().all()
    assert len(held) == 1                                              # the existing holder is charged as before


async def test_non_funding_bar_entry_is_unchanged(db_session, paper):
    """Control: an ordinary minute (same production condition) behaves exactly as before."""
    await _seed_always_long(db_session, n_agents=2)
    holder = await _open_position_for_first_agent(db_session, since_bar=HOUR_BAR - 40)
    await _decide_then_fill(db_session, HOUR_BAR - 10)
    new = [o for o in (await db_session.execute(select(Order).where(Order.reduce_only.is_(False)))).scalars().all()
           if o.agent_id != holder]
    assert len(new) == 1 and new[0].status == OrderStatus.FILLED
    fresh = (await db_session.execute(select(Position).where(Position.agent_id == new[0].agent_id))).scalars().all()
    assert len(fresh) == 1 and fresh[0].funding_accrued == 0.0
    assert (await db_session.execute(select(FundingPayment))).scalars().all() == []

