"""Independent agents, per-agent failure isolation and DB-level idempotency
(spec phases 20, 31, 38)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.execution.base import ExecutionEngine
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import Bias, ExecutionVenue, OrderStatus, RiskDecision, Side
from app.models.trading import FundingPayment, Order, Position
from tests.helpers_agents import cycle, make_agents, make_context, make_dna

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


async def test_every_agent_starts_with_its_own_100_dollars_and_independent_balance(db_session):
    dnas = [make_dna(), make_dna(), make_dna()]
    agents = await make_agents(db_session, dnas)
    assert [a.starting_balance for a in agents] == [100.0] * 3 == [a.balance for a in agents] == [a.equity for a in agents]
    assert get_settings().agent_starting_balance == 100.0
    agents[0].balance = 5.0
    await db_session.commit()
    others = (await db_session.execute(select(Agent).where(Agent.id != agents[0].id))).scalars().all()
    assert all(a.balance == 100.0 for a in others)          # one agent's loss never touches another's account


async def test_a_failing_agent_is_isolated_and_the_rest_of_the_population_trades(db_session):
    agents = await make_agents(db_session, [make_dna(), make_dna(), make_dna()])
    poisoned = agents[1].id

    class Flaky(PaperExecutionAdapter):
        async def submit_order(self, request):
            if request.agent_id == str(poisoned):
                raise RuntimeError("venue exploded for this agent only")
            return await super().submit_order(request)

    processed = await cycle(db_session, Flaky(), make_context(1, 100.0, rsi=65.0))
    assert processed == 2
    positions = (await db_session.execute(select(Position))).scalars().all()
    assert {p.agent_id for p in positions} == {agents[0].id, agents[2].id}
    # The poisoned agent left no half-written state behind (savepoint rolled back).
    assert (await db_session.execute(select(Decision).where(Decision.agent_id == poisoned))).first() is None
    assert (await db_session.execute(select(Order).where(Order.agent_id == poisoned))).first() is None


async def test_re_running_a_candle_never_duplicates_decisions(db_session):
    await make_agents(db_session, [make_dna(), make_dna()])
    eng = PaperExecutionAdapter()
    ctx = make_context(1, 100.0, rsi=65.0)
    assert await cycle(db_session, eng, ctx) == 2
    assert await cycle(db_session, eng, ctx) == 0            # already-decided candle is skipped
    assert len((await db_session.execute(select(Decision))).scalars().all()) == 2


async def test_database_rejects_a_second_decision_for_the_same_agent_and_candle(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    first = (await db_session.execute(select(Decision))).scalar_one()
    dup = Decision(
        agent_id=agent.id, strategy_version_id=agent.strategy_version_id, market_candle_open_time=first.market_candle_open_time,
        market_timestamp=first.market_timestamp, market_context={}, agent_signal=Bias.LONG, agent_signal_confidence=1.0,
        risk_decision=RiskDecision.APPROVED, risk_reasoning={},
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_database_rejects_a_second_open_position_for_one_agent(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    existing = (await db_session.execute(select(Position))).scalar_one()
    db_session.add(Position(agent_id=agent.id, symbol="SOL", side=Side.LONG, quantity=1, entry_price=100, opened_at=existing.opened_at))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_closed_positions_do_not_block_a_new_open_one(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    c1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, c1)
    c2 = make_context(2, 101.0, rsi=30.0)
    await cycle(db_session, eng, c2, c1)
    await cycle(db_session, eng, make_context(3, 100.0, rsi=65.0), c2)
    rows = (await db_session.execute(select(Position).where(Position.agent_id == agent.id))).scalars().all()
    assert sorted(p.is_open for p in rows) == [False, True]


async def test_client_order_id_is_unique_in_the_database(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    for _ in range(2):
        db_session.add(Order(agent_id=agent.id, client_order_id="same-id", symbol="SOL", side=Side.LONG, quantity=1,
                             venue=ExecutionVenue.PAPER, status=OrderStatus.PENDING))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_funding_settlement_cannot_be_charged_twice_to_one_position(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    pos = (await db_session.execute(select(Position))).scalar_one()
    for _ in range(2):
        db_session.add(FundingPayment(agent_id=agent.id, position_id=pos.id, symbol="SOL", funding_time_ms=123,
                                      funding_rate=0.0001, position_notional=10.0, payment=0.001))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
