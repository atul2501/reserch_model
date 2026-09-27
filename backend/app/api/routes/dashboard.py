"""Read-only endpoints for the /analytics observability dashboard.

Thin routing layer only - every query lives in app.analytics.dashboard_service. No writes,
no trading/fitness/breeding logic here or in the service module it calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import dashboard_service as svc
from app.core.database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    return await svc.get_overview(db)


@router.get("/equity")
async def equity(db: AsyncSession = Depends(get_db), range: str = Query(default="ALL")):  # noqa: A002 - matches spec's query param name
    return await svc.get_equity_curve(db, range)


@router.get("/agents/metrics")
async def agent_metrics(
    db: AsyncSession = Depends(get_db),
    generation: int | None = None,
    status: str | None = None,
    strategy_family: str | None = None,
    sort_by: str = Query(default="fitness"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    return await svc.get_agent_metrics(
        db, generation=generation, status=status, strategy_family=strategy_family,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )


@router.get("/fitness/components")
async def fitness_components(db: AsyncSession = Depends(get_db), generation: int | None = None):
    return await svc.get_fitness_components(db, generation=generation)


@router.get("/champions/analysis")
async def champions_analysis(db: AsyncSession = Depends(get_db)):
    return await svc.get_champions_analysis(db)


@router.get("/timeframes")
async def timeframes(db: AsyncSession = Depends(get_db)):
    return await svc.get_timeframe_performance(db)


@router.get("/ranking-stability")
async def ranking_stability(db: AsyncSession = Depends(get_db)):
    return await svc.get_ranking_stability(db)
