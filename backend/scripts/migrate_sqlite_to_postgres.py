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


async def migrate(sqlite_path: str, pg_url: str) -> None:
    sqlite_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    pg_engine = create_async_engine(pg_url)

    tables = Base.metadata.sorted_tables
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

    await sqlite_engine.dispose()
    await pg_engine.dispose()

    if mismatches:
        raise SystemExit(f"\nRow-count mismatch in: {mismatches} -- destination data is NOT trustworthy, investigate before use.")
    print(f"\nDone. All tables verified row-for-row. Source SQLite file untouched: {sqlite_path}")


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
