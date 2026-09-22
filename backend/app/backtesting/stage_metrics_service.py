"""Persists backtest/walk-forward/live performance into StageMetrics and
compares them across pipeline stages (spec sections 22-24, 34) — the
"reality gap" between simulated and real execution.

`Trade.stage` is stamped by `app/agents/decision_loop.py::_close_position`
at close time (the StrategyVersion.stage active at that moment), so
`compute_live_stage_metrics` can isolate exactly the trades that closed
during `stage` rather than blending a version's entire history together.
Trades closed before this column existed have `stage IS NULL`; for those
legacy rows only, this falls back to attributing all of them to whichever
stage is requested (matches the old MVP behavior) rather than silently
excluding them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.engine import BacktestResult
from app.backtesting.walk_forward import WalkForwardReport
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import OrderStatus, RiskDecision, StrategyStage
from app.models.stage_metrics import StageMetrics
from app.models.trading import Order, Trade


def pct_change(a: float | None, b: float | None) -> float | None:
    """Positive = improved at the later value, negative = degraded (the
    "reality gap"). Shared by compute_reality_gap and reality_gap_engine's
    full-chain report so both use identical math."""
    if a is None or b is None or a == 0:
        return None
    return (b - a) / abs(a)


def persist_backtest_metrics(
    strategy_version_id: uuid.UUID, stage: StrategyStage, result: BacktestResult
) -> StageMetrics:
    """Builds a StageMetrics row from a single backtest run (BACKTEST or
    OUT_OF_SAMPLE stage — caller passes which). Caller adds + commits."""
    profit_factor = result.profit_factor
    trade_count = len(result.trades)
    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=stage,
        net_return_pct=result.net_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        win_rate=result.win_rate,
        profit_factor=profit_factor if profit_factor != float("inf") else None,
        trade_count=trade_count,
        total_fees=sum(t.fee for t in result.trades) if result.trades else None,
        total_slippage_cost=sum(t.slippage_cost for t in result.trades) if result.trades else None,
        avg_trade_net_pnl=(sum(t.net_pnl for t in result.trades) / trade_count) if trade_count else None,
        # No real order flow inside run_backtest — funding/latency/missed
        # fills simply don't exist as concepts in a backtest.
        computed_at=datetime.now(timezone.utc),
    )


def persist_walk_forward_metrics(strategy_version_id: uuid.UUID, report: WalkForwardReport) -> StageMetrics:
    """Builds a StageMetrics row (WALK_FORWARD stage) from a walk-forward
    report, averaging per-window win_rate/profit_factor and carrying the
    report's consistency_score through for champion/challenger gating."""
    all_trades = [t for w in report.windows for t in w.result.trades]
    trade_count = len(all_trades)
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
        total_fees=sum(t.fee for t in all_trades) if all_trades else None,
        total_slippage_cost=sum(t.slippage_cost for t in all_trades) if all_trades else None,
        avg_trade_net_pnl=(sum(t.net_pnl for t in all_trades) / trade_count) if trade_count else None,
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
    staged_trades = (
        await db.execute(select(Trade).where(Trade.agent_id.in_(agent_ids), Trade.stage == stage))
    ).scalars().all()
    if staged_trades:
        trades = staged_trades
    else:
        # No trades tagged with this stage yet — either none have closed
        # here at all, or these are legacy pre-migration rows with
        # stage=NULL. Fall back to the version's untagged trade history
        # rather than silently reporting zero.
        legacy_trades = (
            await db.execute(
                select(Trade).where(Trade.agent_id.in_(agent_ids), Trade.stage.is_(None))
            )
        ).scalars().all()
        trades = legacy_trades

    starting = sum(a.starting_balance for a in agents)
    current = sum(a.equity for a in agents)
    net_return_pct = (current - starting) / starting if starting else 0.0
    max_drawdown_pct = max((a.max_drawdown for a in agents), default=0.0)

    win_rate = None
    profit_factor = None
    avg_trade_net_pnl = None
    if trades:
        wins = sum(1 for t in trades if t.net_pnl > 0)
        win_rate = wins / len(trades)
        gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        if gross_loss > 0:
            profit_factor = gross_win / gross_loss
        avg_trade_net_pnl = sum(t.net_pnl for t in trades) / len(trades)

    avg_latency_ms = (
        await db.execute(
            select(func.avg(Order.latency_ms)).where(
                Order.agent_id.in_(agent_ids), Order.status == OrderStatus.FILLED, Order.latency_ms.is_not(None)
            )
        )
    ).scalar_one_or_none()

    missed = await compute_missed_trade_stats(db, strategy_version_id)

    return StageMetrics(
        strategy_version_id=strategy_version_id,
        stage=stage,
        net_return_pct=net_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        trade_count=len(trades),
        total_fees=sum(t.fees for t in trades) if trades else None,
        total_funding=sum(t.funding for t in trades) if trades else None,
        total_slippage_cost=sum(t.slippage_cost for t in trades) if trades else None,
        avg_trade_net_pnl=avg_trade_net_pnl,
        avg_latency_ms=float(avg_latency_ms) if avg_latency_ms is not None else None,
        missed_trade_count=missed.missed_trade_count,
        missed_trade_pct=missed.missed_trade_pct,
        avg_signal_to_fill_seconds=missed.avg_signal_to_fill_seconds,
        computed_at=datetime.now(timezone.utc),
    )


