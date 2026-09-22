"""Wires compute_fitness (previously uncalled anywhere outside its own
test) to real Agent/Trade data, so Agent.fitness — read by
app/evolution/breeding.py::select_survivors for every breeding cycle —
means something instead of always falling back to raw equity."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.analytics.fitness_service import compute_and_persist_agent_fitness
from app.models.agent import Agent
from app.models.enums import Side, StrategyFamily
from app.models.metrics import FitnessScore
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


async def _seed_agent_with_trades(db_session, *, generation: int, net_pnls: list[float]) -> Agent:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
    db_session.add(strategy)
    await db_session.flush()

    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=generation, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.flush()

    starting_balance = 100.0
    equity = starting_balance + sum(net_pnls)
    agent = Agent(
        identifier=f"GEN{generation:02d}-AG{uuid.uuid4().hex[:4]}",
        generation=generation,
        strategy_version_id=version.id,
        starting_balance=starting_balance,
        balance=equity,
        equity=equity,
        peak_equity=max(starting_balance, equity),
        max_drawdown=0.0,
        day_start_equity=equity,
        day_start_date=date.today(),
    )
    db_session.add(agent)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for i, net_pnl in enumerate(net_pnls):
        opened = now - timedelta(hours=len(net_pnls) - i, minutes=5)
        closed = now - timedelta(hours=len(net_pnls) - i)
        db_session.add(
            Trade(
                agent_id=agent.id,
                position_id=uuid.uuid4(),
                symbol="SOL",
                side=Side.LONG,
                quantity=1.0,
                entry_price=100.0,
                exit_price=100.0 + net_pnl,
                gross_pnl=net_pnl,
                fees=0.0,
                net_pnl=net_pnl,
                opened_at=opened,
                closed_at=closed,
                holding_seconds=300,
                exit_reason="signal",
            )
        )
    await db_session.commit()
    return agent


@pytest.mark.asyncio
async def test_agent_fitness_gets_written_from_real_trades(db_session):
    agent = await _seed_agent_with_trades(db_session, generation=200, net_pnls=[5.0, -2.0, 3.0, 4.0])
    assert agent.fitness is None  # sanity check: unwritten before the service runs

    summary = await compute_and_persist_agent_fitness(db_session, generation=200)
    await db_session.commit()

    assert summary.agent_count == 1
    assert summary.mean_fitness is not None

    await db_session.refresh(agent)
    assert agent.fitness is not None
    assert agent.fitness == pytest.approx(summary.mean_fitness)

    scores = (await db_session.execute(select(FitnessScore).where(FitnessScore.agent_id == agent.id))).scalars().all()
    assert len(scores) == 1
    assert scores[0].fitness == pytest.approx(agent.fitness)


@pytest.mark.asyncio
async def test_agent_with_no_trades_still_gets_a_finite_fitness(db_session):
    agent = await _seed_agent_with_trades(db_session, generation=201, net_pnls=[])

    await compute_and_persist_agent_fitness(db_session, generation=201)
    await db_session.commit()

    await db_session.refresh(agent)
    assert agent.fitness is not None
    import math
    assert math.isfinite(agent.fitness)


@pytest.mark.asyncio
async def test_only_agents_in_the_requested_generation_are_touched(db_session):
    gen_a = await _seed_agent_with_trades(db_session, generation=210, net_pnls=[1.0])
    gen_b = await _seed_agent_with_trades(db_session, generation=211, net_pnls=[1.0])

    await compute_and_persist_agent_fitness(db_session, generation=210)
    await db_session.commit()

    await db_session.refresh(gen_a)
    await db_session.refresh(gen_b)
    assert gen_a.fitness is not None
    assert gen_b.fitness is None
