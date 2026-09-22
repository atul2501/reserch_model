from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.regime_validation import RegimeValidationReport
from app.schemas.regime_validation import RegimeValidationReportOut

router = APIRouter(prefix="/api/regime-validation", tags=["regime-validation"])


@router.get("/{strategy_version_id}", response_model=RegimeValidationReportOut)
async def get_latest_regime_validation(strategy_version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    report = (
        await db.execute(
            select(RegimeValidationReport)
            .where(RegimeValidationReport.strategy_version_id == strategy_version_id)
            .order_by(RegimeValidationReport.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="no regime validation report for this strategy version yet")
    return report


@router.get("/{strategy_version_id}/history", response_model=list[RegimeValidationReportOut])
async def get_regime_validation_history(
    strategy_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
):
    reports = (
        await db.execute(
            select(RegimeValidationReport)
            .where(RegimeValidationReport.strategy_version_id == strategy_version_id)
            .order_by(RegimeValidationReport.computed_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return reports
