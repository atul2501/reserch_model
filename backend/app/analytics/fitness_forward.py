"""Pure fitness->future engine: point-in-time reconstruction and forward windows.

LOOK-AHEAD PROTECTION (the rules that make the study scientific):

1. Fitness at T is reconstructed ONLY from trades with closed_at <= T. The
   mutable "now" columns on Agent (balance, equity, peak_equity, max_drawdown,
   realized_pnl, fitness) are NEVER read for a historical T — they include
   everything that happened after T by definition.
2. Future performance uses ONLY trades with closed_at > T (strict), bounded by
   the horizon and censored at real boundaries (agent death, generation
   rollover, end of data). Coverage < 1 is recorded, never extrapolated.
3. The reconstruction mirrors the PRODUCTION computation (fitness_service +
   performance_metrics_service + fitness_engine) — including its known
   imperfections — because the study asks "does the fitness we actually compute
   predict the future?", not "does an idealized fitness predict the future".
   Documented deviations (v1):
     * net_return_pct uses realized PnL only (starting_balance + closed-trade
       PnL), because production's agent.equity at T included open unrealized
       PnL that is not recoverable from closed trades alone;
     * drawdown/survival likewise rebuilt from the realized curve and T;
     * component evidence rows (stage metrics, regime validation, adversarial,
       correlations) are filtered to computed_at <= T.
4. Rows in fitness_forward_performance are write-once evidence: recomputing
   them with later knowledge would defeat the study (enforced by ORM listener
   + DB trigger).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.analytics.performance_metrics_engine import compute_trade_stats
from app.models.enums import AgentStatus

HORIZONS_MINUTES = (60, 360, 1440, 4320)

CENSOR_NONE = "none"
CENSOR_AGENT_DEATH = "agent_death"
CENSOR_GENERATION_ROLLOVER = "generation_rollover"
CENSOR_DATA_END = "data_end"

# Regime classification -> robustness score: the same map fitness_service uses
# (kept in sync deliberately; the analytics must score like production).
REGIME_CLASS_SCORE = {"ROBUST": 1.0, "REGIME_SPECIALIST": 0.6, "FRAGILE": 0.25, "UNSTABLE": 0.1}


@dataclass(frozen=True)
class AgentFacts:
    """The immutable facts of an agent needed at any T (no mutable state)."""
    agent_id: uuid.UUID
    generation: int
    starting_balance: float
    created_at: datetime
    death_timestamp: datetime | None
    status: AgentStatus


@dataclass(frozen=True)
class TradePoint:
    """One closed trade, reduced to what the study needs."""
    closed_at: datetime
    net_pnl: float
    notional: float          # quantity * entry_price
    opened_at: datetime


@dataclass
class ReconstructedFitness:
    fitness: float
    components: dict


def realized_curve(trades: list[TradePoint], *, starting_balance: float) -> list[tuple[datetime, float]]:
    """(closed_at, starting + cumulative net pnl) sorted by close time — the
    look-ahead-free account curve built only from the trades given (which the
    caller must already have filtered to closed_at <= T)."""
    ordered = sorted(trades, key=lambda t: t.closed_at)
    cum = starting_balance
    out: list[tuple[datetime, float]] = []
    for t in ordered:
        cum += t.net_pnl
        out.append((t.closed_at, cum))
    return out


def max_drawdown_currency(trades: list[TradePoint], *, starting_balance: float) -> float:
    """Peak-to-trough of the realized curve (currency). 0.0 when no drawdown."""
    curve = realized_curve(trades, starting_balance=starting_balance)
    peak = starting_balance
    worst = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        worst = min(worst, eq - peak)
    return worst if worst < 0 else 0.0


def _daily_consistency(trades: list[TradePoint]) -> float | None:
    by_day: dict[object, float] = {}
    for t in trades:
        by_day[t.closed_at.date()] = by_day.get(t.closed_at.date(), 0.0) + t.net_pnl
    if len(by_day) < 2:
        return None
    return sum(1 for v in by_day.values() if v > 0) / len(by_day)


def reconstruct_fitness_at(
    facts: AgentFacts,
    trades_upto_t: list[TradePoint],
    *,
    as_of: datetime,
    weights: FitnessWeights,
    stage_evidence: dict | None = None,
) -> ReconstructedFitness:
    """The production fitness an agent WOULD have had at T, from closed trades only.

    `stage_evidence` carries the optional component inputs (oos_score,
    walk_forward_consistency, regime_robustness, adversarial_robustness,
    mean_pairwise_correlation) already filtered to computed_at <= T by the caller.
    """
    trades = [t for t in trades_upto_t if t.closed_at <= as_of]   # defensive double filter
    stats = compute_trade_stats([t.net_pnl for t in trades], [0 for _ in trades])
    equity_t = facts.starting_balance + sum(t.net_pnl for t in trades)
    roi = (equity_t - facts.starting_balance) / facts.starting_balance if facts.starting_balance else 0.0
    dd_currency = max_drawdown_currency(trades, starting_balance=facts.starting_balance)
    dd_pct = abs(dd_currency / facts.starting_balance) if facts.starting_balance else 0.0

    end = as_of
    if facts.death_timestamp is not None and facts.death_timestamp <= as_of:
        end = facts.death_timestamp
    survival_seconds = max(0.0, (end - facts.created_at).total_seconds())
    dead = facts.status == AgentStatus.DEAD and facts.death_timestamp is not None and facts.death_timestamp <= as_of

    ev = stage_evidence or {}
    stdev = stats.return_volatility
    return_volatility = abs(stdev / facts.starting_balance) if stdev is not None and facts.starting_balance else None

    inputs = FitnessInputs(
        net_return_pct=roi,
        profit_factor=stats.profit_factor,
        max_drawdown_pct=dd_pct,
        expectancy=stats.expectancy,
        trade_count=len(trades),
        win_rate=stats.win_rate,
        survival_days=survival_seconds / 86400.0,
        sharpe_like=stats.sharpe_like,
        oos_score=ev.get("oos_score"),
        walk_forward_score=ev.get("walk_forward_consistency"),
        return_volatility=return_volatility,
        mean_pairwise_correlation=ev.get("mean_pairwise_correlation"),
        regime_robustness=REGIME_CLASS_SCORE.get(ev.get("regime_classification")) if ev.get("regime_classification") else None,
        adversarial_robustness=ev.get("adversarial_robustness"),
        starting_balance=facts.starting_balance,
        daily_consistency=_daily_consistency(trades),
        dead=dead,
    )
    result = compute_fitness(inputs, weights)
    components = {
        "return_score": result.return_score, "risk_score": result.risk_score,
        "consistency_score": result.consistency_score, "robustness_score": result.robustness_score,
        "oos_score": result.oos_score, "drawdown_penalty": result.drawdown_penalty,
        "instability_penalty": result.instability_penalty, "correlation_penalty": result.correlation_penalty,
        "expectancy_score": result.expectancy_score, "regime_score": result.regime_score,
        "adversarial_score": result.adversarial_score, "inactivity_penalty": result.inactivity_penalty,
        "death_penalty": result.death_penalty, "trade_count": len(trades), "equity_at_t": equity_t,
        "survival_days": survival_seconds / 86400.0, "realized_drawdown_pct": dd_pct,
    }
    return ReconstructedFitness(fitness=result.fitness, components=components)


def weights_from_recorded(weights_used: dict | None) -> FitnessWeights:
    """The weights of a recorded snapshot (fitness_scores.weights_used), falling
    back to current settings — so reconstruction matches what production would
    have used at that time."""
    if weights_used:
        try:
            return FitnessWeights(**{k: float(v) for k, v in weights_used.items()})
        except TypeError:
            pass
    from app.core.config import get_settings

    return FitnessWeights.from_settings(get_settings())


@dataclass(frozen=True)
class CensoredWindow:
    window_start: datetime
    window_end_planned: datetime
    window_end_actual: datetime
    censor_reason: str
    window_coverage: float


def forward_window(
    as_of: datetime, horizon_minutes: int, *, death_at: datetime | None,
    generation_rollover_at: datetime | None, data_end: datetime,
) -> CensoredWindow:
    """The honest (T, T+h] window: truncated at the earliest real boundary."""
    planned = as_of + timedelta(minutes=horizon_minutes)
    candidates = []
    if death_at is not None and death_at > as_of:
        candidates.append((death_at, CENSOR_AGENT_DEATH))
    if generation_rollover_at is not None and generation_rollover_at > as_of:
        candidates.append((generation_rollover_at, CENSOR_GENERATION_ROLLOVER))
    if data_end > as_of:
        candidates.append((data_end, CENSOR_DATA_END))

    actual = planned
    reason = CENSOR_NONE
    for boundary, why in sorted(candidates, key=lambda c: c[0]):
        if boundary < actual:
            actual = boundary
            reason = why

    planned_span = (planned - as_of).total_seconds()
    coverage = 1.0
    if planned_span > 0:
        coverage = max(0.0, min(1.0, (actual - as_of).total_seconds() / planned_span))
    return CensoredWindow(as_of, planned, actual, reason, coverage)


@dataclass(frozen=True)
class ForwardPerformance:
    trade_count: int
    net_pnl: float | None
    net_bps: float | None
    expectancy: float | None
    win_rate: float | None
    max_drawdown_currency: float | None


def forward_performance(
    trades: list[TradePoint], window: CensoredWindow, *, starting_balance: float,
) -> ForwardPerformance:
    """Realized performance strictly inside (T, window_end_actual].

    The drawdown is measured on the equity curve that STARTS from the realized
    equity at T (starting_balance + closed PnL up to T — no look-ahead), so a
    big pre-T drawdown can never leak into the forward window's number.
    """
    future = [t for t in trades if window.window_start < t.closed_at <= window.window_end_actual]
    if not future:
        return ForwardPerformance(0, None, None, None, None, None)

    net = [t.net_pnl for t in future]
    notional = sum(t.notional for t in future)
    wins = sum(1 for p in net if p > 0)
    base = starting_balance  # drawdown measured from the window's own curve, not lifetime equity
    dd = _drawdown_from_curve([t.net_pnl for t in sorted(future, key=lambda t: t.closed_at)], base)
    return ForwardPerformance(
        trade_count=len(future),
        net_pnl=sum(net),
        net_bps=(1e4 * sum(net) / notional) if notional > 0 else None,
        expectancy=sum(net) / len(net),
        win_rate=wins / len(future),
        max_drawdown_currency=dd,
    )


def _drawdown_from_curve(net_pnls: list[float], base_equity: float) -> float:
    peak = base_equity
    cum = base_equity
    worst = 0.0
    for p in net_pnls:
        cum += p
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst if worst < 0 else 0.0