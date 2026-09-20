"""Agent + population lifecycle (spec sections 12-16, 52-53).

Rules enforced here, not left to callers:
  - every new agent gets exactly `starting_balance` of fresh capital
  - death (`equity <= 0`) is permanent — a dead agent is never revived
  - historical generation number is never rewritten
  - milestone multiples only ever increase
  - agent identifiers (GEN01-AG0001) are never reused
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent import Agent
from app.models.enums import AgentStatus, PopulationEventType, PopulationStatus
from app.models.evolution import PopulationEvent
from app.models.strategy import Generation

logger = get_logger(__name__)

MILESTONE_MULTIPLES = (2.0, 3.0, 5.0, 10.0, 25.0, 50.0, 100.0)


class AgentAlreadyDeadError(RuntimeError):
    pass


def format_agent_identifier(generation: int, index_in_generation: int) -> str:
    return f"GEN{generation:02d}-AG{index_in_generation:04d}"


async def create_generation(
    db: AsyncSession,
    *,
    generation_number: int,
    strategy_version_ids: list[uuid.UUID],
    starting_balance: float,
    triggered_by: str = "initial",
) -> Generation:
    """Creates a new Generation row and one Agent per strategy_version_id,
    each freshly capitalized with `starting_balance` (spec section 13)."""
    if not strategy_version_ids:
        raise ValueError("cannot create a generation with zero agents")

    total_capital = starting_balance * len(strategy_version_ids)
    generation = Generation(
        number=generation_number,
        population_target=len(strategy_version_ids),
        population_created=0,
        starting_balance=starting_balance,
        total_capital_allocated=total_capital,
        triggered_by=triggered_by,
    )
    db.add(generation)
    await db.flush()

    agents: list[Agent] = []
    for idx, strategy_version_id in enumerate(strategy_version_ids, start=1):
        identifier = format_agent_identifier(generation_number, idx)
        agent = Agent(
            identifier=identifier,
            generation=generation_number,
            strategy_version_id=strategy_version_id,
            status=AgentStatus.ACTIVE,
            starting_balance=starting_balance,
            balance=starting_balance,
            equity=starting_balance,
            peak_equity=starting_balance,
        )
        agents.append(agent)
    db.add_all(agents)

    generation.population_created = len(agents)
    await db.flush()

    await db.execute(
        PopulationEvent.__table__.insert().values(
            id=uuid.uuid4(),
            event_type=PopulationEventType.GENERATION_CREATED,
            generation=generation_number,
            population_status=PopulationStatus.ACTIVE,
            detail={"agent_count": len(agents), "total_capital_allocated": total_capital, "triggered_by": triggered_by},
            report={},
        )
    )
    await db.commit()

    logger.info(
        "population.generation_created",
        generation=generation_number,
        agent_count=len(agents),
        total_capital_allocated=total_capital,
    )
    return generation


def update_equity(agent: Agent, new_equity: float) -> None:
    """Updates equity, peak equity, drawdown, and milestone tracking. Never
    call this after the agent is DEAD."""
    if agent.status == AgentStatus.DEAD:
        raise AgentAlreadyDeadError(f"cannot update equity for dead agent {agent.identifier}")

    agent.equity = new_equity
    if new_equity > agent.peak_equity:
        agent.peak_equity = new_equity

    if agent.peak_equity > 0:
        drawdown = max(0.0, (agent.peak_equity - new_equity) / agent.peak_equity)
        agent.max_drawdown = max(agent.max_drawdown or 0.0, drawdown)

    if agent.starting_balance > 0:
        current_multiple = new_equity / agent.starting_balance
        for milestone in MILESTONE_MULTIPLES:
            # Section 16: milestones only ratchet up, never downgrade later.
            if current_multiple >= milestone and (agent.best_milestone_multiple or 1.0) < milestone:
                agent.best_milestone_multiple = milestone

    if new_equity <= 0:
        mark_dead(agent, reason="equity_depleted")


def mark_dead(agent: Agent, *, reason: str) -> None:
    """Permanently marks an agent dead. Idempotent: calling twice on an
    already-dead agent is a no-op rather than an error, since multiple
    independent checks (risk engine, PnL update) may all observe equity<=0
    in the same cycle."""
    if agent.status == AgentStatus.DEAD:
        return
    agent.status = AgentStatus.DEAD
    agent.death_timestamp = datetime.now(timezone.utc)
    agent.death_reason = reason
    agent.final_equity = agent.equity
    agent.final_pnl = agent.equity - agent.starting_balance
    logger.warning("agent.death", identifier=agent.identifier, reason=reason, final_equity=agent.equity)


async def is_population_extinct(db: AsyncSession, generation_number: int) -> bool:
    stmt = select(func.count()).select_from(Agent).where(
        Agent.generation == generation_number, Agent.status == AgentStatus.ACTIVE
    )
    active_count = (await db.execute(stmt)).scalar_one()
    return active_count == 0


async def record_extinction(db: AsyncSession, generation_number: int, report: dict) -> None:
    db.add(
        PopulationEvent(
            event_type=PopulationEventType.POPULATION_EXTINCT,
            generation=generation_number,
            population_status=PopulationStatus.EXTINCT,
            detail={},
            report=report,
        )
    )
    await db.commit()
    logger.error("population.extinct", generation=generation_number)
