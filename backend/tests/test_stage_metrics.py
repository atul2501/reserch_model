"""Persisted per-stage performance snapshots and reality-gap comparison
(spec sections 22-24, 34)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.backtesting.engine import BacktestResult, BacktestTrade
from app.backtesting.stage_metrics_service import (
    compute_reality_gap,
    persist_backtest_metrics,
    persist_walk_forward_metrics,
)
from app.backtesting.walk_forward import WalkForwardReport, WalkForwardWindow
from app.models.enums import Side, StrategyFamily, StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


async def _seed_strategy_version(db_session) -> uuid.UUID:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
    db_session.add(strategy)
    await db_session.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
    db_session.add(version)
    await db_session.commit()
    return version.id


def _backtest_result(*, net_pnl: float, starting_equity: float = 100.0) -> BacktestResult:
    trade = BacktestTrade(
        side=Side.LONG, entry_index=210, exit_index=220, entry_price=100.0, exit_price=100.0 + net_pnl,
        quantity=1.0, net_pnl=net_pnl, exit_reason="signal",
    )
    return BacktestResult(
        equity_curve=[starting_equity, starting_equity + net_pnl],
        trades=[trade],
        final_equity=starting_equity + net_pnl,
        starting_equity=starting_equity,
    )


@pytest.mark.asyncio
async def test_persist_backtest_metrics_and_read_back(db_session):
    version_id = await _seed_strategy_version(db_session)
    result = _backtest_result(net_pnl=10.0)

    row = persist_backtest_metrics(version_id, StrategyStage.BACKTEST, result)
    db_session.add(row)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(StageMetrics).where(StageMetrics.strategy_version_id == version_id))
    ).scalar_one()
    assert fetched.stage == StrategyStage.BACKTEST
    assert fetched.net_return_pct == pytest.approx(0.10)
    assert fetched.trade_count == 1


@pytest.mark.asyncio
async def test_persist_walk_forward_metrics_averages_windows(db_session):
    version_id = await _seed_strategy_version(db_session)
    windows = [
        WalkForwardWindow(0, 0, 250, 250, 300, _backtest_result(net_pnl=5.0)),
        WalkForwardWindow(1, 50, 300, 300, 350, _backtest_result(net_pnl=-3.0)),
    ]
    report = WalkForwardReport(windows=windows)

    row = persist_walk_forward_metrics(version_id, report)
    db_session.add(row)
    await db_session.commit()

    assert row.stage == StrategyStage.WALK_FORWARD
    assert row.walk_forward_consistency == report.consistency_score
    assert row.trade_count == 2


@pytest.mark.asyncio
async def test_compute_reality_gap_between_stages(db_session):
    version_id = await _seed_strategy_version(db_session)
    now = datetime.now(timezone.utc)

    backtest_row = StageMetrics(
        strategy_version_id=version_id, stage=StrategyStage.BACKTEST,
        net_return_pct=0.20, max_drawdown_pct=0.05, win_rate=0.6, profit_factor=2.0,
        trade_count=50, computed_at=now - timedelta(days=1),
    )
    paper_row = StageMetrics(
        strategy_version_id=version_id, stage=StrategyStage.PAPER,
        net_return_pct=0.05, max_drawdown_pct=0.10, win_rate=0.5, profit_factor=1.2,
        trade_count=40, computed_at=now,
    )
    db_session.add_all([backtest_row, paper_row])
    await db_session.commit()

    gap = await compute_reality_gap(db_session, version_id, StrategyStage.BACKTEST, StrategyStage.PAPER)

    assert gap["net_return_pct"]["pct_change"] == pytest.approx((0.05 - 0.20) / 0.20)
    assert gap["net_return_pct"]["pct_change"] < 0  # degraded going backtest -> paper
    assert gap["max_drawdown_pct"]["pct_change"] == pytest.approx((0.10 - 0.05) / 0.05)


@pytest.mark.asyncio
async def test_compute_reality_gap_raises_when_stage_missing(db_session):
    version_id = await _seed_strategy_version(db_session)
    with pytest.raises(ValueError):
        await compute_reality_gap(db_session, version_id, StrategyStage.BACKTEST, StrategyStage.PAPER)
