"""Final-OOS protection (spec phase 23): evolution cannot see or re-tune
against the protected slice."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.backtesting.data import prepare_backtest_data
from app.models.enums import StrategyStage
from app.models.research import OosEvaluation
from app.models.stage_metrics import StageMetrics
from app.research import dataset as ds
from app.research.evaluation import evaluate_in_sample
from app.research.lockbox import OosAlreadyConsumedError, compute_oos_score, evaluate_oos_once
from tests.helpers_agents import make_agents
from tests.test_backtest_parity import candles, ema_cross_dna
from app.backtesting.engine import BacktestResult, BacktestTrade
from app.models.enums import Side


async def _setup(db, n=1400):
    c = candles(n, seed=21, drift=0.01)
    epoch, _ = await ds.get_or_create_epoch(db, c, symbol="SOL", timeframe="1m")
    (agent,) = await make_agents(db, [ema_cross_dna(5, 20)])
    from app.models.strategy import StrategyVersion
    version = await db.get(StrategyVersion, agent.strategy_version_id)
    return c, epoch, version


async def test_evolution_frame_contains_no_candle_beyond_the_validation_boundary(db_session):
    c, epoch, _ = await _setup(db_session)
    frame = ds.slice_train_validation(c, epoch)
    assert int(frame["open_time"].max()) == epoch.validation_end_ms
    assert int(c["open_time"].max()) == epoch.end_ms > epoch.validation_end_ms
    assert len(frame) == int(len(c) * 0.8)


async def test_in_sample_evaluation_refuses_frames_that_leak_the_oos_slice(db_session):
    c, epoch, version = await _setup(db_session)
    data = prepare_backtest_data(c, symbol="SOL", timeframe="1m", specs=[])
    with pytest.raises(ValueError, match="OOS leak"):
        evaluate_in_sample(version.id, ema_cross_dna(5, 20), c, data, epoch)


async def test_in_sample_evaluation_writes_backtest_and_walk_forward_metrics(db_session):
    c, epoch, version = await _setup(db_session, n=2600)
    frame = ds.slice_train_validation(c, epoch)
    from app.strategies.engine import dna_indicator_specs
    dna = ema_cross_dna(5, 20)
    data = prepare_backtest_data(frame, symbol="SOL", timeframe="1m", specs=dna_indicator_specs(dna))
    ev = evaluate_in_sample(version.id, dna, frame, data, epoch)
    assert ev.backtest_metrics.stage == StrategyStage.BACKTEST and ev.backtest_metrics.trade_count == len(ev.train.trades)
    assert ev.backtest_metrics.oos_score == ev.validation_score        # validation-slice score, NOT the final OOS
    assert ev.wfo_metrics is not None and ev.wfo_metrics.stage == StrategyStage.WALK_FORWARD
    assert ev.wfo_metrics.walk_forward_consistency is not None


async def test_oos_can_be_consumed_only_once_per_version_and_dataset(db_session):
    c, epoch, version = await _setup(db_session)
    first = await evaluate_oos_once(db_session, version, epoch, c)
    await db_session.commit()
    assert 0.0 <= first.oos_score <= 1.0
    with pytest.raises(OosAlreadyConsumedError):
        await evaluate_oos_once(db_session, version, epoch, c)
    rows = (await db_session.execute(select(OosEvaluation))).scalars().all()
    assert len(rows) == 1
    oos_metrics = (await db_session.execute(select(StageMetrics).where(StageMetrics.stage == StrategyStage.OUT_OF_SAMPLE))).scalars().all()
    assert len(oos_metrics) == 1 and oos_metrics[0].oos_score == first.oos_score


async def test_database_constraint_is_the_final_arbiter_for_oos_reuse(db_session):
    c, epoch, version = await _setup(db_session)
    await evaluate_oos_once(db_session, version, epoch, c)
    await db_session.commit()
    db_session.add(OosEvaluation(strategy_version_id=version.id, dataset_fingerprint=epoch.dataset_fingerprint,
                                 experiment_id="EXP-x", oos_score=0.9, metrics={}))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_only_an_explicit_renewal_opens_a_fresh_oos_slice(db_session):
    c, epoch, version = await _setup(db_session)
    await evaluate_oos_once(db_session, version, epoch, c)
    await db_session.commit()
    c2 = candles(1500, seed=22, drift=0.01)          # different / later data ...
    same, created = await ds.get_or_create_epoch(db_session, c2, symbol="SOL", timeframe="1m")
    assert not created and same.dataset_fingerprint == epoch.dataset_fingerprint     # ... does NOT re-open the holdout
    with pytest.raises(OosAlreadyConsumedError):
        await evaluate_oos_once(db_session, version, same, c)
    await db_session.rollback()
    await db_session.refresh(version)
    await db_session.refresh(epoch)
    epoch2 = await ds.renew_epoch(db_session, c2, symbol="SOL", timeframe="1m", reason="operator refresh")
    again = await evaluate_oos_once(db_session, version, epoch2, c2)
    assert again.dataset_fingerprint == epoch2.dataset_fingerprint != epoch.dataset_fingerprint


def _result(trades_pnl, final=100.0, curve=None):
    trades = [BacktestTrade(side=Side.LONG, entry_index=i, exit_index=i + 1, entry_price=100, exit_price=100, quantity=1,
                            net_pnl=p, exit_reason="signal") for i, p in enumerate(trades_pnl)]
    return BacktestResult(equity_curve=curve or [100.0, final], trades=trades, final_equity=final, starting_equity=100.0)


def test_oos_score_needs_trades_and_cannot_be_high_for_a_losing_run():
    assert compute_oos_score(_result([], 100.0), min_trades=3) == 0.0
    assert compute_oos_score(_result([1, 1], 102.0), min_trades=3) == 0.0                # too few trades
    losing = compute_oos_score(_result([-1, -1, 1, -1], 97.0, [100, 97]), min_trades=3)
    winning = compute_oos_score(_result([2, 2, -1, 2], 105.0, [100, 105]), min_trades=3)
    assert losing <= 0.3 and winning > 0.8 and winning <= 1.0
