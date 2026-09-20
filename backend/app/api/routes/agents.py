from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.schemas.api import AgentDetail, AgentSummary

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _to_summary(agent: Agent) -> AgentSummary:
    roi = (agent.equity - agent.starting_balance) / agent.starting_balance if agent.starting_balance else 0.0
    return AgentSummary(
        id=agent.id,
        identifier=agent.identifier,
        generation=agent.generation,
        status=agent.status,
        strategy_version_id=agent.strategy_version_id,
        balance=agent.balance,
        equity=agent.equity,
        starting_balance=agent.starting_balance,
        roi=roi,
        realized_pnl=agent.realized_pnl,
        max_drawdown=agent.max_drawdown,
        trade_count=agent.trade_count,
        is_professional=agent.is_professional,
        best_milestone_multiple=agent.best_milestone_multiple,
        fitness=agent.fitness,
        created_at=agent.created_at,
    )


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    generation: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    stmt = select(Agent)
    if generation is not None:
        stmt = stmt.where(Agent.generation == generation)
    if status_filter is not None:
        stmt = stmt.where(Agent.status == status_filter)
    stmt = stmt.order_by(Agent.identifier).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_to_summary(a) for a in result.scalars().all()]


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    summary = _to_summary(agent)
    return AgentDetail(
        **summary.model_dump(),
        fees_paid=agent.fees_paid,
        funding_paid=agent.funding_paid,
        peak_equity=agent.peak_equity,
        death_timestamp=agent.death_timestamp,
        death_reason=agent.death_reason,
        final_equity=agent.final_equity,
        final_pnl=agent.final_pnl,
    )
