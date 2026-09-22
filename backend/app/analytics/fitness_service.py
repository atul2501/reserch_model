"""Wires the previously-uncalled `compute_fitness` (app/analytics/
fitness_engine.py) to real persisted data, so `Agent.fitness` — read by
`app/evolution/breeding.py::select_survivors` for every breeding cycle —
actually means something instead of always falling back to raw equity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.fitness_engine import FitnessInputs, FitnessWeights, compute_fitness
from app.analytics.performance_metrics_engine import compute_trade_stats
from app.analytics.performance_metrics_service import compute_and_persist_agent_performance_metric
from app.backtesting.stage_metrics_service import latest_stage_metrics
from app.models.agent import Agent
from app.models.enums import StrategyStage
from app.models.metrics import FitnessScore
from app.models.trading import Trade


@dataclass
class FitnessSummary:
    generation: int
    agent_count: int
    mean_fitness: float | None
    min_fitness: float | None
    max_fitness: float | None


async def compute_and_persist_agent_fitness(
    db: AsyncSession, *, generation: int, weights: FitnessWeights | None = None
) -> FitnessSummary:
    """For every Agent in `generation`: computes+persists a PerformanceMetric
    snapshot, builds FitnessInputs from it plus the agent's StrategyVersion's
    latest OOS/walk-forward StageMetrics, calls compute_fitness, persists a
    FitnessScore row, and writes the result onto Agent.fitness. Caller
    commits."""
    agents = (await db.execute(select(Agent).where(Agent.generation == generation))).scalars().all()

    as_of = datetime.now(timezone.utc)
    fitness_values: list[float] = []

    for agent in agents:
        metric = await compute_and_persist_agent_performance_metric(db, agent, as_of=as_of)

        trades = (await db.execute(select(Trade).where(Trade.agent_id == agent.id))).scalars().all()
        stats = compute_trade_stats([t.net_pnl for t in trades], [t.holding_seconds for t in trades])
        return_volatility = (
            abs(stats.return_volatility / agent.starting_balance)
            if stats.return_volatility is not None and agent.starting_balance
            else None
        )

        oos_row = await latest_stage_metrics(db, agent.strategy_version_id, StrategyStage.OUT_OF_SAMPLE)
        wf_row = await latest_stage_metrics(db, agent.strategy_version_id, StrategyStage.WALK_FORWARD)

        inputs = FitnessInputs(
            net_return_pct=metric.roi,
            profit_factor=metric.profit_factor,
            max_drawdown_pct=agent.max_drawdown,
            expectancy=metric.expectancy,
            trade_count=metric.trade_count,
            win_rate=metric.win_rate,
            survival_days=metric.survival_seconds / 86400.0,
            sharpe_like=metric.sharpe_like,
            oos_score=oos_row.oos_score if oos_row else None,
            walk_forward_score=wf_row.walk_forward_consistency if wf_row else None,
            return_volatility=return_volatility,
        )

        result = compute_fitness(inputs, weights)

        db.add(
            FitnessScore(
                agent_id=agent.id,
                as_of=as_of,
                fitness=result.fitness,
                return_score=result.return_score,
                risk_score=result.risk_score,
                consistency_score=result.consistency_score,
                robustness_score=result.robustness_score,
                oos_score=result.oos_score,
                drawdown_penalty=result.drawdown_penalty,
                instability_penalty=result.instability_penalty,
                weights_used=result.weights_used,
            )
        )
        agent.fitness = result.fitness
        fitness_values.append(result.fitness)

    return FitnessSummary(
        generation=generation,
        agent_count=len(agents),
        mean_fitness=(sum(fitness_values) / len(fitness_values)) if fitness_values else None,
        min_fitness=min(fitness_values) if fitness_values else None,
        max_fitness=max(fitness_values) if fitness_values else None,
    )
