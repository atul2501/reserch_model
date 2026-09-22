from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.correlation import AgentCorrelation, CorrelationConvergenceSnapshot, StrategyFamilyCorrelation
from app.schemas.correlation import (
    AgentPairCorrelationOut,
    CorrelationConvergenceOut,
    StrategyFamilyCorrelationOut,
)

router = APIRouter(prefix="/api/correlation", tags=["correlation"])


@router.get("/matrix", response_model=list[StrategyFamilyCorrelationOut])
async def get_family_correlation_matrix(generation: int, db: AsyncSession = Depends(get_db)):
    """Family x family mean-correlation grid for one generation — never
    the raw agent x agent matrix (500 agents = 125k pairs)."""
    rows = (
        await db.execute(
            select(StrategyFamilyCorrelation).where(StrategyFamilyCorrelation.generation == generation)
        )
    ).scalars().all()
    return rows


@router.get("/top-pairs", response_model=list[AgentPairCorrelationOut])
async def get_top_correlated_pairs(
    generation: int, db: AsyncSession = Depends(get_db), limit: int = Query(default=50, le=200)
):
    rows = (
        await db.execute(
            select(AgentCorrelation)
            .where(AgentCorrelation.generation == generation)
            .order_by(AgentCorrelation.composite_correlation.desc())
            .limit(limit)
        )
    ).scalars().all()
    return rows


@router.get("/convergence-history", response_model=list[CorrelationConvergenceOut])
async def get_convergence_history(db: AsyncSession = Depends(get_db), limit: int = Query(default=50, le=200)):
    """Generation-over-generation convergence trend — this is the
    correlation-history-across-generations store the correlation engine
    exists to provide."""
    rows = (
        await db.execute(
            select(CorrelationConvergenceSnapshot).order_by(CorrelationConvergenceSnapshot.generation.desc()).limit(limit)
        )
    ).scalars().all()
    return rows


@router.get("/agent/{agent_id}", response_model=list[AgentPairCorrelationOut])
async def get_agent_correlations(
    agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), limit: int = Query(default=20, le=100)
):
    """This agent's most-correlated peers, most recent generation it
    appears in first."""
    rows = (
        await db.execute(
            select(AgentCorrelation)
            .where(or_(AgentCorrelation.agent_id_a == agent_id, AgentCorrelation.agent_id_b == agent_id))
            .order_by(AgentCorrelation.generation.desc(), AgentCorrelation.composite_correlation.desc())
            .limit(limit)
        )
    ).scalars().all()
    return rows
