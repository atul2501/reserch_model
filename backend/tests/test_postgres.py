"""PostgreSQL-specific checks (spec phases 19, 44). Skipped automatically when
no PostgreSQL server is reachable (set TEST_POSTGRES_ADMIN_URL, e.g.
postgresql://postgres@127.0.0.1:5432/postgres). Each test uses a throw-away database."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
ADMIN = os.environ.get("TEST_POSTGRES_ADMIN_URL", "postgresql://postgres@127.0.0.1:55432/postgres")


async def _reachable() -> bool:
    try:
        c = await asyncio.wait_for(asyncpg.connect(ADMIN), 2)
        await c.close()
        return True
    except Exception:
        return False


@pytest.fixture
async def pg_database():
    if not await _reachable():
        pytest.skip("no PostgreSQL server reachable for TEST_POSTGRES_ADMIN_URL")
    name = f"mig_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(ADMIN)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    base = ADMIN.rsplit("/", 1)[0].replace("postgresql://", "postgresql+asyncpg://")
    yield f"{base}/{name}"
    admin = await asyncpg.connect(ADMIN)
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.close()


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=url)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=240)


async def _drift(url: str):
    import app.models  # noqa: F401
    from app.core.database import Base

    engine = create_async_engine(url)
    async with engine.connect() as conn:
        diffs = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    await engine.dispose()
    out = []
    for d in diffs:
        for item in (d if isinstance(d, list) else [d]):
            if item[0] in ("add_table", "remove_table"):
                out.append((item[0], item[1].name))
            elif item[0] in ("add_column", "remove_column"):
                out.append((item[0], f"{item[2]}.{item[3].name}"))
            elif item[0] in ("add_index", "remove_index"):
                out.append((item[0], item[1].name))
    return out


async def test_full_migration_chain_applies_on_postgres_with_no_drift(pg_database):
    r = _alembic(pg_database, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-2000:]
    assert await _drift(pg_database) == []


async def test_downgrade_then_upgrade_round_trips_on_postgres(pg_database):
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    for _ in range(3):
        r = _alembic(pg_database, "downgrade", "-1")
        assert r.returncode == 0, r.stderr[-2000:]
    r = _alembic(pg_database, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-2000:]
    assert await _drift(pg_database) == []


async def test_legacy_rows_survive_migration_on_postgres(pg_database):
    assert _alembic(pg_database, "upgrade", "c2f0a1d4e901").returncode == 0
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    await conn.execute(
        "INSERT INTO worker_cycles (cycle_id, candle_timestamp, cycle_started_at, completed, id, created_at, updated_at) "
        "VALUES ('SOL:1m:1700000000000', 1700000000000, 1.0, true, $1, now(), now())", uuid.uuid4(),
    )
    await conn.close()
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    row = await conn.fetchrow("SELECT status, attempts FROM worker_cycles")
    await conn.close()
    assert (row["status"], row["attempts"]) == ("COMPLETED", 1)


async def test_partial_unique_open_position_index_exists_on_postgres(pg_database):
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    idx = await conn.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_position_one_open_per_agent'"
    )
    await conn.close()
    assert idx and "UNIQUE" in idx and "WHERE" in idx


async def test_snapshot_source_column_fits_its_own_documented_values_on_postgres(pg_database):
    """Regression for a real bug the migration dry run caught: the column was
    VARCHAR(12), but its own comment documents "reconstructed" (13 chars) as a
    legal value - invisible on SQLite (no length enforcement), a hard INSERT
    failure on Postgres."""
    assert _alembic(pg_database, "upgrade", "head").returncode == 0
    conn = await asyncpg.connect(pg_database.replace("postgresql+asyncpg://", "postgresql://"))
    max_len = await conn.fetchval(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = 'fitness_forward_performance' AND column_name = 'snapshot_source'"
    )
    await conn.close()
    assert max_len >= len("reconstructed")


def test_pool_settings_are_applied_for_postgres_urls():
    from app.core.config import Settings
    s = Settings(database_url="postgresql+asyncpg://u:p@h/db", database_pool_size=7, database_max_overflow=3)
    assert (s.database_pool_size, s.database_max_overflow) == (7, 3)
