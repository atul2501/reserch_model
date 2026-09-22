from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.reality_gap_engine import compute_full_reality_gap_chain
from app.core.database import get_db
from app.models.reality_gap import RealityGapReport
from app.schemas.reality_gap import RealityGapChainReportOut, RealityGapReportOut

router = APIRouter(prefix="/api/reality-gap", tags=["reality-gap"])


@router.get("/{strategy_version_id}", response_model=RealityGapChainReportOut)
async def get_reality_gap_chain(strategy_version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Computed live from current StageMetrics — read-only, not persisted.
    Empty stages_present/transitions just means no StageMetrics exist for
    this version yet at any stage, not an error."""
    report = await compute_full_reality_gap_chain(db, strategy_version_id)
    return report


@router.get("/{strategy_version_id}/history", response_model=list[RealityGapReportOut])
async def get_reality_gap_history(
    strategy_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
):
    reports = (
        await db.execute(
            select(RealityGapReport)
            .where(RealityGapReport.strategy_version_id == strategy_version_id)
            .order_by(RealityGapReport.computed_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return reports
