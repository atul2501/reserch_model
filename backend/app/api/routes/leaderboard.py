from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.agents import _to_summary
from app.core.database import get_db
from app.models.agent import Agent
from app.models.enums import AgentStatus
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.api import LeaderboardEntry

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=500),
    include_dead: bool = False,
):
    stmt = (
        select(Agent, Strategy.family)
        .outerjoin(StrategyVersion, StrategyVersion.id == Agent.strategy_version_id)
        .outerjoin(Strategy, Strategy.id == StrategyVersion.strategy_id)
    )
    if not include_dead:
        stmt = stmt.where(Agent.status == AgentStatus.ACTIVE)
    stmt = stmt.order_by(Agent.equity.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()
    return [
        LeaderboardEntry(
            rank=i + 1,
            agent=_to_summary(agent),
            strategy_family=family.value if family is not None else None,
        )
        for i, (agent, family) in enumerate(rows)
    ]
