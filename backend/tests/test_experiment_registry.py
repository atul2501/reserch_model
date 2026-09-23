"""Experiment registry + dataset fingerprints (spec phase 23)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.models.research import Experiment, ResearchEpoch
from app.research import dataset as ds
from app.research.registry import code_version, register_experiment, schema_version


def frame(n=1000, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame({"open_time": np.arange(n) * 60_000 + 1_700_000_040_000, "open": close - 0.05, "high": close + 0.2,
                         "low": close - 0.2, "close": close, "volume": rng.uniform(500, 1500, n)})


def test_fingerprint_is_deterministic_and_content_sensitive():
    a = frame(seed=1)
    assert ds.fingerprint_frame(a) == ds.fingerprint_frame(a.copy())
    b = a.copy()
    b.loc[500, "close"] += 0.01
    assert ds.fingerprint_frame(a) != ds.fingerprint_frame(b)
    assert len(ds.fingerprint_frame(a)) == 64


async def test_epoch_is_frozen_chronologically_and_idempotent(db_session):
    c = frame()
    epoch, created = await ds.get_or_create_epoch(db_session, c, symbol="SOL", timeframe="1m")
    again, created2 = await ds.get_or_create_epoch(db_session, c.copy(), symbol="SOL", timeframe="1m")
    assert created and not created2 and again.id == epoch.id
    assert epoch.start_ms < epoch.train_end_ms < epoch.validation_end_ms < epoch.end_ms
    assert epoch.oos_locked and epoch.n_candles == 1000
    # 60/20/20 by default
    n_train = int((c["open_time"] <= epoch.train_end_ms).sum())
    n_val = int(((c["open_time"] > epoch.train_end_ms) & (c["open_time"] <= epoch.validation_end_ms)).sum())
    assert (n_train, n_val) == (600, 200)


async def test_different_data_gets_a_different_epoch(db_session):
    e1, _ = await ds.get_or_create_epoch(db_session, frame(seed=1), symbol="SOL", timeframe="1m")
    e2, _ = await ds.get_or_create_epoch(db_session, frame(seed=2), symbol="SOL", timeframe="1m")
    assert e1.epoch_id != e2.epoch_id and e1.dataset_fingerprint != e2.dataset_fingerprint


async def test_experiment_records_all_required_provenance(db_session):
    epoch, _ = await ds.get_or_create_epoch(db_session, frame(), symbol="SOL", timeframe="1m")
    exp = await register_experiment(db_session, kind="evolution", seed=1234, parameters={"survivor_fraction": 0.2},
                                    epoch=epoch, generation=3)
    await db_session.commit()
    row = (await db_session.execute(select(Experiment).where(Experiment.id == exp.id))).scalar_one()
    assert row.experiment_id.startswith("EXP-EVOL-")
    assert row.dataset_fingerprint == epoch.dataset_fingerprint and row.epoch_id == epoch.epoch_id
    assert row.train_period == {"start_ms": epoch.start_ms, "end_ms": epoch.train_end_ms}
    assert row.validation_period["end_ms"] == epoch.validation_end_ms and row.oos_period["end_ms"] == epoch.end_ms
    assert row.parameters == {"survivor_fraction": 0.2} and row.random_seed == 1234 and row.generation == 3
    assert row.code_version and row.schema_version and row.created_at is not None


def test_code_and_schema_versions_are_resolved():
    assert code_version() not in ("", None)
    assert schema_version() == "c6f3a1b8d5e2"    # alembic head shipped with this code


async def test_confirmed_only_loader_never_returns_open_bars(db_session):
    from app.models.market import MarketCandle
    rows = [MarketCandle(symbol="SOL", timeframe="1m", open_time=i * 60_000, close_time=i * 60_000 + 59_999, open=1, high=1, low=1,
                         close=1, volume=1, is_final=(i < 9)) for i in range(10)]
    db_session.add_all(rows)
    await db_session.commit()
    df = await ds.load_confirmed_candles(db_session, "SOL", "1m")
    assert len(df) == 9 and int(df["open_time"].iloc[-1]) == 8 * 60_000
    assert await ds.count_confirmed_candles(db_session, "SOL", "1m") == 9
