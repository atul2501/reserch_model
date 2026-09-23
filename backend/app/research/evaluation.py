"""In-sample research evaluation of a strategy version (train + validation
only — the final OOS slice is never reachable from here):

  BACKTEST       full simulation on the TRAIN slice        -> StageMetrics(BACKTEST)
                 (its `oos_score` is the VALIDATION-slice score: out-of-sample
                  w.r.t. training, and therefore the only "OOS" selection may use)
  WALK_FORWARD   rolling out-of-time windows over train+val -> StageMetrics(WALK_FORWARD)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.backtesting.data import BacktestData
from app.backtesting.engine import BacktestResult, run_backtest
from app.backtesting.stage_metrics_service import persist_backtest_metrics, persist_walk_forward_metrics
from app.backtesting.walk_forward import WalkForwardReport, run_walk_forward
from app.core.config import get_settings
from app.market.feature_engine import MIN_CANDLES_REQUIRED, InsufficientDataError
from app.models.enums import StrategyStage
from app.models.research import ResearchEpoch
from app.models.stage_metrics import StageMetrics
from app.research.lockbox import compute_oos_score
from app.schemas.strategy_dna import StrategyDNA


@dataclass
class InSampleEvaluation:
    train: BacktestResult
    validation: BacktestResult
    walk_forward: WalkForwardReport | None
    validation_score: float
    backtest_metrics: StageMetrics
    wfo_metrics: StageMetrics | None


def evaluate_in_sample(
    version_id, dna: StrategyDNA, frame: pd.DataFrame, data: BacktestData, epoch: ResearchEpoch,
    *, funding: list[tuple[int, float]] | None = None,
) -> InSampleEvaluation:
    """`frame`/`data` MUST be the train+validation frame (see dataset.slice_train_validation)."""
    s = get_settings()
    if int(frame["open_time"].iloc[-1]) > epoch.validation_end_ms:
        raise ValueError("in-sample evaluation received candles beyond the validation boundary (OOS leak)")
    n = len(frame)
    train_end = int((frame["open_time"] > epoch.train_end_ms).idxmax()) if (frame["open_time"] > epoch.train_end_ms).any() else n

    common: dict[str, Any] = dict(
        symbol=epoch.symbol, timeframe=epoch.timeframe, starting_equity=s.agent_starting_balance,
        fee_rate=s.paper_fee_rate, slippage_bps=s.paper_slippage_bps, enforce_risk_engine=True,
        global_max_leverage=s.max_leverage, global_max_position_size=s.max_position_size,
        global_max_drawdown=s.max_drawdown, global_max_daily_loss=s.max_daily_loss, data=data,
    )
    train = run_backtest(frame, dna, end_index=train_end, **common)
    validation = run_backtest(frame, dna, start_index=train_end, **common)
    val_score = compute_oos_score(validation, min_trades=s.research_candidate_min_trades)

    bt_row = persist_backtest_metrics(version_id, StrategyStage.BACKTEST, train)
    bt_row.oos_score = val_score   # validation-slice score; NOT the protected final OOS

    wfo: WalkForwardReport | None = None
    wfo_row: StageMetrics | None = None
    test_window = 1440 if n >= 4000 else max(200, n // 6)
    train_window = max(MIN_CANDLES_REQUIRED + 50, min(3000, n // 3))
    if n >= train_window + test_window:
        try:
            wfo = run_walk_forward(
                frame, dna, symbol=epoch.symbol, timeframe=epoch.timeframe, train_window=train_window,
                test_window=test_window, step=test_window, starting_equity=s.agent_starting_balance,
                fee_rate=s.paper_fee_rate, slippage_bps=s.paper_slippage_bps,
            )
            wfo_row = persist_walk_forward_metrics(version_id, wfo)
        except InsufficientDataError:
            wfo = None
    return InSampleEvaluation(train, validation, wfo, val_score, bt_row, wfo_row)
