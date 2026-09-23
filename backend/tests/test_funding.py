"""Funding (spec phase 8): accrued from exchange-published settlements, never
hard-coded to zero, idempotent, and reflected in equity and trade PnL."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.market import FundingRate
from app.models.trading import FundingPayment, Position, Trade
from app.schemas.strategy_dna import StopLossConfig, TakeProfitConfig
from tests.helpers_agents import MINUTE, T0, cycle, make_agents, make_context, make_dna


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


def _dna(**kw):
    return make_dna(stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(enabled=False), **kw)


async def _hold_across(db, rate, side_dna, settle_after_bars=3):
    (agent,) = await make_agents(db, [side_dna])
    eng = PaperExecutionAdapter()
    ctx1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db, eng, ctx1)
    pos = (await db.execute(select(Position).where(Position.agent_id == agent.id))).scalar_one()
    settle_ms = T0 + (1 + settle_after_bars) * MINUTE + 5_000
    db.add(FundingRate(symbol="SOL", time_ms=settle_ms, rate=rate))
    await db.commit()
    prev = ctx1
    for i in range(2, settle_after_bars + 3):
        ctx = make_context(i, 100.0, rsi=55.0)      # neutral: neither exit (<40) nor entry
        await cycle(db, eng, ctx, prev)
        prev = ctx
    return agent, pos


async def test_long_pays_positive_funding_and_it_hits_balance_and_ledger(db_session):
    agent, pos = await _hold_across(db_session, 0.0001, _dna())
    await db_session.refresh(agent); await db_session.refresh(pos)
    payments = (await db_session.execute(select(FundingPayment).where(FundingPayment.position_id == pos.id))).scalars().all()
    assert len(payments) == 1
    p = payments[0]
    assert p.funding_rate == 0.0001 and p.position_notional == pytest.approx(pos.quantity * 100.0)
    assert p.payment == pytest.approx(p.position_notional * 0.0001) and p.payment > 0       # long pays
    assert agent.funding_paid == pytest.approx(p.payment) and pos.funding_accrued == pytest.approx(p.payment)
    assert pos.last_funding_time is not None


async def test_negative_rate_credits_a_long(db_session):
    agent, pos = await _hold_across(db_session, -0.0002, _dna())
    await db_session.refresh(agent)
    assert agent.funding_paid < 0                       # received


async def test_short_receives_positive_funding(db_session):
    dna = _dna(direction_mode="short_only")
    agent, pos = await _hold_across(db_session, 0.0001, dna)
    await db_session.refresh(agent)
    assert agent.funding_paid < 0


async def test_funding_is_idempotent_across_repeated_cycles(db_session):
    agent, pos = await _hold_across(db_session, 0.0001, _dna(), settle_after_bars=2)
    n = (await db_session.execute(select(func.count()).select_from(FundingPayment))).scalar_one()
    assert n == 1
    for i in range(20, 24):          # many more bars, no new settlements
        await cycle(db_session, PaperExecutionAdapter(), make_context(i, 100.0, rsi=55.0))
    assert (await db_session.execute(select(func.count()).select_from(FundingPayment))).scalar_one() == 1


async def test_no_funding_rows_means_no_charge_not_an_invented_one(db_session):
    (agent,) = await make_agents(db_session, [_dna()])
    eng = PaperExecutionAdapter()
    ctx1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, ctx1)
    await cycle(db_session, eng, make_context(2, 100.0, rsi=55.0), ctx1)
    await db_session.refresh(agent)
    assert agent.funding_paid == 0.0 and (await db_session.execute(select(func.count()).select_from(FundingPayment))).scalar_one() == 0


async def test_trade_pnl_includes_entry_fee_and_funding_and_matches_equity(db_session):
    agent, pos = await _hold_across(db_session, 0.0002, _dna())
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(20, 101.0, rsi=30.0), make_context(19, 100.0, rsi=55.0))   # exit signal (rsi<40)
    await db_session.refresh(agent)
    trade = (await db_session.execute(select(Trade).where(Trade.agent_id == agent.id))).scalar_one()
    assert trade.funding > 0
    assert trade.fees == pytest.approx(pos.entry_fee + (trade.fees - pos.entry_fee)) and trade.fees > pos.entry_fee
    assert trade.net_pnl == pytest.approx(trade.gross_pnl - trade.fees - trade.funding)     # slippage NOT subtracted twice
    # Trade-level PnL and account equity agree exactly.
    assert agent.equity == pytest.approx(agent.starting_balance + trade.net_pnl)
    assert agent.realized_pnl == pytest.approx(trade.net_pnl)
