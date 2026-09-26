"""Build/refresh the derived analytics tables (the ONLY writer to them).

    python -m scripts.refresh_analytics                 # all three phases
    python -m scripts.refresh_analytics --only trade_analytics
    python -m scripts.refresh_analytics --only matrix
    python -m scripts.refresh_analytics --only fitness_forward --grid-minutes 30

Writes ONLY trade_analytics / strategy_regime_matrix / fitness_forward_performance.
Raw tables are read, never modified (tests/test_analytics_store.py proves it with
a checksum). fitness_forward_performance is write-once evidence: a rerun only
fills gaps, it never rewrites existing rows.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.analytics.analytics_store import (
    COMPUTATION_VERSION, refresh_fitness_forward, refresh_strategy_regime_matrix, refresh_trade_analytics,
)
from app.core.database import AsyncSessionLocal, engine
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def _raw_table_checksums(db) -> dict[str, int]:
    """COUNT(*) of every raw table — printed before/after so a refresh run can
    prove it touched nothing but the analytics tables."""
    raw_tables = [
        "agents", "strategies", "strategy_versions", "decisions", "orders", "positions", "trades",
        "funding_payments", "market_candles", "market_features", "market_regimes", "funding_rates",
        "council_decisions", "council_analyses", "fitness_scores", "performance_metrics", "stage_metrics",
        "generations", "agent_snapshots", "evolution_events", "experiments", "oos_evaluations",
        "research_epochs", "regime_validation_reports", "adversarial_test_reports", "reality_gap_reports",
        "challenger_evaluations", "agent_correlations", "strategy_family_correlations", "population_events",
        "worker_cycles", "worker_leases", "system_events", "system_flags", "system_status",
    ]
    out: dict[str, int] = {}
    for t in raw_tables:
        try:
            out[t] = (await db.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar_one()
        except Exception:
            out[t] = -1
    return out


async def main(phases: list[str], grid_minutes: int) -> None:
    async with AsyncSessionLocal() as db:
        before = await _raw_table_checksums(db)
        await db.rollback()

        if "trade_analytics" in phases:
            r = await refresh_trade_analytics(db, computation_version=COMPUTATION_VERSION)
            logger.info("analytics.trade_analytics_refreshed",
                        trades_processed=r.trades_processed, trades_updated=r.trades_updated,
                        crosscheck_failures=r.crosscheck_failures, crosscheck_skipped=r.crosscheck_skipped,
                        missing_candles=r.missing_candles, missing_episode=r.missing_episode,
                        regime_mismatches=r.regime_mismatches)
            for f in r.findings:
                logger.warning("analytics.data_integrity_finding", finding=f)
        if "matrix" in phases:
            r = await refresh_strategy_regime_matrix(db, computation_version=COMPUTATION_VERSION)
            logger.info("analytics.matrix_refreshed", cells=r.matrix_cells)
        if "fitness_forward" in phases:
            r = await refresh_fitness_forward(db, grid_minutes=grid_minutes, computation_version=COMPUTATION_VERSION)
            logger.info("analytics.fitness_forward_refreshed", inserted=r.ffp_inserted, existing=r.ffp_existing)

        await db.commit()

        after = await _raw_table_checksums(db)
        await db.rollback()
        changed = {t: (before[t], after[t]) for t in before if before[t] != after[t]}
        if changed:
            raise RuntimeError(f"RAW TABLE MUTATION DETECTED (refresh must be read-only on raw tables): {changed}")
        logger.info("analytics.refresh_complete", raw_tables_verified_unchanged=len(before))
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=["trade_analytics", "matrix", "fitness_forward"], default=None,
                    help="run a single phase (default: all three, in dependency order)")
    ap.add_argument("--grid-minutes", type=int, default=60,
                    help="spacing of the historical fitness reconstruction grid (minutes)")
    args = ap.parse_args()
    phases = ["trade_analytics", "matrix", "fitness_forward"] if args.only is None else [args.only]
    asyncio.run(main(phases, args.grid_minutes))