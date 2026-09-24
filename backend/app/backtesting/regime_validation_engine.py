"""Per-regime performance breakdown and robustness classification.

Every promising strategy should be evaluated across market regimes before
promotion — not to auto-reject uneven performance (a strategy that only
works in one regime can be a legitimate, valuable specialist), but to know
*which* kind of strategy it is: ROBUST, REGIME_SPECIALIST, FRAGILE, or
UNSTABLE. That classification feeds Champion/Challenger as an advisory
penalty, never a hard veto.

The codebase's MarketRegime enum (TREND_UP, TREND_DOWN, RANGE,
HIGH_VOLATILITY, LOW_VOLATILITY, BREAKOUT, BREAKDOWN, UNCERTAIN) is used
as-is — TREND_UP/TREND_DOWN/RANGE are this system's BULL/BEAR/SIDEWAYS.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.performance_metrics_engine import compute_trade_stats
from app.backtesting.engine import BacktestResult
from app.market.regime_lookup import load_regime_lookup, regime_at
from app.models.agent import Agent
from app.models.enums import StrategyStage
from app.models.regime_validation import RegimeValidationReport
from app.models.trading import Trade

ROBUST = "ROBUST"
REGIME_SPECIALIST = "REGIME_SPECIALIST"
FRAGILE = "FRAGILE"
UNSTABLE = "UNSTABLE"


@dataclass
class RegimeStats:
    trade_count: int
    pnl: float
    roi: float | None
    profit_factor: float | None
    win_rate: float | None
    max_drawdown_pct: float
    expectancy: float | None
    # False for a regime in which the strategy made no trade at all: it is reported (not silently absent) so the
    # coverage of the validation is visible - "untested in HIGH_VOLATILITY" is different from "fine in it".
    observed: bool = True


def _all_regimes() -> list[str]:
    from app.models.enums import MarketRegime

    return [r.value for r in MarketRegime]


def _unobserved() -> RegimeStats:
    return RegimeStats(trade_count=0, pnl=0.0, roi=None, profit_factor=None, win_rate=None, max_drawdown_pct=0.0,
                       expectancy=None, observed=False)


def compute_regime_breakdown_backtest(results: "BacktestResult | list[BacktestResult]") -> dict[str, RegimeStats]:
    """Groups backtest trades by the regime they were ENTERED in (BacktestTrade.entry_regime: the market condition
    that produced the decision), across every supplied slice (train AND validation), and reports EVERY regime -
    those without a single trade appear as `observed=False` rows."""
    results = results if isinstance(results, list) else [results]
    buckets: dict[str, list[float]] = {}
    for result in results:
        for trade in result.trades:
            regime = trade.entry_regime or trade.exit_regime or "UNKNOWN"
            buckets.setdefault(regime, []).append(trade.net_pnl)
    base = results[0].starting_equity if results else 0.0
    out = {r: _unobserved() for r in _all_regimes()}
    out.update({regime: _regime_stats_from_pnls(pnls, base) for regime, pnls in buckets.items()})
    return out


async def compute_regime_breakdown_live(
    db: AsyncSession, strategy_version_id, *, stage: StrategyStage | None = None
) -> dict[str, RegimeStats]:
    """Groups a strategy version's closed trades (across all agents
    currently on it) by regime-at-close-time, reusing the same bisect
    lookup `/api/trades/by-regime` uses. Filters to `stage` when given, so
    a challenger mid-evaluation isn't scored on trades from a different
    pipeline stage."""
    agents = (
        await db.execute(select(Agent).where(Agent.strategy_version_id == strategy_version_id))
    ).scalars().all()
    if not agents:
        return {}

    agent_ids = [a.id for a in agents]
    stmt = select(Trade.net_pnl, Trade.closed_at).where(Trade.agent_id.in_(agent_ids))
    if stage is not None:
        stmt = stmt.where(Trade.stage == stage)
    stmt = stmt.order_by(Trade.closed_at)
    trades = (await db.execute(stmt)).all()
    if not trades:
        return {}

    open_times, regimes = await load_regime_lookup(db)
    base_equity = sum(a.starting_balance for a in agents)

    buckets: dict[str, list[float]] = {}
    for net_pnl, closed_at in trades:
        regime = regime_at(int(closed_at.timestamp() * 1000), open_times, regimes)
        buckets.setdefault(regime, []).append(net_pnl)

    return {regime: _regime_stats_from_pnls(pnls, base_equity) for regime, pnls in buckets.items()}


def classify_robustness(
    per_regime: dict[str, RegimeStats],
    *,
    min_trades_per_regime: int = 10,
    robust_min_positive_regimes_pct: float = 0.7,
    specialist_min_pnl_share: float = 0.6,
) -> tuple[str, list[str]]:
    """Classifies a strategy's cross-regime behavior. Never used to reject
    a strategy outright — REGIME_SPECIALIST is a valid, non-penalized
    outcome; only FRAGILE/UNSTABLE should tighten promotion criteria
    upstream (Champion/Challenger's job, not this function's)."""
    reasoning: list[str] = []
    testable = {r: s for r, s in per_regime.items() if s.trade_count >= min_trades_per_regime}

    if len(testable) < 2:
        reasoning.append(
            f"only {len(testable)} regime(s) have >= {min_trades_per_regime} trades — "
            "insufficient cross-regime coverage to classify confidently"
        )
        return UNSTABLE, reasoning

    total_pnl = sum(s.pnl for s in testable.values())
    positive_regimes = [r for r, s in testable.items() if (s.expectancy or 0.0) > 0]
    negative_regimes = [r for r, s in testable.items() if (s.expectancy or 0.0) < 0]
    positive_pct = len(positive_regimes) / len(testable)

    if positive_pct >= robust_min_positive_regimes_pct and total_pnl > 0:
        reasoning.append(
            f"positive expectancy in {positive_pct:.0%} of {len(testable)} tested regimes, net profitable overall"
        )
        return ROBUST, reasoning

    if total_pnl > 0:
        sorted_by_pnl = sorted(testable.items(), key=lambda kv: kv[1].pnl, reverse=True)
        top_share = sum(max(s.pnl, 0.0) for _, s in sorted_by_pnl[:2]) / total_pnl
        if top_share >= specialist_min_pnl_share and len(negative_regimes) / len(testable) < 0.5:
            top_regimes = [r for r, _ in sorted_by_pnl[:2]]
            reasoning.append(
                f"concentrated in {top_regimes} ({top_share:.0%} of PnL) but not broadly losing elsewhere"
            )
            return REGIME_SPECIALIST, reasoning

    if len(negative_regimes) / len(testable) >= 0.5 and any(s.pnl > 0 for s in testable.values()):
        reasoning.append(
            f"profitable in isolated regime(s) but losing in {len(negative_regimes)}/{len(testable)} tested regimes"
        )
        return FRAGILE, reasoning

    reasoning.append("no consistent edge across tested regimes and no single-regime specialization")
    return UNSTABLE, reasoning


async def run_and_persist_regime_validation(
    db: AsyncSession,
    strategy_version_id: uuid.UUID,
    *,
    backtest_result: "BacktestResult | list[BacktestResult] | None" = None,
    stage: StrategyStage | None = None,
    min_trades_per_regime: int = 10,
    robust_min_positive_regimes_pct: float = 0.7,
    specialist_min_pnl_share: float = 0.6,
) -> RegimeValidationReport:
    """Computes and persists a full regime breakdown + classification for
    `strategy_version_id`. Pass `backtest_result` to validate a backtest
    run; omit it to validate live/paper/shadow trade history instead (via
    `stage`). Caller commits. Insert-only — history is never overwritten,
    so classification drift across a strategy's lifetime stays visible."""
    if backtest_result is not None:
        per_regime = compute_regime_breakdown_backtest(backtest_result)
    else:
        per_regime = await compute_regime_breakdown_live(db, strategy_version_id, stage=stage)

    classification, reasoning = classify_robustness(
        per_regime,
        min_trades_per_regime=min_trades_per_regime,
        robust_min_positive_regimes_pct=robust_min_positive_regimes_pct,
        specialist_min_pnl_share=specialist_min_pnl_share,
    )

    report = RegimeValidationReport(
        strategy_version_id=strategy_version_id,
        per_regime={regime: asdict(stats) for regime, stats in per_regime.items()},
        classification=classification,
        classification_reasoning=reasoning + _coverage_note(per_regime),
        computed_at=datetime.now(timezone.utc),
    )
    db.add(report)
    return report


