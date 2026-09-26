"""Migration-level analytics guarantees: the evidence table is write-once at the
DATABASE level too (SQLite triggers), and the additive indexes exist."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db_path}")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180
    )


@pytest.fixture
def migrated_db(tmp_path):
    db = tmp_path / "analytics.db"
    r = _alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr
    return db


def test_ffp_write_once_triggers_exist(migrated_db):
    con = sqlite3.connect(migrated_db)
    triggers = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    con.close()
    assert "fitness_forward_performance_no_update" in triggers
    assert "fitness_forward_performance_no_delete" in triggers


def _insert_ffp_row(con: sqlite3.Connection) -> None:
    """Minimal valid parent chain (strategies -> strategy_versions -> agents) + one evidence row."""
    ts = "2026-01-01 00:00:00"
    con.execute("PRAGMA foreign_keys=ON")
    con.execute(
        "INSERT INTO strategies (id, code, family, name, description, created_at, updated_at)"
        " VALUES ('s', 'S1', 'momentum', 'S', 'd', ?, ?)", (ts, ts)
    )
    con.execute(
        "INSERT INTO strategy_versions (id, strategy_id, version, generation, dna, stage, hypothesis,"
        " proposed_by, created_at, updated_at) VALUES ('v', 's', 1, 1, '{}', 'PAPER', 'h', 'test', ?, ?)",
        (ts, ts),
    )
    con.execute(
        "INSERT INTO agents (id, identifier, generation, strategy_version_id, status, starting_balance, balance,"
        " equity, realized_pnl, fees_paid, funding_paid, peak_equity, max_drawdown, day_start_equity,"
        " day_start_date, trade_count, is_professional, best_milestone_multiple, created_at, updated_at,"
        " daily_trade_count, bad_debt)"
        " VALUES ('a', 'A', 1, 'v', 'ACTIVE', 100, 100, 100, 0, 0, 0, 100, 0, 100, '2026-01-01', 0, 0, 1,"
        " ?, ?, 0, 0)", (ts, ts)
    )
    con.execute(
        "INSERT INTO fitness_forward_performance (id, agent_id, snapshot_source, as_of, fitness_at_t,"
        " fitness_components_at_t, horizon_minutes, window_start, window_end_planned, window_end_actual,"
        " censor_reason, window_coverage, future_trade_count, computation_version, computed_at, created_at,"
        " updated_at)"
        " VALUES ('f', 'a', 'recorded', ?, 1.0, '{}', 60, ?, ?, ?, 'none', 1.0, 0, 'v1', ?, ?, ?)",
        (ts, ts, ts, ts, ts, ts, ts),
    )


def test_ffp_database_trigger_blocks_update_and_delete(migrated_db):
    con = sqlite3.connect(migrated_db)
    _insert_ffp_row(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE fitness_forward_performance SET fitness_at_t = 99 WHERE id = 'f'")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM fitness_forward_performance WHERE id = 'f'")
    con.close()


def test_analytics_indexes_created(migrated_db):
    con = sqlite3.connect(migrated_db)
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    con.close()
    expected = {
        "uq_trade_analytics_trade", "ix_trade_analytics_agent", "ix_trade_analytics_family_regime",
        "ix_trade_analytics_regime", "ix_trade_analytics_version", "ix_trade_analytics_class",
        "uq_srm_cell", "ix_srm_dim", "uq_ffp_agent_asof_horizon", "ix_ffp_asof_horizon",
        "ix_trades_position", "ix_fitness_scores_agent_asof", "ix_fitness_scores_asof",
    }
    missing = expected - names
    assert not missing, f"missing indexes: {missing}"


def test_downgrade_drops_analytics_tables(migrated_db):
    # Target the revision by name, not "-1": head has since gained c1d5e9a3f7b2
    # (a later, unrelated column-width fix) on top of the analytics-foundation
    # migration this test is actually about, so "-1" from head no longer means
    # "undo the analytics migration".
    r = _alembic(migrated_db, "downgrade", "b7d1f3a9c5e2")
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(migrated_db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "trade_analytics" not in tables
    assert "strategy_regime_matrix" not in tables
    assert "fitness_forward_performance" not in tables