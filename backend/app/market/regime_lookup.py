"""Shared regime-at-timestamp lookup, extracted from
`app/api/routes/trades.py::get_regime_performance` so RegimeValidationEngine
can reuse the exact same bisect logic instead of a second implementation.

Trade.exit_regime is never actually populated by the live trading engine
(it evaluates fills live rather than stamping a regime onto the row), so
this reconstructs it: for a given timestamp, find the most recent
MarketRegimeRecord at or before that moment.
"""
from __future__ import annotations

import bisect

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import MarketRegimeRecord


async def load_regime_lookup(db: AsyncSession) -> tuple[list[int], list[str]]:
    """Returns (open_times, regimes) sorted ascending by candle_open_time —
    pass both into `regime_at` for every timestamp you need to resolve,
    rather than re-querying per trade."""
    regime_rows = (
        await db.execute(
            select(MarketRegimeRecord.candle_open_time, MarketRegimeRecord.regime).order_by(
                MarketRegimeRecord.candle_open_time
            )
        )
    ).all()
    open_times = [row[0] for row in regime_rows]
    regimes = [row[1].value for row in regime_rows]
    return open_times, regimes


def regime_at(closed_at_ms: int, open_times: list[int], regimes: list[str]) -> str:
    """The most recent regime classified at or before `closed_at_ms`, or
    "UNKNOWN" if no regime record exists yet at or before that moment."""
    if not open_times:
        return "UNKNOWN"
    idx = bisect.bisect_right(open_times, closed_at_ms) - 1
    return regimes[idx] if idx >= 0 else "UNKNOWN"
