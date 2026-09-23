"""Final-OOS lockbox (spec phase 23).

The final out-of-sample slice of a research epoch may influence NOTHING that
selects or breeds strategies. This module is the ONLY code that reads it:

  * `slice_train_validation` (dataset.py) is what evolution/fitness receive —
    the OOS candles are not even loaded into that process' frames;
  * `evaluate_oos_once` runs a version against the OOS slice exactly once per
    (strategy_version, dataset_fingerprint). A second attempt raises
    `OosAlreadyConsumedError` — enforced by a UNIQUE constraint, not only Python.
  * the resulting score feeds the PROMOTION gate only (never fitness/selection).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.data import prepare_backtest_data
from app.backtesting.engine import BacktestResult, run_backtest
from app.backtesting.stage_metrics_service import persist_backtest_metrics
from app.core.config import get_settings
from app.models.enums import StrategyStage
from app.models.research import OosEvaluation, ResearchEpoch
from app.models.strategy import StrategyVersion
from app.research.registry import finish_experiment, register_experiment
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import dna_indicator_specs


class OosAlreadyConsumedError(RuntimeError):
    """This strategy version already used this dataset's final OOS slice."""


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_oos_score(result: BacktestResult, *, min_trades: int) -> float:
    """[0, 1]. Zero without enough trades to say anything. Otherwise:
        0.4 * clip(profit_factor - 1)        (edge)
      + 0.3 * clip(1 - max_drawdown / 30%)   (pain)
      + 0.3 * clip(return / 5%)              (payoff over the slice)
    A losing or flat OOS run therefore cannot score above 0.3."""
    if len(result.trades) < min_trades:
        return 0.0
    pf = result.profit_factor
    pf = 3.0 if pf is None and result.net_return_pct > 0 else (1.0 if pf is None else min(pf, 3.0))
    return 0.4 * _clip(pf - 1.0) + 0.3 * _clip(1.0 - result.max_drawdown_pct / 0.30) + 0.3 * _clip(result.net_return_pct / 0.05)


async def evaluate_oos_once(
    db: AsyncSession,
    version: StrategyVersion,
    epoch: ResearchEpoch,
    full_candles: pd.DataFrame,
    *,
    funding: list[tuple[int, float]] | None = None,
    seed: int | None = None,
) -> OosEvaluation:
    """Runs `version` on the epoch's protected OOS slice, exactly once."""
    s = get_settings()
    existing = (
        await db.execute(
            select(OosEvaluation).where(
                OosEvaluation.strategy_version_id == version.id,
                OosEvaluation.dataset_fingerprint == epoch.dataset_fingerprint,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise OosAlreadyConsumedError(
            f"strategy_version {version.id} already consumed the OOS slice of {epoch.epoch_id}"
        )

    dna = StrategyDNA.model_validate(version.dna)
    oos_start = int((full_candles["open_time"] > epoch.validation_end_ms).idxmax())
    data = prepare_backtest_data(
        full_candles, symbol=epoch.symbol, timeframe=epoch.timeframe, specs=dna_indicator_specs(dna), funding=funding
    )
    result = run_backtest(
        full_candles, dna, symbol=epoch.symbol, timeframe=epoch.timeframe, starting_equity=s.agent_starting_balance,
        fee_rate=s.paper_fee_rate, slippage_bps=s.paper_slippage_bps, enforce_risk_engine=True,
        global_max_leverage=s.max_leverage, global_max_position_size=s.max_position_size,
        global_max_drawdown=s.max_drawdown, global_max_daily_loss=s.max_daily_loss,
        data=data, start_index=oos_start,
    )
    score = compute_oos_score(result, min_trades=s.research_candidate_min_trades)

    exp = await register_experiment(
        db, kind="oos", seed=seed if seed is not None else s.research_seed, epoch=epoch,
        strategy_version_id=version.id, generation=version.generation,
        parameters={"oos_start_index": oos_start, "min_trades": s.research_candidate_min_trades},
    )
    row = OosEvaluation(
        strategy_version_id=version.id, dataset_fingerprint=epoch.dataset_fingerprint, experiment_id=exp.experiment_id,
        oos_score=score,
        metrics={"net_return_pct": result.net_return_pct, "max_drawdown_pct": result.max_drawdown_pct,
                 "profit_factor": None if result.profit_factor in (None, float("inf")) else result.profit_factor,
                 "trade_count": len(result.trades), "win_rate": result.win_rate},
    )
    db.add(row)
    metrics_row = persist_backtest_metrics(version.id, StrategyStage.OUT_OF_SAMPLE, result)
    metrics_row.oos_score = score
    db.add(metrics_row)
    try:
        await db.flush()
    except IntegrityError as exc:  # concurrent duplicate: the DB constraint is the final arbiter
        await db.rollback()
        raise OosAlreadyConsumedError(f"OOS slice of {epoch.epoch_id} already consumed (concurrent)") from exc
    await finish_experiment(db, exp, status="COMPLETED", result={"oos_score": score, **row.metrics})
    return row
