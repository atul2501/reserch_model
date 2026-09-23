"""Reclaim space taken by legacy "nothing happened" decision rows.

Before the fix, every agent wrote a `decisions` row on every candle (500 agents x 1/min
= ~720k rows/day), 99% of them "no signal / holding", each carrying a ~1.4 KB copy of the
market snapshot (which already lives once per candle in `market_features`).

    python -m scripts.prune_decisions --dry-run                 # count only
    python -m scripts.prune_decisions                           # delete no-op rows older than DECISION_RETENTION_DAYS
    python -m scripts.prune_decisions --older-than-days 0 --strip-context --vacuum
                                                                # one-time cleanup + reclaim disk

SAFETY: rows linked to an order or a trade are never touched. Deletion is batched so WAL and
lock time stay small. `--vacuum` needs the worker STOPPED (SQLite: exclusive; PostgreSQL:
VACUUM FULL takes an exclusive lock). Always take a backup/dump first.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, delete, func, or_, select, text, update
from sqlalchemy import null as sa_null
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, engine
from app.core.logging import configure_logging, get_logger
from app.models.decision import Decision

logger = get_logger(__name__)

# The "skipped" markers written by the legacy no-op paths (JSON spacing differs per dialect,
# so match on the bare token rather than on a formatted key/value).
NOOP_MARKERS = ("no_entry_signal_or_position_open", "position_open_holding")


def _noop_filter(cutoff: datetime):
    reasoning_text = cast(Decision.risk_reasoning, String)
    return (
        Decision.order_id.is_(None),
        Decision.trade_id.is_(None),
        Decision.created_at < cutoff,
        or_(*[reasoning_text.like(f"%{m}%") for m in NOOP_MARKERS]),
    )


async def count_noop(db: AsyncSession, cutoff: datetime) -> tuple[int, int]:
    total = (await db.execute(select(func.count()).select_from(Decision))).scalar_one()
    noop = (await db.execute(select(func.count()).select_from(Decision).where(*_noop_filter(cutoff)))).scalar_one()
    return total, noop


async def prune_noop_decisions(db: AsyncSession, cutoff: datetime, *, batch_size: int = 20_000) -> int:
    """Deletes no-op rows older than `cutoff` in batches. Returns rows deleted."""
    deleted = 0
    while True:
        ids = (await db.execute(select(Decision.id).where(*_noop_filter(cutoff)).limit(batch_size))).scalars().all()
        if not ids:
            return deleted
        await db.execute(delete(Decision).where(Decision.id.in_(ids)))
        await db.commit()
        deleted += len(ids)
        logger.info("prune_decisions.batch", deleted_total=deleted)


async def strip_context(db: AsyncSession, *, batch_size: int = 20_000) -> int:
    """Nulls the duplicated market_context on every remaining row (batched)."""
    stripped = 0
    while True:
        ids = (
            await db.execute(select(Decision.id).where(Decision.market_context.is_not(None)).limit(batch_size))
        ).scalars().all()
        if not ids:
            return stripped
        await db.execute(update(Decision).where(Decision.id.in_(ids)).values(market_context=sa_null()))
        await db.commit()
        stripped += len(ids)


async def vacuum() -> None:
    """Return freed pages to the OS. Runs outside a transaction; needs exclusive access."""
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        if engine.dialect.name == "postgresql":
            await conn.execute(text("VACUUM (FULL, ANALYZE) decisions"))
        else:
            await conn.execute(text("VACUUM"))


async def main(*, dry_run: bool, older_than_days: int | None, do_strip: bool, do_vacuum: bool) -> None:
    configure_logging()
    days = get_settings().decision_retention_days if older_than_days is None else older_than_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        total, noop = await count_noop(db, cutoff)
        logger.info("prune_decisions.plan", total_rows=total, prunable_noop_rows=noop, older_than_days=days, dry_run=dry_run)
        if dry_run:
            return
        deleted = await prune_noop_decisions(db, cutoff)
        stripped = await strip_context(db) if do_strip else 0
        logger.info("prune_decisions.done", deleted=deleted, context_stripped=stripped)
    if do_vacuum:
        await vacuum()
        logger.info("prune_decisions.vacuumed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--older-than-days", type=int, default=None, help="default: DECISION_RETENTION_DAYS")
    ap.add_argument("--strip-context", action="store_true", help="null the duplicated market_context on remaining rows")
    ap.add_argument("--vacuum", action="store_true", help="reclaim disk (worker must be stopped)")
    a = ap.parse_args()
    asyncio.run(main(dry_run=a.dry_run, older_than_days=a.older_than_days, do_strip=a.strip_context, do_vacuum=a.vacuum))