def _coverage_note(per_regime: dict[str, RegimeStats]) -> list[str]:
    missing = sorted(r for r, s in per_regime.items() if not s.observed and r in set(_all_regimes()))
    return [f"untested regimes (no trades): {', '.join(missing)}"] if missing and len(missing) < len(_all_regimes()) else []


def _regime_stats_from_pnls(pnls_in_order: list[float], base_equity: float) -> RegimeStats:
    stats = compute_trade_stats(pnls_in_order, holding_seconds=[])
    pnl = sum(pnls_in_order)
    return RegimeStats(
        trade_count=len(pnls_in_order),
        pnl=pnl,
        roi=(pnl / base_equity) if base_equity else None,
        profit_factor=stats.profit_factor,
        win_rate=stats.win_rate,
        max_drawdown_pct=_max_drawdown_from_pnls(pnls_in_order, base_equity),
        expectancy=stats.expectancy,
    )


def _max_drawdown_from_pnls(pnls: list[float], base_equity: float) -> float:
    """Peak-to-trough drawdown of the equity curve formed by replaying only
    this regime's trades, in chronological order, against `base_equity`.
    An approximation (it skips the equity movement from other regimes'
    trades interleaved in real time), not a true time-aligned drawdown —
    but consistent with the rest of the codebase's peak-tracking approach
    (see BacktestResult.max_drawdown_pct) and the only meaningful way to
    talk about "drawdown within a regime" without a full equity-curve
    reconstruction per regime."""
    if not pnls or base_equity <= 0:
        return 0.0
    equity = base_equity
    peak = base_equity
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd
