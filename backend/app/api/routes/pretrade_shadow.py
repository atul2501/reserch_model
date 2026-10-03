"""PRE-TRADE SHADOW dashboard API. Read-only: shadow JSONL files + read-only DB queries. Nothing here can create
orders, positions or balance changes, and the numbers are HYPOTHETICAL shadow measurements, never real P&L."""
from __future__ import annotations

import io
import json
import time

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(prefix="/api/pretrade-shadow", tags=["pretrade-shadow"])
_CACHE: dict[tuple, tuple[float, object]] = {}
CACHE_SECONDS = 30.0


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if np.isfinite(f) else None
    if isinstance(o, np.bool_):
        return bool(o)
    return o


async def _assembled(db, horizon: int, hour_group: int):
    from app.pretrade.assemble import assemble   # lazy: the API never loads it unless the page is used

    key = (horizon, hour_group)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    out = await assemble(db, get_settings(), horizon=horizon, hour_group=hour_group)
    _CACHE[key] = (time.monotonic(), out)
    return out


@router.get("/summary")
async def pretrade_shadow_summary(
    db: AsyncSession = Depends(get_db),
    horizon: int = Query(default=10, description="forward-return horizon in minutes: 1, 5, 10, 30 or 60"),
    hour_group: int = Query(default=1, ge=1, le=6),
):
    _, _, _, payload = await _assembled(db, horizon, hour_group)
    return _jsonable({"banner": "SHADOW / HYPOTHETICAL - DOES NOT AFFECT PAPER OR LIVE TRADING", **payload})


@router.get("/decisions.csv")
async def pretrade_shadow_decisions_csv(db: AsyncSession = Depends(get_db)):
    _, dataset, _, _ = await _assembled(db, 10, 1)
    buf = io.StringIO()
    out = dataset.drop(columns=[c for c in dataset.columns if c.startswith("_")]).copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, (list, dict))).any():
            out[col] = out[col].map(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v)
    out.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=pretrade_shadow_decisions.csv"})
