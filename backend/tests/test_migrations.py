"""Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema
in sync with the ORM models (no drift), (c) round-trip downgrade -> upgrade,
(d) preserve pre-existing historical rows."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db_path}")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180
    )


def _structural_diffs(db_path: Path) -> list[tuple[str, str]]:
    """Missing/extra tables and columns between the migrated DB and the ORM."""
    import app.models  # noqa: F401
    from app.core.database import Base

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    found: list[tuple[str, str]] = []
    for d in diffs:
        for item in (d if isinstance(d, list) else [d]):
            kind = item[0]
            if kind in ("add_table", "remove_table"):
                found.append((kind, item[1].name))
            elif kind in ("add_column", "remove_column"):
                found.append((kind, f"{item[2]}.{item[3].name}"))
    return found


def test_upgrade_head_has_no_structural_drift(tmp_path):
    db = tmp_path / "mig.db"
    r = _alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    assert _structural_diffs(db) == []


def test_downgrade_then_upgrade_round_trips(tmp_path):
    db = tmp_path / "mig.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    r = _alembic(db, "downgrade", "-1")
    assert r.returncode == 0, r.stderr
    r = _alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    assert _structural_diffs(db) == []


def test_upgrade_preserves_historical_worker_cycles(tmp_path):
    db = tmp_path / "mig.db"
    # Migrate to the revision before T1, insert a legacy row, then upgrade.
    assert _alembic(db, "upgrade", "c2f0a1d4e901").returncode == 0
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO worker_cycles (cycle_id, candle_timestamp, cycle_started_at, completed, id, created_at, updated_at)"
        " VALUES ('SOL:1m:1', 1, 1.0, 1, 'a'*1, '2026-01-01', '2026-01-01')".replace("'a'*1", "'00000000000000000000000000000001'")
    )
    con.commit()
    con.close()
    assert _alembic(db, "upgrade", "head").returncode == 0
    con = sqlite3.connect(db)
    row = con.execute("SELECT cycle_id, status FROM worker_cycles").fetchone()
    con.close()
    assert row == ("SOL:1m:1", "COMPLETED")


def test_drift_detector_actually_detects_drift(tmp_path):
    db = tmp_path / "mig.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    con = sqlite3.connect(db)
    con.execute("DROP TABLE funding_rates")
    con.commit()
    con.close()
    assert ("add_table", "funding_rates") in _structural_diffs(db)
