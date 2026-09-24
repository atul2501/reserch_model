"""Wires compute_fitness to real persisted data, so Agent.fitness — read by
breeding's select_survivors — means something. Batch-loaded (a handful of
queries for the whole generation, not several per agent).

Selection-safety: the `oos_score` used here is the VALIDATION-slice score
(stored on the BACKTEST StageMetrics row). The protected FINAL out-of-sample
score (OUT_OF_SAMPLE row / OosEvaluation) is deliberately NOT read — it may
only gate promotion, never influence which strategies breed.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.analytics.performance_metrics_engine import compute_trade_stats
from app.analytics.performance_metrics_service import compute_and_persist_agent_performance_metric
from app.models.adversarial import AdversarialTestReport
from app.models.agent import Agent
from app.models.enums import AgentStatus, StrategyStage
from app.models.metrics import FitnessScore
from app.models.regime_validation import RegimeValidationReport
from app.models.stage_metrics import StageMetrics
from app.models.trading import Trade

# Regime classification -> robustness score. Specialists are NOT rejected: they
# score meaningfully (0.6) and champion selection can use them for their regime.
REGIME_CLASS_SCORE = {"ROBUST": 1.0, "REGIME_SPECIALIST": 0.6, "FRAGILE": 0.25, "UNSTABLE": 0.1}


@dataclass
class FitnessSummary:
    generation: int
    agent_count: int
    mean_fitness: float | None
    min_fitness: float | None
    max_fitness: float | None


async def _latest_by_version(db: AsyncSession, model, version_ids, extra_filter=None) -> dict[uuid.UUID, Any]:
    stmt = select(model).where(model.strategy_version_id.in_(version_ids)).order_by(model.computed_at.desc())
    if extra_filter is not None:
        stmt = stmt.where(extra_filter)
    latest: dict[uuid.UUID, Any] = {}
    for row in (await db.execute(stmt)).scalars().all():
        latest.setdefault(row.strategy_version_id, row)  # first seen == newest
    return latest


def _overlaps(trade: Trade, window_ms: tuple[int, int]) -> bool:
    lo, hi = window_ms
    opened = int(trade.opened_at.timestamp() * 1000)
    closed = int(trade.closed_at.timestamp() * 1000)
    return closed >= lo and opened <= hi


def _daily_consistency(trades: list[Trade]) -> float | None:
    by_day: dict = defaultdict(float)
    for t in trades:
        by_day[t.closed_at.date()] += t.net_pnl
    if len(by_day) < 2:
        return None
    return sum(1 for v in by_day.values() if v > 0) / len(by_day)


async def compute_and_persist_agent_fitness(
    db: AsyncSession,
    *,
    generation: int,
    weights: FitnessWeights | None = None,
    correlation_by_agent: dict[uuid.UUID, float] | None = None,
    oos_window_ms: tuple[int, int] | None = None,
) -> FitnessSummary:
    """For every Agent in `generation`: persists a PerformanceMetric snapshot,
    builds FitnessInputs (paper results + VALIDATION OOS + walk-forward +
    regime + adversarial + correlation), calls compute_fitness, persists a
    FitnessScore row and writes the result onto Agent.fitness. Caller commits.

    `oos_window_ms` = the sealed OOS holdout's (start, end): any paper trade whose life overlaps it is EXCLUDED, so
    selection can never be influenced by performance during the protected period."""
    weights = weights or FitnessWeights.from_settings()
    agents = (await db.execute(select(Agent).where(Agent.generation == generation))).scalars().all()
    if not agents:
        return FitnessSummary(generation, 0, None, None, None)

    agent_ids = [a.id for a in agents]
    version_ids = {a.strategy_version_id for a in agents}

    # ---- batch loads: one query each for the whole generation ------------- #
    trades_by_agent: dict[uuid.UUID, list[Trade]] = defaultdict(list)
    for t in (
        await db.execute(select(Trade).where(Trade.agent_id.in_(agent_ids)).order_by(Trade.closed_at))
    ).scalars().all():
        if oos_window_ms is not None and _overlaps(t, oos_window_ms):
            continue
        trades_by_agent[t.agent_id].append(t)
    backtest_rows = await _latest_by_version(db, StageMetrics, version_ids, StageMetrics.stage == StrategyStage.BACKTEST)
    wfo_rows = await _latest_by_version(db, StageMetrics, version_ids, StageMetrics.stage == StrategyStage.WALK_FORWARD)
    regime_rows = await _latest_by_version(db, RegimeValidationReport, version_ids)
    adversarial_rows = await _latest_by_version(db, AdversarialTestReport, version_ids)

    as_of = datetime.now(timezone.utc)
    fitness_values: list[float] = []
    for agent in agents:
        trades = trades_by_agent.get(agent.id, [])
        metric = await compute_and_persist_agent_performance_metric(db, agent, as_of=as_of, trades=trades)
        stats = compute_trade_stats([t.net_pnl for t in trades], [t.holding_seconds for t in trades])
        return_volatility = (
            abs(stats.return_volatility / agent.starting_balance)
            if stats.return_volatility is not None and agent.starting_balance else None
        )
        bt = backtest_rows.get(agent.strategy_version_id)
        wfo = wfo_rows.get(agent.strategy_version_id)
        regime = regime_rows.get(agent.strategy_version_id)
        adversarial = adversarial_rows.get(agent.strategy_version_id)

        inputs = FitnessInputs(
            net_return_pct=metric.roi,
            profit_factor=metric.profit_factor,
            max_drawdown_pct=agent.max_drawdown,
            expectancy=metric.expectancy,
            trade_count=metric.trade_count,
            win_rate=metric.win_rate,
            survival_days=metric.survival_seconds / 86400.0,
            sharpe_like=metric.sharpe_like,
            oos_score=bt.oos_score if bt is not None else None,
            walk_forward_score=wfo.walk_forward_consistency if wfo is not None else None,
            return_volatility=return_volatility,
            mean_pairwise_correlation=(correlation_by_agent or {}).get(agent.id),
            regime_robustness=REGIME_CLASS_SCORE.get(regime.classification) if regime is not None else None,
            adversarial_robustness=adversarial.robustness_score if adversarial is not None else None,
            starting_balance=agent.starting_balance,
            daily_consistency=_daily_consistency(trades),
            dead=agent.status == AgentStatus.DEAD,
        )
        result = compute_fitness(inputs, weights)
        db.add(
            FitnessScore(
                agent_id=agent.id, as_of=as_of, fitness=result.fitness, return_score=result.return_score,
                risk_score=result.risk_score, consistency_score=result.consistency_score,
                robustness_score=result.robustness_score, oos_score=result.oos_score,
                drawdown_penalty=result.drawdown_penalty, instability_penalty=result.instability_penalty,
                correlation_penalty=result.correlation_penalty, expectancy_score=result.expectancy_score,
                regime_score=result.regime_score, adversarial_score=result.adversarial_score,
                weights_used=result.weights_used,
            )
        )
        agent.fitness = result.fitness
        fitness_values.append(result.fitness)

    return FitnessSummary(
        generation=generation, agent_count=len(agents),
        mean_fitness=sum(fitness_values) / len(fitness_values),
        min_fitness=min(fitness_values), max_fitness=max(fitness_values),
    )
