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
            day_start_equity=starting_balance,
            day_start_date=datetime.now(timezone.utc).date(),
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


def bankruptcy_threshold(agent: Agent) -> float:
    """Equity at or below which the agent is DEAD (default 0 = fully depleted)."""
    from app.core.config import get_settings
    return agent.starting_balance * get_settings().agent_bankruptcy_equity_fraction


def update_equity(agent: Agent, new_equity: float, *, death_reason: str = "equity_depleted") -> None:
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

    if new_equity <= max(0.0, bankruptcy_threshold(agent)):
        mark_dead(agent, reason=death_reason)


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


async def retire_generation(
    db: AsyncSession, generation_number: int, *, mark_price: float, at: datetime, fee_rate: float,
) -> dict:
    """Ends a superseded generation cleanly: every open position is closed at
    `mark_price` (a real Trade with exit_reason='generation_rollover', fees and
    funding included) and every still-ACTIVE agent becomes RETIRED with its
    final equity/PnL frozen. DEAD agents stay DEAD (never revived); nothing is
    deleted. Returns counts for the report."""
    from app.analytics.pnl_engine import compute_trade_pnl
    from app.models.strategy import StrategyVersion
    from app.models.trading import Position, Trade

    agents = (
        await db.execute(select(Agent).where(Agent.generation == generation_number, Agent.status == AgentStatus.ACTIVE))
    ).scalars().all()
    if not agents:
        return {"retired": 0, "positions_closed": 0}
    by_id = {a.id: a for a in agents}
    stage_by_version = {
        v.id: v.stage
        for v in (await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents})))).scalars().all()
    }
    positions = (
        await db.execute(select(Position).where(Position.agent_id.in_(list(by_id)), Position.is_open.is_(True)))
    ).scalars().all()
    for pos in positions:
        agent = by_id[pos.agent_id]
        exit_fee = mark_price * pos.quantity * fee_rate
        pnl = compute_trade_pnl(
            side=pos.side, quantity=pos.quantity, entry_price=pos.entry_price, exit_price=mark_price,
            entry_fee=pos.entry_fee, exit_fee=exit_fee, funding_paid=pos.funding_accrued,
        )
        pos.is_open = False
        pos.closed_at = at
        pos.unrealized_pnl = 0.0
        db.add(Trade(
            agent_id=agent.id, position_id=pos.id, entry_order_id=pos.entry_order_id, symbol=pos.symbol, side=pos.side,
            quantity=pos.quantity, entry_price=pos.entry_price, exit_price=mark_price, gross_pnl=pnl.gross_pnl,
            fees=pnl.fees, funding=pnl.funding, slippage_cost=pos.entry_slippage_cost, net_pnl=pnl.net_pnl,
            opened_at=pos.opened_at, closed_at=at, holding_seconds=max(0, int((at - pos.opened_at).total_seconds())),
            entry_regime=pos.entry_regime, exit_reason="generation_rollover", stage=stage_by_version.get(agent.strategy_version_id),
        ))
        agent.balance = max(0.0, agent.balance + pnl.gross_pnl - exit_fee)
        agent.realized_pnl += pnl.net_pnl
        agent.fees_paid += exit_fee
        agent.equity = agent.balance
    for agent in agents:
        agent.status = AgentStatus.RETIRED
        agent.final_equity = agent.equity
        agent.final_pnl = agent.equity - agent.starting_balance
    await db.flush()
    return {"retired": len(agents), "positions_closed": len(positions)}