@dataclass
class MissedTradeStats:
    total_entry_signals: int
    missed_trade_count: int
    missed_trade_pct: float | None
    avg_signal_to_fill_seconds: float | None


async def compute_missed_trade_stats(db: AsyncSession, strategy_version_id: uuid.UUID) -> MissedTradeStats:
    """A "missed trade" is a real entry signal that never became a filled
    position — either the Risk Engine rejected it, or the order was
    submitted but didn't fill (partial/failed/cancelled). Distinguished
    from the much more common "no entry signal this candle" / "already
    holding a position" cases via decision_loop.py's risk_reasoning
    convention: those set risk_reasoning={"skipped": ...} and never reach
    check_trade at all, so they're excluded here rather than counted as
    missed. Not stage-scoped — Decision carries no stage column, so this
    spans a strategy version's entire decision history."""
    decisions = (
        await db.execute(select(Decision).where(Decision.strategy_version_id == strategy_version_id))
    ).scalars().all()

    # Real entry attempts: went through check_trade (not the generic
    # "skipped" no-signal/already-in-position path) and aren't a close
    # (closes always set trade_id; entries never do, in this engine).
    entry_attempts = [d for d in decisions if "skipped" not in d.risk_reasoning and d.trade_id is None]
    if not entry_attempts:
        return MissedTradeStats(total_entry_signals=0, missed_trade_count=0, missed_trade_pct=None, avg_signal_to_fill_seconds=None)

    risk_rejected = [d for d in entry_attempts if d.risk_decision == RiskDecision.REJECTED]
    approved = [d for d in entry_attempts if d.risk_decision != RiskDecision.REJECTED]

    order_ids = [d.order_id for d in approved if d.order_id is not None]
    orders_by_id: dict[uuid.UUID, Order] = {}
    if order_ids:
        orders = (await db.execute(select(Order).where(Order.id.in_(order_ids)))).scalars().all()
        orders_by_id = {o.id: o for o in orders}

    unfilled = [
        d for d in approved
        if d.order_id is None or orders_by_id.get(d.order_id) is None
        or orders_by_id[d.order_id].status != OrderStatus.FILLED
    ]

    fill_latencies = []
    for d in approved:
        order = orders_by_id.get(d.order_id) if d.order_id else None
        if order is not None and order.status == OrderStatus.FILLED and order.filled_at is not None:
            fill_latencies.append((order.filled_at - d.market_timestamp).total_seconds())

    missed_trade_count = len(risk_rejected) + len(unfilled)
    total = len(entry_attempts)
    return MissedTradeStats(
        total_entry_signals=total,
        missed_trade_count=missed_trade_count,
        missed_trade_pct=missed_trade_count / total if total else None,
        avg_signal_to_fill_seconds=(sum(fill_latencies) / len(fill_latencies)) if fill_latencies else None,
    )


REALITY_GAP_METRICS = (
    "net_return_pct", "max_drawdown_pct", "win_rate", "profit_factor",
    "total_fees", "total_funding", "total_slippage_cost", "avg_trade_net_pnl",
    "avg_latency_ms", "missed_trade_pct", "avg_signal_to_fill_seconds",
)


async def compute_reality_gap(
    db: AsyncSession, strategy_version_id: uuid.UUID, from_stage: StrategyStage, to_stage: StrategyStage
) -> dict:
    """Pulls the most recent StageMetrics row per stage and returns
    per-metric {from, to, pct_change} across every metric StageMetrics
    tracks — not just PnL/drawdown/win-rate/profit-factor, but cost drag
    (fees/funding/slippage) and execution quality (latency/missed fills)
    too, so a degradation can be attributed to a specific cause. Positive
    pct_change = improved at the later stage, negative = degraded (the
    "reality gap"). Raises ValueError if either stage has no metrics yet."""
    from_row = await latest_stage_metrics(db, strategy_version_id, from_stage)
    to_row = await latest_stage_metrics(db, strategy_version_id, to_stage)
    if from_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {from_stage.value}")
    if to_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {to_stage.value}")

    result: dict = {"from_stage": from_stage.value, "to_stage": to_stage.value}
    for metric in REALITY_GAP_METRICS:
        from_value = getattr(from_row, metric)
        to_value = getattr(to_row, metric)
        result[metric] = {"from": from_value, "to": to_value, "pct_change": pct_change(from_value, to_value)}
    return result


async def latest_stage_metrics(db: AsyncSession, strategy_version_id: uuid.UUID, stage: StrategyStage) -> StageMetrics | None:
    return (
        await db.execute(
            select(StageMetrics)
            .where(StageMetrics.strategy_version_id == strategy_version_id, StageMetrics.stage == stage)
            .order_by(StageMetrics.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
