from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.enums import AgentStatus
from app.models.strategy import Generation
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
    professional = [a for a in agents if a.is_professional]

    return PopulationSummary(
        generation=generation_number,
        target_size=latest_gen.population_target if latest_gen else 0,
        active_count=len(active),
        dead_count=len(dead),
        professional_count=len(professional),
        total_equity=sum(a.equity for a in active),
        total_realized_pnl=sum(a.realized_pnl for a in agents),
        total_capital_allocated=latest_gen.total_capital_allocated if latest_gen else 0.0,
    )
