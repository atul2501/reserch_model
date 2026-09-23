from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import ExecutionVenue, OrderStatus
from app.models.trading import Order

router = APIRouter(prefix="/api/shadow", tags=["shadow"])


@router.get("/summary")
async def shadow_summary(db: AsyncSession = Depends(get_db)):
    """Expected-vs-actual market execution measured by shadow mode."""
    rows = (await db.execute(select(Order).where(Order.venue == ExecutionVenue.SHADOW).order_by(Order.created_at.desc()).limit(2000))).scalars().all()
    filled = [o for o in rows if o.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)]
    raws = [o.raw_venue_response or {} for o in filled]

    def avg(key):
        vals = [r[key] for r in raws if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "orders": len(rows), "filled": len(filled), "fill_rate": (len(filled) / len(rows)) if rows else None,
        "partial_fills": sum(1 for o in rows if o.status == OrderStatus.PARTIALLY_FILLED),
        "avg_slippage_bps": avg("slippage_bps"), "avg_drift_after_latency_bps": avg("drift_after_latency_bps"),
        "avg_latency_ms": (sum(o.latency_ms for o in filled if o.latency_ms is not None) / max(1, sum(1 for o in filled if o.latency_ms is not None))) if filled else None,
        "sent_to_exchange": sum(1 for r in raws if r.get("sent_to_exchange")),   # must always be 0
    }
