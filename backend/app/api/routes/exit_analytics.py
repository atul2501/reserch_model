"""Exit-research dashboard data: MFE/MAE, realized R, post-exit movement,
reversal rate, exit-reason distribution, holding time, left-on-table. Reads
`TradeAnalytics` (the same table `scripts/report_trade_quality.py` reads) —
no new backend tracking, this is a read-only view over data already built by
`scripts/refresh_analytics.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.analytics import TradeAnalytics
from app.models.strategy import StrategyVersion
from app.models.trading import Trade

router = APIRouter(prefix="/api/exit-analytics", tags=["exit-analytics"])


def _histogram(values: list[float], *, bins: int = 12, lo: float | None = None, hi: float | None = None) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"bins": [], "counts": [], "min": None, "max": None, "mean": None, "median": None, "n": 0}
    lo = lo if lo is not None else min(values)
    hi = hi if hi is not None else max(values)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, max(0, int((v - lo) / width))) if width > 0 else 0
        counts[idx] += 1
    edges = [round(lo + i * width, 4) for i in range(bins + 1)]
    sv = sorted(values)
    median = sv[len(sv) // 2] if len(sv) % 2 else (sv[len(sv) // 2 - 1] + sv[len(sv) // 2]) / 2
    return {"bins": edges, "counts": counts, "min": min(values), "max": max(values),
            "mean": sum(values) / len(values), "median": median, "n": len(values)}


@router.get("")
async def exit_analytics(
    db: AsyncSession = Depends(get_db),
    family: str | None = None,
    generation: int | None = None,
    side: str | None = None,
    regime: str | None = None,
    agent_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=20_000, le=100_000),
):
    stmt = (
        select(TradeAnalytics, Trade.exit_reason, Trade.net_pnl, Trade.holding_seconds, Trade.closed_at)
        .join(Trade, Trade.id == TradeAnalytics.trade_id)
        .order_by(TradeAnalytics.computed_at.desc())
        .limit(limit)
    )
    if generation is not None:
        stmt = stmt.join(StrategyVersion, StrategyVersion.id == TradeAnalytics.strategy_version_id).where(
            StrategyVersion.generation == generation
        )
    if family is not None:
        stmt = stmt.where(TradeAnalytics.family == family)
    if side is not None:
        # TradeAnalytics.side is stored as "SIDE.SHORT"/"SIDE.LONG" (an enum-repr artifact
        # from analytics_store.py's `str(trade.side).upper()`, pre-existing and out of this
        # endpoint's scope to fix) rather than the clean "SHORT"/"LONG" - match by suffix so
        # the API's own query parameter stays the clean, obvious spelling.
        stmt = stmt.where(TradeAnalytics.side.endswith(side.upper()))
    if regime is not None:
        stmt = stmt.where(TradeAnalytics.regime == regime)
    if agent_id is not None:
        stmt = stmt.where(TradeAnalytics.agent_id == agent_id)
    if since is not None:
        stmt = stmt.where(Trade.closed_at >= since)
    if until is not None:
        stmt = stmt.where(Trade.closed_at <= until)
    rows = (await db.execute(stmt)).all()

    n = len(rows)
    mfe_r = [ta.mfe_r for ta, *_ in rows]
    mae_r = [ta.mae_r for ta, *_ in rows]
    left_on_table = [ta.left_on_table_r for ta, *_ in rows]
    holding = [hs for _, _, _, hs, _ in rows if hs is not None]

    class_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for ta, exit_reason, *_ in rows:
        klass = ta.trade_quality_class or "OTHER"
        class_counts[klass] = class_counts.get(klass, 0) + 1
        reason = exit_reason or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    mfe_capture = [
        (net_pnl / ta.max_unrealized_profit) for ta, _, net_pnl, *_ in rows
        if ta.max_unrealized_profit and ta.max_unrealized_profit > 0
    ]
    post_exit_favourable = [ta.post_exit_mfe_bps_30 for ta, *_ in rows if ta.post_exit_mfe_bps_30 is not None]
    reversal_count = class_counts.get("REVERSAL_AFTER_PROFIT", 0)

    return {
        "trades_analysed": n,
        "filters": {"family": family, "generation": generation, "side": side, "regime": regime,
                    "agent_id": agent_id, "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None},
        "mfe_r": _histogram(mfe_r, lo=-3, hi=6),
        "mae_r": _histogram(mae_r, lo=-6, hi=1),
        "left_on_table_r": _histogram(left_on_table, lo=0, hi=8),
        "holding_seconds": _histogram(holding),
        "mfe_capture_ratio": {
            "mean": (sum(mfe_capture) / len(mfe_capture)) if mfe_capture else None, "n": len(mfe_capture),
        },
        "post_exit_favourable_bps": {
            "mean": (sum(post_exit_favourable) / len(post_exit_favourable)) if post_exit_favourable else None,
            "n": len(post_exit_favourable),
        },
        "reversal_rate": (reversal_count / n) if n else None,
        "trade_quality_class_distribution": class_counts,
        "exit_reason_distribution": reason_counts,
    }
