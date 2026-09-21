"""Persists backtest/walk-forward/live performance into StageMetrics and
compares them across pipeline stages (spec sections 22-24, 34) — the
"reality gap" between simulated and real execution.

MVP limitation: `Trade` rows aren't tagged with the stage that was active
when they closed, only `StrategyVersion.stage` (mutable) exists. So
`compute_live_stage_metrics` attributes ALL of a version's trade history to
whichever stage is passed in. Callers must persist metrics for a stage
*before* advancing `StrategyVersion.stage` to the next value, or a later
call will blend two stages' trades together.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.engine import BacktestResult
from app.backtesting.walk_forward import WalkForwardReport
from app.models.agent import Agent
from app.models.enums import StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.trading import Trade


def persist_backtest_metrics(
    strategy_version_id: uuid.UUID, stage: StrategyStage, result: BacktestResult
) -> StageMetrics:
    """Builds a StageMetrics row from a single backtest run (BACKTEST or
    OUT_OF_SAMPLE stage — caller passes which). Caller adds + commits."""
    profit_factor = result.profit_factor
    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=stage,
        net_return_pct=result.net_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        win_rate=result.win_rate,
        profit_factor=profit_factor if profit_factor != float("inf") else None,
        trade_count=len(result.trades),
        computed_at=datetime.now(timezone.utc),
    )


def persist_walk_forward_metrics(strategy_version_id: uuid.UUID, report: WalkForwardReport) -> StageMetrics:
    """Builds a StageMetrics row (WALK_FORWARD stage) from a walk-forward
    report, averaging per-window win_rate/profit_factor and carrying the
    report's consistency_score through for champion/challenger gating."""
    trade_count = sum(len(w.result.trades) for w in report.windows)
    win_rates = [w.result.win_rate for w in report.windows if w.result.win_rate is not None]
    profit_factors = [
        w.result.profit_factor for w in report.windows if w.result.profit_factor not in (None, float("inf"))
    ]
    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=StrategyStage.WALK_FORWARD,
        net_return_pct=report.average_return_pct,
        max_drawdown_pct=report.max_drawdown_across_windows,
        win_rate=sum(win_rates) / len(win_rates) if win_rates else None,
        profit_factor=sum(profit_factors) / len(profit_factors) if profit_factors else None,
        trade_count=trade_count,
        walk_forward_consistency=report.consistency_score,
        computed_at=datetime.now(timezone.utc),
    )


async def compute_live_stage_metrics(
    db: AsyncSession, *, strategy_version_id: uuid.UUID, stage: StrategyStage
) -> StageMetrics:
    """Computes the same 4 base metrics from actual Trade/Agent history for
    every agent currently on `strategy_version_id`, for PAPER/SHADOW/
    SMALL_LIVE/APPROVED_LIVE stages. Does not persist — caller adds+commits."""
    agents = (
        await db.execute(select(Agent).where(Agent.strategy_version_id == strategy_version_id))
    ).scalars().all()

    if not agents:
        return StageMetrics(
            strategy_version_id=strategy_version_id,
            stage=stage,
            net_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate=None,
            profit_factor=None,
            trade_count=0,
            computed_at=datetime.now(timezone.utc),
        )

    agent_ids = [a.id for a in agents]
    trades = (await db.execute(select(Trade).where(Trade.agent_id.in_(agent_ids)))).scalars().all()

    starting = sum(a.starting_balance for a in agents)
    current = sum(a.equity for a in agents)
    net_return_pct = (current - starting) / starting if starting else 0.0
    max_drawdown_pct = max((a.max_drawdown for a in agents), default=0.0)

    win_rate = None
    profit_factor = None
    if trades:
        wins = sum(1 for t in trades if t.net_pnl > 0)
        win_rate = wins / len(trades)
        gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        if gross_loss > 0:
            profit_factor = gross_win / gross_loss

    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=stage,
        net_return_pct=net_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        trade_count=len(trades),
        computed_at=datetime.now(timezone.utc),
    )


async def compute_reality_gap(
    db: AsyncSession, strategy_version_id: uuid.UUID, from_stage: StrategyStage, to_stage: StrategyStage
) -> dict:
    """Pulls the most recent StageMetrics row per stage and returns
    per-metric {from, to, pct_change} for the 4 base metrics. Positive
    pct_change = improved at the later stage, negative = degraded (the
    "reality gap"). Raises ValueError if either stage has no metrics yet."""
    from_row = await latest_stage_metrics(db, strategy_version_id, from_stage)
    to_row = await latest_stage_metrics(db, strategy_version_id, to_stage)
    if from_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {from_stage.value}")
    if to_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {to_stage.value}")

    def pct_change(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or a == 0:
            return None
        return (b - a) / abs(a)

    return {
        "from_stage": from_stage.value,
        "to_stage": to_stage.value,
        "net_return_pct": {
            "from": from_row.net_return_pct, "to": to_row.net_return_pct,
            "pct_change": pct_change(from_row.net_return_pct, to_row.net_return_pct),
        },
        "max_drawdown_pct": {
            "from": from_row.max_drawdown_pct, "to": to_row.max_drawdown_pct,
            "pct_change": pct_change(from_row.max_drawdown_pct, to_row.max_drawdown_pct),
        },
        "win_rate": {
            "from": from_row.win_rate, "to": to_row.win_rate,
            "pct_change": pct_change(from_row.win_rate, to_row.win_rate),
        },
        "profit_factor": {
            "from": from_row.profit_factor, "to": to_row.profit_factor,
            "pct_change": pct_change(from_row.profit_factor, to_row.profit_factor),
        },
    }


async def latest_stage_metrics(db: AsyncSession, strategy_version_id: uuid.UUID, stage: StrategyStage) -> StageMetrics | None:
    return (
        await db.execute(
            select(StageMetrics)
            .where(StageMetrics.strategy_version_id == strategy_version_id, StageMetrics.stage == stage)
            .order_by(StageMetrics.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
