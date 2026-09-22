"""Generational strategy-evaluation pipeline (spec sections 25-34): the
concrete home for the order the user specified — Correlation -> Reality
Gap -> Regime Validation -> Adversarial Testing -> Fitness -> Champion/
Challenger. Fitness and Correlation are generation-scoped and already run
in scripts/breed_next_generation.py; this script runs the remaining three,
per strategy version, then advances each version's Candidate -> ... ->
Promotion Decision pipeline_stage.

This does NOT run backtests for brand-new candidates itself — that
prerequisite (backtest -> walk-forward -> OOS, persisting StageMetrics) is
a separate, not-yet-automated step in this codebase; this script picks up
from wherever a strategy version currently has metrics and moves it
forward, skipping (not failing) whatever it doesn't have data for yet.

Usage:
    python -m scripts.evaluate_generation
"""
from __future__ import annotations

import asyncio

import pandas as pd
from sqlalchemy import or_, select

from app.backtesting.reality_gap_engine import compute_full_reality_gap_chain, persist_reality_gap_report
from app.backtesting.regime_validation_engine import run_and_persist_regime_validation
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.evolution.adversarial_service import run_and_persist_adversarial_suite
from app.evolution.champion_challenger_service import advance_pipeline_stage, latest_challenger_evaluation
from app.models.enums import ChampionStatus, StrategyStage
from app.models.market import MarketCandle
from app.models.strategy import StrategyVersion

logger = get_logger(__name__)

_LIVE_DATA_STAGES = (StrategyStage.PAPER, StrategyStage.SHADOW, StrategyStage.SMALL_LIVE, StrategyStage.APPROVED_LIVE)


async def evaluate_generation() -> None:
    configure_logging()
    settings = get_settings()

    async with session_scope() as db:
        candles = await _load_recent_candles(db, symbol=settings.market_symbol, timeframe=settings.market_timeframe)

        # champion_status is nullable (most versions never had it set), and
        # SQL `!=` against NULL evaluates to unknown (row excluded), not
        # true — so this must be an explicit OR against NULL, or every
        # never-evaluated version silently vanishes from the query.
        versions = (
            await db.execute(
                select(StrategyVersion).where(
                    or_(StrategyVersion.champion_status.is_(None), StrategyVersion.champion_status != ChampionStatus.RETIRED)
                )
            )
        ).scalars().all()

        for version in versions:
            evaluation = await latest_challenger_evaluation(db, version.id)
            current_stage = evaluation.pipeline_stage if evaluation is not None else "candidate"
            if current_stage in ("promoted", "rejected"):
                continue

            # Reality gap: harmless no-op for versions with fewer than 2
            # stages of recorded metrics (compute_full_reality_gap_chain
            # returns empty transitions rather than raising).
            chain_report = await compute_full_reality_gap_chain(db, version.id)
            if chain_report.transitions:
                await persist_reality_gap_report(db, chain_report)

            # Regime validation from live trade history, once this version
            # has reached a live-data stage.
            if version.stage in _LIVE_DATA_STAGES:
                await run_and_persist_regime_validation(
                    db, version.id, stage=version.stage,
                    min_trades_per_regime=settings.regime_validation_min_trades_per_regime,
                    robust_min_positive_regimes_pct=settings.regime_validation_robust_min_positive_regimes_pct,
                    specialist_min_pnl_share=settings.regime_validation_specialist_min_pnl_share,
                )

            # Adversarial testing gates validation -> challenger, so only
            # run it for versions actually waiting on that gate, and only
            # when there's enough real market data to backtest against.
            if current_stage == "validation" and candles is not None:
                await run_and_persist_adversarial_suite(
                    db, version.id, candles,
                    symbol=settings.market_symbol, timeframe=settings.market_timeframe, starting_equity=100.0,
                    base_fee_rate=settings.paper_fee_rate, base_slippage_bps=settings.paper_slippage_bps,
                    n_dna_variants=settings.adversarial_n_dna_variants,
                    global_max_leverage=settings.max_leverage, global_max_position_size=settings.max_position_size,
                    global_max_drawdown=settings.max_drawdown, global_max_daily_loss=settings.max_daily_loss,
                )

            result = await advance_pipeline_stage(db, version.id, promotion_stage=version.stage)
            await db.commit()
            logger.info(
                "evaluate_generation.pipeline_advanced",
                strategy_version_id=str(version.id),
                from_stage=current_stage,
                to_stage=result.pipeline_stage,
                blocking_reasons=result.blocking_reasons,
            )


async def _load_recent_candles(db, *, symbol: str, timeframe: str, limit: int = 2000) -> pd.DataFrame | None:
    rows = (
        await db.execute(
            select(
                MarketCandle.open_time, MarketCandle.open, MarketCandle.high,
                MarketCandle.low, MarketCandle.close, MarketCandle.volume,
            )
            .where(MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe)
            .order_by(MarketCandle.open_time.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
    return df.sort_values("open_time").reset_index(drop=True)


if __name__ == "__main__":
    asyncio.run(evaluate_generation())
