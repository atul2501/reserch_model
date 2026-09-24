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
from app.analytics.performance_metrics_engine import PROFIT_FACTOR_CAP, capped_profit_factor
from app.models.enums import AgentStatus, OrderStatus, RiskDecision, StrategyStage
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
        # An all-winning run has an infinite profit factor: stored at the cap (None would FAIL the promotion gate).
        profit_factor=(PROFIT_FACTOR_CAP if profit_factor == float("inf") else profit_factor),
        trade_count=trade_count,
        total_fees=sum(t.fee for t in result.trades) if result.trades else None,
        total_slippage_cost=sum(t.slippage_cost for t in result.trades) if result.trades else None,
        total_funding=sum(t.funding for t in result.trades) if result.trades else None,
        avg_trade_net_pnl=(sum(t.net_pnl for t in result.trades) / trade_count) if trade_count else None,
        # No latency/missed-fill concept inside run_backtest; funding IS simulated from exchange settlements.
        observed_days=result.observed_days, period_start_ms=result.first_bar_open_ms, period_end_ms=result.last_bar_open_ms,
        bar_count=result.bars_simulated or None,
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
        (PROFIT_FACTOR_CAP if w.result.profit_factor == float("inf") else w.result.profit_factor)
        for w in report.windows if w.result.profit_factor is not None
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
        total_funding=sum(t.funding for t in all_trades) if all_trades else None,
        avg_trade_net_pnl=(sum(t.net_pnl for t in all_trades) / trade_count) if trade_count else None,
        # The reported return is the MEAN per-window return, so the matching observation length is the mean window.
        observed_days=(sum(w.result.observed_days or 0.0 for w in report.windows) / len(report.windows)) if report.windows else None,
        period_start_ms=report.windows[0].result.first_bar_open_ms if report.windows else None,
        period_end_ms=report.windows[-1].result.last_bar_open_ms if report.windows else None,
        bar_count=sum(w.result.bars_simulated for w in report.windows) or None,
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

    # STAGE-scoped performance. Agent equity/max_drawdown are LIFETIME values (every stage a version has been through),
    # so they cannot describe "how did this stage perform". Return and drawdown are therefore rebuilt from this stage's
    # own closed trades: realized PnL with any bad debt added back (the account cannot lose more than it holds), over
    # the mean starting capital - i.e. the return of ONE continuous account observed for `observed_days` agent-days.
    now = datetime.now(timezone.utc)
    mean_starting = sum(a.starting_balance for a in agents) / len(agents)
    stage_pnl = sum(t.net_pnl + (getattr(t, "bad_debt", 0.0) or 0.0) for t in trades)
    net_return_pct = stage_pnl / mean_starting if mean_starting else 0.0
    by_agent: dict[uuid.UUID, list[Trade]] = {}
    for t in sorted(trades, key=lambda t: t.closed_at):
        by_agent.setdefault(t.agent_id, []).append(t)
    starting_by_agent = {a.id: a.starting_balance for a in agents}
    max_drawdown_pct = max(
        (_max_drawdown(starting_by_agent.get(aid, mean_starting), [t.net_pnl + (t.bad_debt or 0.0) for t in ts])
         for aid, ts in by_agent.items()), default=0.0,
    )

    def _lifetime_days(a: Agent) -> float:
        end = a.death_timestamp or (a.updated_at if a.status == AgentStatus.RETIRED else now)
        return max(0.0, (end - a.created_at).total_seconds() / 86_400)

    observed_days = sum(_lifetime_days(a) for a in agents)
    starts = [int(a.created_at.timestamp() * 1000) for a in agents]

    win_rate = None
    profit_factor = None
    avg_trade_net_pnl = None
    if trades:
        wins = sum(1 for t in trades if t.net_pnl > 0)
        win_rate = wins / len(trades)
        gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        profit_factor = capped_profit_factor(gross_win, gross_loss)
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
        observed_days=observed_days, period_start_ms=min(starts), period_end_ms=int(now.timestamp() * 1000),
        computed_at=now,
    )


