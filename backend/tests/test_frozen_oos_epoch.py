"""The protected OOS holdout is FROZEN (spec phase 15): its range and fingerprint never change as candles arrive,
its slice is integrity-checked on every load, it is write-once, provenance-complete, and only an explicit reasoned
operator action replaces it."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.models.market import MarketCandle
from app.models.research import ImmutableResearchRecordError, OosEvaluation, ResearchEpoch
from app.research import dataset as ds
from app.research.lockbox import OosAlreadyConsumedError, OosLineageExhaustedError, evaluate_oos_once
from tests.helpers_agents import make_agents
from tests.test_backtest_parity import candles as make_candles, ema_cross_dna

BACKEND = Path(__file__).resolve().parents[1]


async def _store(db, frame, *, start=0):
    db.add_all([MarketCandle(symbol="SOL", timeframe="1m", open_time=int(r.open_time), close_time=int(r.open_time) + 59_999,
                             open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
                             volume=float(r.volume), is_final=True) for r in frame.itertuples()])
    await db.commit()


def _frame(n=1400, seed=21):
    return make_candles(n, seed=seed, drift=0.01)


async def _sealed(db, n=1400):
    c = _frame(n)
    await _store(db, c)
    epoch = await ds.seal_epoch(db, c, symbol="SOL", timeframe="1m", reason="initial")
    await db.commit()
    return c, epoch


# --- the holdout does not move --------------------------------------------------------------------------------------


async def test_epoch_fingerprint_and_frame_are_stable_while_new_candles_arrive(db_session):
    c, epoch = await _sealed(db_session)
    fp, oos_start, oos_end = epoch.dataset_fingerprint, epoch.oos_start_ms, epoch.oos_end_ms
    frame_before = await ds.load_epoch_candles(db_session, epoch)

    later = make_candles(1900, seed=21, drift=0.01).iloc[1400:]          # 500 NEW candles after the seal
    await _store(db_session, later)

    active = await ds.get_active_epoch(db_session, "SOL", "1m")
    assert active.epoch_id == epoch.epoch_id and active.dataset_fingerprint == fp       # ... the fingerprint did not change
    assert (active.oos_start_ms, active.oos_end_ms) == (oos_start, oos_end)
    frame_after = await ds.load_epoch_candles(db_session, active)
    assert ds.fingerprint_frame(frame_after) == ds.fingerprint_frame(frame_before)     # ... and the loaded frame is identical
    assert int(frame_after["open_time"].max()) == oos_end                               # newer bars are NOT in the holdout frame
    again, created = await ds.get_or_create_epoch(db_session, make_candles(1900, seed=5), symbol="SOL", timeframe="1m")
    assert not created and again.epoch_id == epoch.epoch_id


async def test_train_and_validation_are_strictly_before_the_sealed_oos_range(db_session):
    c, epoch = await _sealed(db_session)
    frame = await ds.load_epoch_candles(db_session, epoch)
    tv = ds.slice_train_validation(frame, epoch)
    assert int(tv["open_time"].max()) == epoch.validation_end_ms < epoch.oos_start_ms
    assert epoch.train_end_ms < epoch.validation_end_ms
    assert int(frame["open_time"].iloc[-1]) == epoch.oos_end_ms == epoch.end_ms


async def test_a_revised_or_missing_oos_candle_is_detected_never_silently_evaluated(db_session):
    c, epoch = await _sealed(db_session)
    last = (await db_session.execute(select(MarketCandle).where(MarketCandle.open_time == epoch.oos_end_ms))).scalar_one()
    original_close = last.close
    last.close = original_close * 1.5
    await db_session.commit()
    with pytest.raises(ds.EpochIntegrityError, match="fingerprint"):
        await ds.load_epoch_candles(db_session, epoch)
    last.close = original_close
    await db_session.commit()
    await ds.load_epoch_candles(db_session, epoch)                                        # restored: fine again
    await db_session.delete(last)
    await db_session.commit()
    with pytest.raises(ds.EpochIntegrityError, match="sealed"):
        await ds.load_epoch_candles(db_session, epoch)


# --- operator-only renewal ---------------------------------------------------------------------------------------------


async def test_renewal_requires_a_reason_and_supersedes_without_touching_history(db_session):
    c, epoch = await _sealed(db_session)
    with pytest.raises(ValueError, match="reason"):
        await ds.renew_epoch(db_session, _frame(1500, seed=9), symbol="SOL", timeframe="1m", reason="   ")
    new = await ds.renew_epoch(db_session, _frame(1500, seed=9), symbol="SOL", timeframe="1m", reason="monthly refresh")
    await db_session.commit()
    await db_session.refresh(epoch)
    assert new.active and new.supersedes_epoch_id == epoch.epoch_id and new.renewal_reason == "monthly refresh"
    assert epoch.active is False and epoch.superseded_at is not None
    assert epoch.oos_fingerprint == epoch.dataset_fingerprint                          # the old holdout is untouched
    assert (await ds.get_active_epoch(db_session, "SOL", "1m")).epoch_id == new.epoch_id


# --- immutability: ORM guard AND real database triggers --------------------------------------------------------------


async def test_sealed_columns_cannot_be_edited_or_the_epoch_deleted(db_session):
    c, epoch = await _sealed(db_session)
    epoch.oos_end_ms += 60_000
    with pytest.raises(ImmutableResearchRecordError, match="oos_end_ms"):
        await db_session.flush()
    await db_session.rollback()
    await db_session.refresh(epoch)
    await db_session.delete(epoch)
    with pytest.raises(ImmutableResearchRecordError, match="never be deleted"):
        await db_session.flush()
    await db_session.rollback()


async def test_an_oos_evaluation_is_write_once(db_session):
    c, epoch = await _sealed(db_session)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    from app.models.strategy import StrategyVersion
    version = await db_session.get(StrategyVersion, agent.strategy_version_id)
    row = await evaluate_oos_once(db_session, version, epoch, c)
    await db_session.commit()
    row.oos_score = 0.99                                    # "improve" a consumed result
    with pytest.raises(ImmutableResearchRecordError, match="write-once"):
        await db_session.flush()
    await db_session.rollback()
    await db_session.refresh(row)
    await db_session.delete(row)
    with pytest.raises(ImmutableResearchRecordError):
        await db_session.flush()
    await db_session.rollback()


def _insert(con, table, **values):
    """INSERT that fills every other NOT NULL column (without a default) with a type-appropriate dummy value."""
    cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(values)
    for _cid, name, ctype, notnull, default, _pk in cols:
        if name in row or not notnull or default is not None:
            continue
        t = (ctype or "").upper()
        row[name] = 0 if any(k in t for k in ("INT", "FLOAT", "REAL", "NUMERIC", "BOOL")) else ("{}" if "JSON" in t else
                    (datetime.now(timezone.utc).isoformat() if "DATE" in t else ""))
    keys = ", ".join(row)
    con.execute(f"INSERT INTO {table} ({keys}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))


def test_database_triggers_enforce_the_same_rules_in_the_migrated_schema(tmp_path):
    """The ORM guard is not the authority: the migration installs triggers, so raw SQL cannot rewrite the holdout either."""
    db = tmp_path / "t.db"
    import os
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db}")
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    now = datetime.now(timezone.utc).isoformat()
    _insert(con, "research_epochs", id="e1", epoch_id="EP1", symbol="SOL", timeframe="1m", start_ms=0, end_ms=100, n_candles=10,
            dataset_fingerprint="fp", train_end_ms=5, validation_end_ms=8, oos_locked=1, oos_start_ms=9, oos_end_ms=100,
            oos_fingerprint="fp", active=1)
    con.commit()
    with pytest.raises(sqlite3.DatabaseError, match="sealed"):
        con.execute("UPDATE research_epochs SET oos_end_ms = 999 WHERE id='e1'")
    con.execute("UPDATE research_epochs SET active = 0 WHERE id='e1'")            # superseding IS allowed
    with pytest.raises(sqlite3.DatabaseError, match="never be deleted"):
        con.execute("DELETE FROM research_epochs WHERE id='e1'")
    _insert(con, "experiments", id="x1", experiment_id="EXP1", kind="oos", status="RUNNING", code_version="c",
            schema_version="s", random_seed=1)
    with pytest.raises(sqlite3.DatabaseError, match="never be deleted"):
        con.execute("DELETE FROM experiments WHERE id='x1'")
    _insert(con, "strategies", id="s1", code="C1", family="MOMENTUM", name="n")
    _insert(con, "strategy_versions", id="v1", strategy_id="s1", version=1, generation=1, dna="{}", stage="PAPER")
    _insert(con, "oos_evaluations", id="o1", strategy_version_id="v1", dataset_fingerprint="fp", experiment_id="EXP1", oos_score=0.5)
    with pytest.raises(sqlite3.DatabaseError, match="write-once"):
        con.execute("UPDATE oos_evaluations SET oos_score = 1.0 WHERE id='o1'")
    with pytest.raises(sqlite3.DatabaseError, match="write-once"):
        con.execute("DELETE FROM oos_evaluations WHERE id='o1'")
    con.close()


# --- lineage cap + provenance ----------------------------------------------------------------------------------------------


async def test_a_lineage_cannot_be_tuned_against_the_same_holdout_indefinitely(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "research_oos_max_evaluations_per_lineage", 2)
    c, epoch = await _sealed(db_session)
    from app.models.strategy import Strategy, StrategyVersion
    from app.models.enums import StrategyFamily
    root_agents = await make_agents(db_session, [ema_cross_dna(5, 20), ema_cross_dna(6, 21), ema_cross_dna(7, 22), ema_cross_dna(8, 25)])
    versions = [await db_session.get(StrategyVersion, a.strategy_version_id) for a in root_agents]
    strategies = [await db_session.get(Strategy, v.strategy_id) for v in versions]
    for st in strategies[:3]:                                # three descendants of ONE lineage; the fourth is unrelated
        st.lineage_id = strategies[0].id
    await db_session.commit()
    v3_id, epoch_pk = versions[3].id, epoch.id            # capture ids before any rollback expires the objects
    await evaluate_oos_once(db_session, versions[0], epoch, c)
    await evaluate_oos_once(db_session, versions[1], epoch, c)
    await db_session.commit()
    with pytest.raises(OosLineageExhaustedError, match="lineage"):
        await evaluate_oos_once(db_session, versions[2], epoch, c)
    assert issubclass(OosLineageExhaustedError, OosAlreadyConsumedError)      # the pipeline's existing handler covers it
    await db_session.rollback()
    v3 = await db_session.get(StrategyVersion, v3_id)
    epoch = await db_session.get(ResearchEpoch, epoch_pk)
    await evaluate_oos_once(db_session, v3, epoch, c)                          # another lineage still has its own quota


async def test_oos_evaluation_records_full_provenance(db_session):
    c, epoch = await _sealed(db_session)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    from app.models.strategy import StrategyVersion
    version = await db_session.get(StrategyVersion, agent.strategy_version_id)
    row = await evaluate_oos_once(db_session, version, epoch, c, seed=4242)
    await db_session.commit()
    p = row.provenance
    assert row.random_seed == 4242 and row.code_version and row.lineage_id is not None
    assert p["epoch_id"] == epoch.epoch_id and p["oos_fingerprint"] == epoch.oos_fingerprint
    assert p["train_period"] == {"start_ms": epoch.start_ms, "end_ms": epoch.train_end_ms}
    assert p["validation_period"] == {"start_ms": epoch.train_end_ms, "end_ms": epoch.validation_end_ms}
    assert p["oos_period"] == {"start_ms": epoch.oos_start_ms, "end_ms": epoch.oos_end_ms}
    assert p["engine_version"] and len(p["parameter_hash"]) == 64 and p["strategy_version_id"] == str(version.id)
    from app.models.research import Experiment
    exp = (await db_session.execute(select(Experiment).where(Experiment.experiment_id == row.experiment_id))).scalar_one()
    assert exp.engine_version == p["engine_version"] and exp.parameter_hash == p["parameter_hash"]
    assert exp.dataset_fingerprint == epoch.dataset_fingerprint and exp.random_seed == 4242


async def test_parameter_hash_changes_when_a_result_shaping_parameter_changes(monkeypatch):
    from app.research.registry import parameter_hash

    h = parameter_hash()
    monkeypatch.setattr(get_settings(), "paper_slippage_bps", get_settings().paper_slippage_bps + 1)
    assert parameter_hash() != h


# --- selection cannot see the protected period ------------------------------------------------------------------------------


async def test_paper_trades_overlapping_the_oos_window_never_feed_fitness(db_session):
    from app.analytics.fitness_service import compute_and_persist_agent_fitness
    from app.models.agent import Agent
    from app.models.enums import Side
    from app.models.trading import Trade
    from tests.helpers_agents import closed_position, make_dna

    a_in, a_out = await make_agents(db_session, [make_dna(), make_dna()])
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for agent, when in ((a_in, base), (a_out, base + timedelta(days=5))):
        db_session.add(Trade(agent_id=agent.id, position_id=closed_position(db_session, agent), symbol="SOL", side=Side.LONG,
                             quantity=1, entry_price=100, exit_price=110, gross_pnl=10, fees=0.1, net_pnl=9.9,
                             opened_at=when, closed_at=when + timedelta(minutes=5), holding_seconds=300, exit_reason="signal"))
    await db_session.commit()
    window = (int(base.timestamp() * 1000) - 1000, int((base + timedelta(hours=1)).timestamp() * 1000))    # covers a_in only
    await compute_and_persist_agent_fitness(db_session, generation=100, oos_window_ms=window)
    await db_session.commit()
    from app.models.metrics import PerformanceMetric
    counts = {m.agent_id: m.trade_count for m in (await db_session.execute(select(PerformanceMetric))).scalars().all()}
    assert counts[a_in.id] == 0 and counts[a_out.id] == 1
