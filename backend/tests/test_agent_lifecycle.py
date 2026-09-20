"""Agent creation, independent balances, death, and permanence (spec 12-16, 45)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agents.lifecycle import (
    AgentAlreadyDeadError,
    create_generation,
    format_agent_identifier,
    is_population_extinct,
    mark_dead,
    update_equity,
)
from app.models.agent import Agent
from app.models.enums import AgentStatus, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


async def _make_strategy_version(db_session) -> uuid.UUID:
    strategy = Strategy(code=f"STRAT-TEST-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="test")
    db_session.add(strategy)
    await db_session.flush()

    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=50)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.flush()
    return version.id


def test_format_agent_identifier_never_collides_across_generations():
    assert format_agent_identifier(1, 1) == "GEN01-AG0001"
    assert format_agent_identifier(2, 1) == "GEN02-AG0001"
    assert format_agent_identifier(1, 1) != format_agent_identifier(2, 1)


@pytest.mark.asyncio
async def test_create_generation_allocates_starting_balance_per_agent(db_session):
    version_ids = [await _make_strategy_version(db_session) for _ in range(5)]
    generation = await create_generation(
        db_session, generation_number=1, strategy_version_ids=version_ids, starting_balance=100.0
    )
    assert generation.total_capital_allocated == 500.0

    agents = (await db_session.execute(select(Agent).where(Agent.generation == 1))).scalars().all()
    assert len(agents) == 5
    for agent in agents:
        assert agent.balance == 100.0
        assert agent.equity == 100.0
        assert agent.starting_balance == 100.0
        assert agent.status == AgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_agent_balances_are_independent(db_session):
    version_ids = [await _make_strategy_version(db_session) for _ in range(2)]
    await create_generation(db_session, generation_number=2, strategy_version_ids=version_ids, starting_balance=100.0)
    agents = (await db_session.execute(select(Agent).where(Agent.generation == 2))).scalars().all()
    agent_a, agent_b = agents[0], agents[1]

    update_equity(agent_a, 0.0)  # agent_a goes bankrupt
    assert agent_a.status == AgentStatus.DEAD
    assert agent_b.status == AgentStatus.ACTIVE
    assert agent_b.equity == 100.0  # untouched by agent_a's loss


def _fresh_agent(balance: float = 100.0) -> Agent:
    # Mirrors a freshly-flushed row: SQLAlchemy column defaults (status,
    # max_drawdown, best_milestone_multiple, ...) only apply at INSERT time,
    # not on bare construction, so tests that exercise lifecycle logic in
    # isolation must set them explicitly.
    return Agent(
        identifier="GEN01-AG0001",
        generation=1,
        strategy_version_id=uuid.uuid4(),
        status=AgentStatus.ACTIVE,
        starting_balance=balance,
        balance=balance,
        equity=balance,
        peak_equity=balance,
        max_drawdown=0.0,
        best_milestone_multiple=1.0,
    )


def test_agent_dies_only_when_equity_non_positive():
    agent = _fresh_agent()
    update_equity(agent, 40.0)  # a losing day, still alive
    assert agent.status == AgentStatus.ACTIVE

    update_equity(agent, 0.0)
    assert agent.status == AgentStatus.DEAD
    assert agent.death_reason == "equity_depleted"
    assert agent.final_equity == 0.0


def test_death_is_permanent_and_cannot_be_revived():
    agent = _fresh_agent()
    mark_dead(agent, reason="equity_depleted")
    assert agent.status == AgentStatus.DEAD

    with pytest.raises(AgentAlreadyDeadError):
        update_equity(agent, 500.0)

    # Idempotent: calling mark_dead again must not raise or change the reason.
    mark_dead(agent, reason="some_other_reason")
    assert agent.death_reason == "equity_depleted"


def test_milestone_multiple_never_downgrades():
    agent = _fresh_agent()
    update_equity(agent, 300.0)  # 3x
    assert agent.best_milestone_multiple == 3.0

    update_equity(agent, 150.0)  # equity fell back to 1.5x
    assert agent.best_milestone_multiple == 3.0  # must not be downgraded


@pytest.mark.asyncio
async def test_population_extinct_when_all_agents_dead(db_session):
    version_ids = [await _make_strategy_version(db_session) for _ in range(3)]
    await create_generation(db_session, generation_number=3, strategy_version_ids=version_ids, starting_balance=100.0)
    agents = (await db_session.execute(select(Agent).where(Agent.generation == 3))).scalars().all()

    assert await is_population_extinct(db_session, 3) is False

    for agent in agents:
        update_equity(agent, 0.0)
    await db_session.flush()

    assert await is_population_extinct(db_session, 3) is True
