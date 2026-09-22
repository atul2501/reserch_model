from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.adversarial import AdversarialTestReport
from app.schemas.adversarial import AdversarialTestReportOut

router = APIRouter(prefix="/api/adversarial", tags=["adversarial"])


@router.get("/{strategy_version_id}", response_model=AdversarialTestReportOut)
async def get_latest_adversarial_report(strategy_version_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    report = (
        await db.execute(
            select(AdversarialTestReport)
            .where(AdversarialTestReport.strategy_version_id == strategy_version_id)
            .order_by(AdversarialTestReport.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="no adversarial test report for this strategy version yet")
    return report


@router.get("/{strategy_version_id}/history", response_model=list[AdversarialTestReportOut])
async def get_adversarial_report_history(
    strategy_version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=200),
):
    reports = (
        await db.execute(
            select(AdversarialTestReport)
            .where(AdversarialTestReport.strategy_version_id == strategy_version_id)
            .order_by(AdversarialTestReport.computed_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return reports
