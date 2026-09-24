"""Wires evolution/champion.py's promotion-decision logic (previously
uncalled) to real persisted data and actually updates StrategyVersion rows
(spec section 28).

Champion/challenger competition is scoped to a Strategy lineage: does this
version of the strategy beat the version it would replace, not cross-family
competition.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.stage_metrics_service import compute_reality_gap, latest_stage_metrics
from app.models.adversarial import AdversarialTestReport
from app.models.metrics import FitnessScore
from app.models.regime_validation import RegimeValidationReport
from app.models.strategy import Strategy
from app.evolution.champion import CandidateMetrics, PromotionCriteria, PromotionDecision, evaluate_promotion
from app.models.agent import Agent
from app.models.enums import ChampionStatus, EvolutionEventType, StrategyStage
from app.models.evolution import EvolutionEvent
from app.models.strategy import StrategyVersion

# The minimum track-record gate is `PromotionCriteria.min_stage_days` (settings: CHAMPION_MIN_STAGE_DAYS): a challenger
# must have run in its current stage that long before it is even eligible, so a short lucky streak can never unseat
# the champion. (It used to be a hard-coded 14 that ignored the setting.)


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
    criteria = criteria or PromotionCriteria.from_settings()

    challenger_version = await db.get(StrategyVersion, strategy_version_id)
    if challenger_version is None:
        raise ValueError(f"strategy_version {strategy_version_id} not found")

    challenger_stage_metrics = await latest_stage_metrics(db, strategy_version_id, stage)
    if challenger_stage_metrics is None:
        return PromotionDecision(promote=False, reasons=["no_stage_metrics_recorded"])

    track_record_reasons: list[str] = []
    # Real time in the current stage (not "created -> metrics computed").
    entered = challenger_version.stage_entered_at or challenger_version.created_at
    days_in_stage = (datetime.now(timezone.utc) - entered).days
    required_days = max(criteria.min_stage_days, 0)
    if days_in_stage < required_days:
        track_record_reasons.append(f"stage_track_record {days_in_stage}d < required {required_days}d")

    challenger_metrics = await _candidate_metrics(db, challenger_version, challenger_stage_metrics, stage)

    # Champion competition is scoped to a LINEAGE (a child is judged against its
    # ancestors), falling back to the strategy itself for pre-lineage rows.
    strategy = await db.get(Strategy, challenger_version.strategy_id)
    lineage_id = (strategy.lineage_id if strategy is not None and strategy.lineage_id else challenger_version.strategy_id)
    lineage_strategy_ids = [
        r for (r,) in (
            await db.execute(select(Strategy.id).where((Strategy.lineage_id == lineage_id) | (Strategy.id == lineage_id)))
        ).all()
    ] or [challenger_version.strategy_id]
    current_champion = (
        await db.execute(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id.in_(lineage_strategy_ids),
                StrategyVersion.champion_status == ChampionStatus.CHAMPION,
            )
        )
    ).scalars().first()

    champion_metrics = None
    if current_champion is not None:
        champion_stage_metrics = await latest_stage_metrics(db, current_champion.id, stage)
        if champion_stage_metrics is not None:
            champion_metrics = await _candidate_metrics(db, current_champion, champion_stage_metrics, stage)

    decision = evaluate_promotion(challenger_metrics, champion_metrics, criteria)
    decision.reasons = decision.reasons + track_record_reasons
    decision.promote = decision.promote and not track_record_reasons

    # Every promotion or rejection is recorded, win or lose — this is the
    # audit trail champion.py's own docstring promises but, until now, no
    # caller ever actually wrote.
    db.add(
        EvolutionEvent(
            event_type=EvolutionEventType.PROMOTION if decision.promote else EvolutionEventType.REJECTION,
            parent_strategy_version_id=current_champion.id if current_champion is not None else None,
            child_strategy_version_id=challenger_version.id,
            generation=challenger_version.generation,
            validation_result={
                "criteria": asdict(criteria),
                "challenger_metrics": asdict(challenger_metrics),
                "champion_metrics": asdict(champion_metrics) if champion_metrics is not None else None,
                "reasons": decision.reasons,
            },
            accepted=decision.promote,
            rejection_reason="; ".join(decision.reasons) if not decision.promote else None,
        )
    )

    if decision.promote:
        if current_champion is not None:
            current_champion.champion_status = ChampionStatus.RETIRED
        challenger_version.champion_status = ChampionStatus.CHAMPION
        challenger_version.promoted_at = datetime.now(timezone.utc)
        # Freeze exactly what was promoted (immutable, provenance-complete).
        best_agent = (
            await db.execute(
                select(Agent).where(Agent.strategy_version_id == challenger_version.id)
                .order_by(Agent.fitness.desc().nulls_last()).limit(1)
            )
        ).scalars().first()
        if best_agent is not None:
            from app.research.snapshots import create_agent_snapshot
            await create_agent_snapshot(db, best_agent, challenger_version, experiment_id=challenger_version.experiment_id)

    await db.commit()

    return decision


async def _average_agent_fitness(db: AsyncSession, strategy_version_id: uuid.UUID) -> float:
    avg_fitness = (
        await db.execute(
            select(func.avg(Agent.fitness)).where(Agent.strategy_version_id == strategy_version_id)
        )
    ).scalar_one_or_none()
    return float(avg_fitness) if avg_fitness is not None else 0.0


async def _candidate_metrics(db: AsyncSession, version: StrategyVersion, stage_row, stage: StrategyStage) -> CandidateMetrics:
    """Assembles ALL promotion evidence for a version. The final OOS score comes
    from the protected lockbox (OUT_OF_SAMPLE row), walk-forward from its own row."""
    oos_row = await latest_stage_metrics(db, version.id, StrategyStage.OUT_OF_SAMPLE)
    wfo_row = await latest_stage_metrics(db, version.id, StrategyStage.WALK_FORWARD)
    adversarial = (
        await db.execute(
            select(AdversarialTestReport).where(AdversarialTestReport.strategy_version_id == version.id)
            .order_by(AdversarialTestReport.computed_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    regime = (
        await db.execute(
            select(RegimeValidationReport).where(RegimeValidationReport.strategy_version_id == version.id)
            .order_by(RegimeValidationReport.computed_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    mean_corr = (
        await db.execute(
            select(func.avg(FitnessScore.correlation_penalty)).join(Agent, Agent.id == FitnessScore.agent_id)
            .where(Agent.strategy_version_id == version.id, FitnessScore.correlation_penalty.is_not(None))
        )
    ).scalar_one_or_none()

    degradation = None
    try:
        gap = await compute_reality_gap(db, version.id, StrategyStage.BACKTEST, stage)
        if gap.get("comparable"):
            # Compared PER DAY: a multi-day backtest total against a short paper run says nothing; the rates do.
            ret = gap.get("net_return_per_day", {})
            if ret.get("from") is not None and ret.get("to") is not None:
                base = abs(ret["from"]) or 1e-9
                degradation = (ret["from"] - ret["to"]) / base if ret["from"] > 0 else (0.0 if ret["to"] >= ret["from"] else 1.0)
        # not comparable => degradation stays None => "missing_evidence: reality gap not measurable" blocks promotion
    except ValueError:
        degradation = None  # a stage has no metrics yet -> missing evidence, handled by the gate

    return CandidateMetrics(
        trade_count=stage_row.trade_count,
        # The FINAL OOS evidence only. A validation-slice score is not a stand-in: missing OOS blocks promotion.
        oos_score=oos_row.oos_score if oos_row is not None else None,
        walk_forward_consistency=wfo_row.walk_forward_consistency if wfo_row is not None else stage_row.walk_forward_consistency,
        max_drawdown=stage_row.max_drawdown_pct,
        profit_factor=stage_row.profit_factor,
        fitness=await _average_agent_fitness(db, version.id),
        adversarial_robustness=adversarial.robustness_score if adversarial is not None else None,
        regime_classification=regime.classification if regime is not None else None,
        mean_correlation=float(mean_corr) if mean_corr is not None else None,
        reality_gap_return_degradation=degradation,
        paper_trade_count=stage_row.trade_count,
    )
