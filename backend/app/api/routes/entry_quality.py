"""Entry Quality Model V1 - SHADOW AUDIT API. Read-only; every response here is a hypothetical
retrospective grading of signals the strategies already produced. Nothing here can affect live
trading - see app/analytics/entry_quality_model.py's module docstring.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.entry_quality_audit import DEFAULT_THRESHOLD, build_audit, export_rows, load_rows
from app.core.database import get_db

router = APIRouter(prefix="/api/entry-quality", tags=["entry-quality"])


@router.get("/audit")
async def entry_quality_audit(
    db: AsyncSession = Depends(get_db),
    family: str | None = None,
    regime: str | None = None,
    side: str | None = None,
    generation: int | None = None,
    agent_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    threshold: float = Query(default=DEFAULT_THRESHOLD, ge=0.0, le=1.0),
    matrix_metric: str = "actual_expectancy",
):
    return await build_audit(
        db, family=family, regime=regime, side=side, generation=generation,
        agent_id=str(agent_id) if agent_id else None, since=since, until=until,
        threshold=threshold, matrix_metric=matrix_metric,
    )


@router.get("/export.csv")
async def entry_quality_export(
    db: AsyncSession = Depends(get_db),
    family: str | None = None,
    regime: str | None = None,
    side: str | None = None,
    generation: int | None = None,
    agent_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    threshold: float = Query(default=DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    rows = await load_rows(
        db, family=family, regime=regime, side=side, generation=generation,
        agent_id=str(agent_id) if agent_id else None, since=since, until=until,
    )
    records = export_rows(rows, threshold=threshold)
    buf = io.StringIO()
    fieldnames = list(records[0].keys()) if records else [
        "timestamp", "trade_id", "agent_id", "generation_id", "strategy", "regime", "direction",
        "model_version", "predicted_probability", "shadow_threshold", "shadow_decision",
        "actual_trade", "actual_outcome", "actual_pnl", "mfe_r", "mae_r", "hold_seconds",
        "exit_reason", "trade_quality_class",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(records)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=entry_quality_shadow_audit.csv"},
    )
