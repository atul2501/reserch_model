"""One-off: copy every row from the live Postgres database into a fresh
SQLite file, in FK-safe order, as part of the Postgres -> SQLite migration.

Not part of the running app — run once, by hand, before cutting the app's
config over to SQLite (while `psycopg2`/`asyncpg` are still installed and
Postgres is still reachable).

Usage:
    python -m scripts.migrate_postgres_to_sqlite
    python -m scripts.migrate_postgres_to_sqlite --pg-url postgresql://... --sqlite-path ./trading_lab.db
"""
from __future__ import annotations

import argparse

import sqlalchemy as sa

from app.core.config import get_settings
from app.core.database import Base
import app.models  # noqa: F401  ensures every model is registered on Base.metadata


def migrate(pg_url: str, sqlite_path: str) -> None:
    pg_engine = sa.create_engine(pg_url)
    sqlite_engine = sa.create_engine(f"sqlite:///{sqlite_path}")

    Base.metadata.create_all(sqlite_engine)

    tables = Base.metadata.sorted_tables
    with pg_engine.connect() as pg_conn, sqlite_engine.begin() as sqlite_conn:
        for table in tables:
            rows = [dict(row._mapping) for row in pg_conn.execute(sa.select(table))]
            if rows:
                sqlite_conn.execute(sa.insert(table), rows)

            pg_count = pg_conn.execute(sa.select(sa.func.count()).select_from(table)).scalar()
            sqlite_count = sqlite_conn.execute(sa.select(sa.func.count()).select_from(table)).scalar()
            status = "OK" if pg_count == sqlite_count else "MISMATCH"
            print(f"{table.name:24s} {pg_count:6d} -> {sqlite_count:6d}  [{status}]")

    pg_engine.dispose()
    sqlite_engine.dispose()
    print(f"\nDone. SQLite database written to {sqlite_path}")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-url", default=settings.database_url_sync, help="Source Postgres URL (sync, psycopg2)")
    parser.add_argument("--sqlite-path", default="./trading_lab.db", help="Destination SQLite file path")
    args = parser.parse_args()

    migrate(args.pg_url, args.sqlite_path)


if __name__ == "__main__":
    main()