def _max_drawdown(starting: float, pnls: list[float]) -> float:
    """Peak-to-trough drawdown of the account built from `starting` plus each closed trade's PnL, in order."""
    equity = peak = starting
    worst = 0.0
    for p in pnls:
        equity = max(0.0, equity + p)
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


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
    # --- normalised / added so different-length observations are compared fairly ---
    "trade_count", "net_pnl", "net_return_per_day", "trade_count_per_day", "fees_per_trade", "slippage_per_trade",
    "funding_per_day",
)


def _rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _metric_value(row: StageMetrics, name: str) -> float | None:
    """Raw column, or a derived per-unit metric. Derived ones are what make a 14-day backtest and a 2-day paper run
    comparable at all: totals scale with the observation length, rates do not."""
    days = row.observed_days
    if name == "net_return_per_day":
        return _rate(row.net_return_pct, days)
    if name == "trade_count_per_day":
        return _rate(float(row.trade_count), days)
    if name == "fees_per_trade":
        return _rate(row.total_fees, float(row.trade_count) if row.trade_count else None)
    if name == "slippage_per_trade":
        return _rate(row.total_slippage_cost, float(row.trade_count) if row.trade_count else None)
    if name == "funding_per_day":
        return _rate(row.total_funding, days)
    if name == "net_pnl":
        return row.avg_trade_net_pnl * row.trade_count if row.avg_trade_net_pnl is not None else None
    return getattr(row, name)


def comparability(from_row: StageMetrics, to_row: StageMetrics, *, min_days: float | None = None, min_trades: int | None = None) -> tuple[bool, list[str]]:
    """Whether the two stages can be used as RELIABLE evidence against each other. Never true for stages with an unknown
    observation window (legacy rows) or too little time/too few trades on either side."""
    from app.core.config import get_settings

    s = get_settings()
    min_days = s.reality_gap_min_observation_days if min_days is None else min_days
    min_trades = s.reality_gap_min_trades if min_trades is None else min_trades
    reasons: list[str] = []
    for label, row in (("from", from_row), ("to", to_row)):
        if row.observed_days is None:
            reasons.append(f"{label}_stage_observation_window_unknown")
        elif row.observed_days < min_days:
            reasons.append(f"{label}_stage_observed_{row.observed_days:.2f}d < required {min_days}d")
        if row.trade_count < min_trades:
            reasons.append(f"{label}_stage_trade_count_{row.trade_count} < required {min_trades}")
    return (not reasons), reasons


async def compute_reality_gap(
    db: AsyncSession, strategy_version_id: uuid.UUID, from_stage: StrategyStage, to_stage: StrategyStage
) -> dict:
    """Pulls the most recent StageMetrics row per stage and returns per-metric {from, to, pct_change} across every
    metric StageMetrics tracks: PnL, drawdown, win rate, profit factor, cost drag (fees/funding/slippage), execution
    quality (latency/missed fills), trade count - and PER-DAY / PER-TRADE normalisations so stages of different length
    are compared like for like. Positive pct_change = improved at the later stage, negative = degraded.

    The result also carries `comparable` + `not_comparable_reasons`: the numbers are always reported, but a gap between
    stages with too little observed time or too few trades (or an unknown window) is flagged UNRELIABLE and the
    promotion gate treats it as missing evidence. Raises ValueError if either stage has no metrics yet."""
    from_row = await latest_stage_metrics(db, strategy_version_id, from_stage)
    to_row = await latest_stage_metrics(db, strategy_version_id, to_stage)
    if from_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {from_stage.value}")
    if to_row is None:
        raise ValueError(f"no StageMetrics recorded for {strategy_version_id} at stage {to_stage.value}")

    ok, reasons = comparability(from_row, to_row)
    result: dict = {
        "from_stage": from_stage.value, "to_stage": to_stage.value, "comparable": ok, "not_comparable_reasons": reasons,
        "from_observed_days": from_row.observed_days, "to_observed_days": to_row.observed_days,
    }
    for metric in REALITY_GAP_METRICS:
        from_value = _metric_value(from_row, metric)
        to_value = _metric_value(to_row, metric)
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
