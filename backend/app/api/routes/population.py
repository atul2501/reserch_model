from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.enums import AgentStatus
from app.models.strategy import Generation
from app.models.trading import Position, Trade
from app.schemas.api import PopulationSummary

router = APIRouter(prefix="/api/population", tags=["population"])


@router.get("", response_model=PopulationSummary)
async def get_population_summary(db: AsyncSession = Depends(get_db)):
    latest_gen = (
        await db.execute(select(Generation).order_by(Generation.number.desc()).limit(1))
    ).scalar_one_or_none()
    generation_number = latest_gen.number if latest_gen else 0

    agents_stmt = select(Agent).where(Agent.generation == generation_number)
    agents = (await db.execute(agents_stmt)).scalars().all()

    active = [a for a in agents if a.status == AgentStatus.ACTIVE]
    dead = [a for a in agents if a.status == AgentStatus.DEAD]
    retired = [a for a in agents if a.status == AgentStatus.RETIRED]
    professional = [a for a in agents if a.is_professional]
    generations_total = (await db.execute(select(func.count()).select_from(Generation))).scalar_one()
    equities = [a.equity for a in agents]

    # Trade counts are aggregated in SQL (one query each), never by loading rows.
    total_trades = (await db.execute(select(func.count()).select_from(Trade))).scalar_one()
    gen_agent_ids = select(Agent.id).where(Agent.generation == generation_number)
    generation_trades, generation_wins = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(case((Trade.net_pnl > 0, 1), else_=0)), 0))
            .where(Trade.agent_id.in_(gen_agent_ids))
        )
    ).one()
    open_positions = (
        await db.execute(
            select(func.count()).select_from(Position).where(Position.is_open.is_(True), Position.agent_id.in_(gen_agent_ids))
        )
    ).scalar_one()

    return PopulationSummary(
        generation=generation_number,
        target_size=latest_gen.population_target if latest_gen else 0,
        active_count=len(active),
        dead_count=len(dead),
        professional_count=len(professional),
        total_equity=sum(a.equity for a in agents),
        total_realized_pnl=sum(a.realized_pnl for a in agents),
        total_capital_allocated=latest_gen.total_capital_allocated if latest_gen else 0.0,
        retired_count=len(retired), total_count=len(agents), generations_total=generations_total,
        mean_equity=(sum(equities) / len(equities)) if equities else None,
        best_equity=max(equities) if equities else None, worst_equity=min(equities) if equities else None,
        total_fees_paid=sum(a.fees_paid for a in agents), total_funding_paid=sum(a.funding_paid for a in agents),
        total_trades=total_trades, generation_trades=generation_trades, open_positions=open_positions,
        win_rate=(generation_wins / generation_trades) if generation_trades else None,
    )
