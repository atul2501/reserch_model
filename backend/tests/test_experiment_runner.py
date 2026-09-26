"""Experiment runner: never overwrites a prior result, records full provenance,
never touches the sealed final-OOS slice, and labels sample sufficiency
correctly at the FULL_CONFIDENCE_TRADES boundary."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.market import MarketCandle
from app.models.research import Experiment
from app.research import dataset as ds
from app.research.experiment_runner import (
    compute_metrics, diff_experiments, list_experiments, render_comparison, run_baseline_vs_candidate,
)
from app.research.lockbox import FULL_CONFIDENCE_TRADES
from tests.test_backtest_parity import candles as make_candles, ema_cross_dna


async def _seal_epoch(db, *, n=1400, seed=21):
    c = make_candles(n, seed=seed, drift=0.01)
    db.add_all([
        MarketCandle(symbol="SOL", timeframe="1m", open_time=int(r.open_time), close_time=int(r.open_time) + 59_999,
                    open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
                    volume=float(r.volume), is_final=True)
        for r in c.itertuples()
    ])
    await db.commit()
    epoch = await ds.seal_epoch(db, c, symbol="SOL", timeframe="1m", reason="test")
    await db.commit()
    return epoch


async def test_run_baseline_vs_candidate_persists_two_new_non_overwriting_experiments(db_session):
    await _seal_epoch(db_session)
    baseline_dna = ema_cross_dna(5, 20)
    candidate_dna = ema_cross_dna(3, 15)

    before = (await db_session.execute(select(Experiment))).scalars().all()
    assert before == []

    baseline, candidate = await run_baseline_vs_candidate(
        db_session, baseline_dna=baseline_dna, candidate_dna=candidate_dna, name="unit_test_run",
    )
    await db_session.commit()

    rows = (await db_session.execute(select(Experiment))).scalars().all()
    assert len(rows) == 2
    assert baseline.experiment.experiment_id != candidate.experiment.experiment_id
    assert {r.status for r in rows} == {"COMPLETED"}
    for exp in (baseline.experiment, candidate.experiment):
        assert exp.code_version and exp.schema_version and exp.random_seed is not None
        assert exp.dataset_fingerprint is not None
        assert exp.parameters["name"] == "unit_test_run"
        assert exp.result["trade_count"] == exp.result.get("trade_count")  # present, whatever the value


async def test_run_baseline_vs_candidate_never_overwrites_a_prior_run(db_session):
    await _seal_epoch(db_session)
    dna = ema_cross_dna(5, 20)

    await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="repeat")
    await db_session.commit()
    first_count = len((await db_session.execute(select(Experiment))).scalars().all())

    await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="repeat")
    await db_session.commit()
    second_count = len((await db_session.execute(select(Experiment))).scalars().all())

    assert second_count == first_count + 2   # a second run adds new rows, never updates the first pair


async def test_run_baseline_vs_candidate_never_touches_the_sealed_oos_slice(db_session):
    """The whole point of the design: OOS is always reported as deliberately
    not evaluated, never as data-insufficient, and evaluate_oos_once is never called."""
    await _seal_epoch(db_session)
    dna = ema_cross_dna(5, 20)

    baseline, _candidate = await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="oos_check")
    await db_session.commit()

    assert "NOT EVALUATED" in baseline.metrics.oos
    assert "rate-limited" in baseline.metrics.oos
    from app.models.research import OosEvaluation
    assert (await db_session.execute(select(OosEvaluation))).scalars().all() == []


async def test_run_baseline_vs_candidate_raises_without_an_active_epoch(db_session):
    dna = ema_cross_dna(5, 20)
    with pytest.raises(ValueError, match="no active ResearchEpoch"):
        await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="no_epoch")


async def test_sample_label_reflects_the_full_confidence_trades_boundary(db_session):
    """compute_metrics is pure - test the boundary directly without a full DB round trip."""
    from app.backtesting.engine import BacktestResult, BacktestTrade
    from app.models.enums import Side
    import pandas as pd

    frame = pd.DataFrame({
        "open_time": [1_700_000_000_000 + i * 60_000 for i in range(40)],
        "open": [100.0] * 40, "high": [101.0] * 40, "low": [99.0] * 40, "close": [100.0] * 40,
    })
    dna = ema_cross_dna(5, 20)

    few_trades = [BacktestTrade(side=Side.LONG, entry_index=i, exit_index=i + 1, entry_price=100, exit_price=101,
                                quantity=1, net_pnl=1.0, exit_reason="signal") for i in range(FULL_CONFIDENCE_TRADES - 1)]
    many_trades = [BacktestTrade(side=Side.LONG, entry_index=i, exit_index=i + 1, entry_price=100, exit_price=101,
                                 quantity=1, net_pnl=1.0, exit_reason="signal") for i in range(FULL_CONFIDENCE_TRADES)]

    few = compute_metrics(BacktestResult(equity_curve=[100, 101], trades=few_trades, final_equity=101, starting_equity=100), frame, dna)
    many = compute_metrics(BacktestResult(equity_curve=[100, 101], trades=many_trades, final_equity=101, starting_equity=100), frame, dna)

    assert few.sample_label == "PROMISING — REQUIRES UNSEEN DATA"
    assert many.sample_label == "IN-SAMPLE"


async def test_diff_experiments_computes_numeric_deltas_and_preserves_non_numeric_fields(db_session):
    await _seal_epoch(db_session)
    dna_a, dna_b = ema_cross_dna(5, 20), ema_cross_dna(3, 15)
    baseline, candidate = await run_baseline_vs_candidate(db_session, baseline_dna=dna_a, candidate_dna=dna_b, name="diff_check")
    await db_session.commit()

    diff = diff_experiments(baseline.experiment, candidate.experiment)

    assert "net_pnl" in diff
    va, vb, delta = diff["net_pnl"]
    assert delta == pytest.approx(vb - va)
    va2, vb2, delta2 = diff["sample_label"]
    assert delta2 is None  # non-numeric fields report a delta of None, not a crash


async def test_list_experiments_returns_newest_first(db_session):
    await _seal_epoch(db_session)
    dna = ema_cross_dna(5, 20)
    await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="first")
    await db_session.commit()
    await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="second")
    await db_session.commit()

    rows = await list_experiments(db_session, kind="evaluation")

    assert len(rows) == 4
    assert rows[0].created_at >= rows[-1].created_at


async def test_render_comparison_includes_both_experiment_ids_and_the_oos_note(db_session):
    await _seal_epoch(db_session)
    dna = ema_cross_dna(5, 20)
    baseline, candidate = await run_baseline_vs_candidate(db_session, baseline_dna=dna, candidate_dna=dna, name="render_check")
    await db_session.commit()

    text = render_comparison("render_check", baseline, candidate)

    assert baseline.experiment.experiment_id in text
    assert candidate.experiment.experiment_id in text
    assert "NOT EVALUATED" in text
