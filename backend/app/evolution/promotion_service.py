"""Wires evolution/champion.py's promotion-decision logic (previously
uncalled) to real persisted data and actually updates StrategyVersion rows
(spec section 28).

Champion/challenger competition is scoped to a Strategy lineage: does this
version of the strategy beat the version it would replace, not cross-family
competition.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.stage_metrics_service import latest_stage_metrics
from app.evolution.champion import CandidateMetrics, PromotionCriteria, PromotionDecision, evaluate_promotion
from app.models.agent import Agent
from app.models.enums import ChampionStatus, StrategyStage
from app.models.strategy import StrategyVersion

# Explicit minimum track-record gate, on top of champion.py's
# min_fitness_improvement margin: a challenger must have run in its current
# stage for at least this many days before it's even eligible for
# promotion, so a short lucky streak can never unseat the champion.
MIN_STAGE_DAYS = 14


async def evaluate_and_promote(
    db: AsyncSession,
    strategy_version_id: uuid.UUID,
    *,
    stage: StrategyStage,
    criteria: PromotionCriteria | None = None,
) -> PromotionDecision:
    """Evaluates whether `strategy_version_id`'s metrics at `stage` justify
    promoting it to CHAMPION within its Strategy lineage. If promoted, sets
    the previous champion's status to RETIRED and this version's to
    CHAMPION, and commits. Returns the decision either way."""
    criteria = criteria or PromotionCriteria()

    challenger_version = await db.get(StrategyVersion, strategy_version_id)
    if challenger_version is None:
        raise ValueError(f"strategy_version {strategy_version_id} not found")

    challenger_stage_metrics = await latest_stage_metrics(db, strategy_version_id, stage)
    if challenger_stage_metrics is None:
        return PromotionDecision(promote=False, reasons=["no_stage_metrics_recorded"])

    track_record_reasons: list[str] = []
    days_in_stage = (challenger_stage_metrics.computed_at - challenger_version.created_at).days
    if days_in_stage < MIN_STAGE_DAYS:
        track_record_reasons.append(
            f"stage_track_record {days_in_stage}d < required {MIN_STAGE_DAYS}d"
        )

    challenger_fitness = await _average_agent_fitness(db, strategy_version_id)
    challenger_metrics = CandidateMetrics(
        trade_count=challenger_stage_metrics.trade_count,
        oos_score=challenger_stage_metrics.oos_score,
        walk_forward_consistency=challenger_stage_metrics.walk_forward_consistency,
        max_drawdown=challenger_stage_metrics.max_drawdown_pct,
        profit_factor=challenger_stage_metrics.profit_factor,
        fitness=challenger_fitness,
    )

    current_champion = (
        await db.execute(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == challenger_version.strategy_id,
                StrategyVersion.champion_status == ChampionStatus.CHAMPION,
            )
        )
    ).scalar_one_or_none()

    champion_metrics = None
    if current_champion is not None:
        champion_stage_metrics = await latest_stage_metrics(db, current_champion.id, stage)
        if champion_stage_metrics is not None:
            champion_metrics = CandidateMetrics(
                trade_count=champion_stage_metrics.trade_count,
                oos_score=champion_stage_metrics.oos_score,
                walk_forward_consistency=champion_stage_metrics.walk_forward_consistency,
                max_drawdown=champion_stage_metrics.max_drawdown_pct,
                profit_factor=champion_stage_metrics.profit_factor,
                fitness=await _average_agent_fitness(db, current_champion.id),
            )

    decision = evaluate_promotion(challenger_metrics, champion_metrics, criteria)
    decision.reasons = decision.reasons + track_record_reasons
    decision.promote = decision.promote and not track_record_reasons

    if decision.promote:
        if current_champion is not None:
            current_champion.champion_status = ChampionStatus.RETIRED
        challenger_version.champion_status = ChampionStatus.CHAMPION
        await db.commit()

    return decision


async def _average_agent_fitness(db: AsyncSession, strategy_version_id: uuid.UUID) -> float:
    avg_fitness = (
        await db.execute(
            select(func.avg(Agent.fitness)).where(Agent.strategy_version_id == strategy_version_id)
        )
    ).scalar_one_or_none()
    return float(avg_fitness) if avg_fitness is not None else 0.0
