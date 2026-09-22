"""Persists PerformanceMetric snapshots from real Trade/Agent state.

Regime-performance breakdown is left as `{}` here — Phase 1
(RegimeValidationEngine) owns computing and filling `regime_performance`,
so this module doesn't duplicate that bisect-join logic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.performance_metrics_engine import compute_trade_stats
from app.models.agent import Agent
from app.models.metrics import PerformanceMetric
from app.models.trading import Trade


async def compute_agent_performance_metric(db: AsyncSession, agent: Agent, *, as_of: datetime | None = None) -> PerformanceMetric:
    """Builds (does not persist) a PerformanceMetric snapshot for `agent`
    from its full closed-trade history. Caller adds + commits."""
    trades = (
        await db.execute(select(Trade).where(Trade.agent_id == agent.id).order_by(Trade.closed_at))
    ).scalars().all()

    stats = compute_trade_stats([t.net_pnl for t in trades], [t.holding_seconds for t in trades])

    roi = (agent.equity - agent.starting_balance) / agent.starting_balance if agent.starting_balance else 0.0
    net_pnl = agent.equity - agent.starting_balance
    gross_pnl = sum(t.gross_pnl for t in trades)
    survival_seconds = ((as_of or datetime.now(timezone.utc)) - agent.created_at).total_seconds()

    return PerformanceMetric(
        agent_id=agent.id,
        as_of=as_of or datetime.now(timezone.utc),
        equity=agent.equity,
        balance=agent.balance,
        roi=roi,
        net_pnl=net_pnl,
        gross_pnl=gross_pnl,
        win_rate=stats.win_rate,
        loss_rate=stats.loss_rate,
        profit_factor=stats.profit_factor,
        expectancy=stats.expectancy,
        average_trade=stats.average_trade,
        average_winner=stats.average_winner,
        average_loser=stats.average_loser,
        largest_win=stats.largest_win,
        largest_loss=stats.largest_loss,
        consecutive_wins=stats.consecutive_wins,
        consecutive_losses=stats.consecutive_losses,
        max_drawdown=agent.max_drawdown,
        sharpe_like=stats.sharpe_like,
        sortino_like=stats.sortino_like,
        trade_count=len(trades),
        average_holding_seconds=stats.average_holding_seconds,
        survival_seconds=max(0.0, survival_seconds),
        regime_performance={},
        oos_score=None,
        walk_forward_score=None,
    )


async def compute_and_persist_agent_performance_metric(db: AsyncSession, agent: Agent, *, as_of: datetime | None = None) -> PerformanceMetric:
    metric = await compute_agent_performance_metric(db, agent, as_of=as_of)
    db.add(metric)
    return metric


async def latest_performance_metric(db: AsyncSession, agent_id: uuid.UUID) -> PerformanceMetric | None:
    return (
        await db.execute(
            select(PerformanceMetric)
            .where(PerformanceMetric.agent_id == agent_id)
            .order_by(PerformanceMetric.as_of.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
