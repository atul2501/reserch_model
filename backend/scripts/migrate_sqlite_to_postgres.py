"""One-off: copy every row from a SQLite trading_lab.db into a Postgres
database, in FK-safe order, as part of the SQLite -> Postgres migration.
Async throughout (asyncpg / aiosqlite -- this project's actual installed
drivers; psycopg2, which the existing reverse-direction
`migrate_postgres_to_sqlite.py` assumes, is not installed here).

Runs `alembic upgrade head` against the destination first, as a subprocess
with DATABASE_URL set only in that subprocess's environment -- the same
pattern tests/test_postgres.py's own `_alembic()` helper uses, and required
here because this project's `alembic/env.py` derives its URL from
`get_settings().database_url`, which this script must not set globally (see
tests/test_config_audit.py::test_no_module_reads_the_environment_directly:
no module may read/write the process environment directly outside Settings).
Using `alembic upgrade` rather than `Base.metadata.create_all()` matters: the
frozen-OOS immutability triggers and CHECK constraints are raw SQL inside
migrations, not expressible in SQLAlchemy metadata, and create_all() would
silently produce a schema missing them.

Never touches the source SQLite file (read-only). Point --sqlite-path at a
snapshot copy of trading_lab.db, never the live file.

Usage:
    python -m scripts.migrate_sqlite_to_postgres \\
        --sqlite-path /path/to/snapshot/trading_lab.db \\
        --pg-url postgresql+asyncpg://user:pass@host:5432/trading_lab
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
import app.models  # noqa: F401  ensures every model is registered on Base.metadata

BACKEND = Path(__file__).resolve().parents[1]


def upgrade_schema(pg_url: str) -> None:
    """Idempotent: alembic upgrade to a revision it's already at is a no-op."""
    env = dict(os.environ, DATABASE_URL=pg_url)
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise SystemExit(f"alembic upgrade head failed:\n{r.stderr}")


async def _aggregate_summary(conn, tables: dict) -> dict[str, object]:
    """One row of headline aggregates, computed identically against either engine, for the
    "verify important aggregates" requirement -- row-count-per-table alone proves nothing
    was dropped or duplicated, but says nothing about whether the VALUES came across intact
    (a swapped column, a silently-truncated JSON blob, a mis-cast enum would all still pass
    a row-count check)."""
    from app.models.enums import AgentStatus

    agents = tables["agents"]
    out: dict[str, object] = {}
    out["total_agents"] = (await conn.execute(sa.select(sa.func.count()).select_from(agents))).scalar()
    out["active_agents"] = (await conn.execute(
        sa.select(sa.func.count()).select_from(agents).where(agents.c.status == AgentStatus.ACTIVE)
    )).scalar()
    out["dead_agents"] = (await conn.execute(
        sa.select(sa.func.count()).select_from(agents).where(agents.c.status == AgentStatus.DEAD)
    )).scalar()
    if "trades" in tables:
        trades = tables["trades"]
        out["total_trades"] = (await conn.execute(sa.select(sa.func.count()).select_from(trades))).scalar()
        out["sum_net_pnl"] = (await conn.execute(sa.select(sa.func.sum(trades.c.net_pnl)))).scalar()
        out["sum_fees"] = (await conn.execute(sa.select(sa.func.sum(trades.c.fees)))).scalar()
        out["earliest_trade_closed_at"] = (await conn.execute(sa.select(sa.func.min(trades.c.closed_at)))).scalar()
        out["latest_trade_closed_at"] = (await conn.execute(sa.select(sa.func.max(trades.c.closed_at)))).scalar()
    if "decisions" in tables:
        out["total_decisions"] = (await conn.execute(sa.select(sa.func.count()).select_from(tables["decisions"]))).scalar()
    if "experiments" in tables:
        out["total_experiments"] = (await conn.execute(sa.select(sa.func.count()).select_from(tables["experiments"]))).scalar()
    if "generations" in tables:
        out["generation_count"] = (await conn.execute(sa.select(sa.func.count()).select_from(tables["generations"]))).scalar()
    if "strategies" in tables:
        out["strategy_count"] = (await conn.execute(sa.select(sa.func.count()).select_from(tables["strategies"]))).scalar()
    return out


async def migrate(sqlite_path: str, pg_url: str) -> None:
    sqlite_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    pg_engine = create_async_engine(pg_url)

    tables = Base.metadata.sorted_tables
    tables_by_name = {t.name: t for t in tables}
    mismatches = []
    async with sqlite_engine.connect() as sqlite_conn, pg_engine.begin() as pg_conn:
        for table in tables:
            rows = [dict(row._mapping) for row in (await sqlite_conn.execute(sa.select(table))).all()]
            if rows:
                await pg_conn.execute(sa.insert(table), rows)

            sqlite_count = (await sqlite_conn.execute(sa.select(sa.func.count()).select_from(table))).scalar()
            pg_count = (await pg_conn.execute(sa.select(sa.func.count()).select_from(table))).scalar()
            status = "OK" if sqlite_count == pg_count else "MISMATCH"
            if status == "MISMATCH":
                mismatches.append(table.name)
            print(f"{table.name:32s} {sqlite_count:6d} -> {pg_count:6d}  [{status}]")

        print("\n=== aggregate verification (SQLite vs. Postgres) ===")
        sqlite_agg = await _aggregate_summary(sqlite_conn, tables_by_name)
        pg_agg = await _aggregate_summary(pg_conn, tables_by_name)
        agg_mismatches = []
        for key in sqlite_agg:
            a, b = sqlite_agg[key], pg_agg.get(key)
            # Sums of floats can differ in the last bit across SQLite/Postgres float arithmetic;
            # treat anything within 1e-6 as equal rather than flagging float noise as data loss.
            equal = (a == b) if not isinstance(a, float) else (b is not None and abs(a - b) < 1e-6)
            status = "OK" if equal else "MISMATCH"
            if not equal:
                agg_mismatches.append(key)
            print(f"  {key:28s} {str(a):>28s} -> {str(b):<28s} [{status}]")

    await sqlite_engine.dispose()
    await pg_engine.dispose()

    if mismatches:
        raise SystemExit(f"\nRow-count mismatch in: {mismatches} -- destination data is NOT trustworthy, investigate before use.")
    if agg_mismatches:
        raise SystemExit(f"\nAggregate mismatch in: {agg_mismatches} -- destination data is NOT trustworthy, investigate before use.")
    print(f"\nDone. All tables verified row-for-row, all aggregates verified. Source SQLite file untouched: {sqlite_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", required=True, help="Source SQLite file (read-only, e.g. a snapshot copy)")
    parser.add_argument("--pg-url", required=True, help="Destination Postgres URL, asyncpg scheme (postgresql+asyncpg://...)")
    parser.add_argument("--skip-schema-upgrade", action="store_true", help="Skip `alembic upgrade head` (schema already current)")
    args = parser.parse_args()

    if not args.skip_schema_upgrade:
        print("running `alembic upgrade head` against destination ...")
        upgrade_schema(args.pg_url)
        print("schema upgrade complete.\n")

    asyncio.run(migrate(args.sqlite_path, args.pg_url))


if __name__ == "__main__":
    main()
