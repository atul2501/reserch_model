"""ChampionChallengerEngine: walks a StrategyVersion through the
Candidate -> Validation -> Challenger -> Observation -> Champion Comparison
-> Promotion Decision pipeline.

`evaluate_and_promote` (promotion_service.py) remains the SINGLE
deterministic promotion gate — this module never builds a second one. Its
job is upstream of that: deciding whether a candidate is even ready to
reach the champion_comparison stage, and when it does, tightening
`PromotionCriteria` based on correlation/reality-gap/regime-validation
signals as an advisory penalty — never a hard veto, per the locked-in rule
that these signals are diversity/robustness information, not kill
switches.

StrategyVersion.dna is immutable (never mutated after creation, per its
own docstring in app/models/strategy.py) and champion snapshot immutability
follows directly from that: a "changed" strategy is always a new
StrategyVersion row, never an edit to an existing one. Nothing in this
module writes to StrategyVersion.dna — only champion_status/stage, which
are documented exceptions.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.stage_metrics_service import latest_stage_metrics
from app.evolution.champion import PromotionCriteria
from app.evolution.promotion_service import evaluate_and_promote
from app.models.adversarial import AdversarialTestReport
from app.models.champion_challenger import ChallengerEvaluation
from app.models.enums import StrategyStage
from app.models.regime_validation import RegimeValidationReport
from app.models.strategy import StrategyVersion

MIN_OBSERVATION_DAYS = 14  # matches promotion_service.MIN_STAGE_DAYS's existing track-record convention

_LIVE_DATA_STAGES = (
    StrategyStage.PAPER, StrategyStage.SHADOW, StrategyStage.SMALL_LIVE, StrategyStage.APPROVED_LIVE,
)


async def latest_challenger_evaluation(db: AsyncSession, strategy_version_id: uuid.UUID) -> ChallengerEvaluation | None:
    return (
        await db.execute(
            select(ChallengerEvaluation)
            .where(ChallengerEvaluation.strategy_version_id == strategy_version_id)
            .order_by(ChallengerEvaluation.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def advance_pipeline_stage(
    db: AsyncSession,
    strategy_version_id: uuid.UUID,
    *,
    promotion_stage: StrategyStage = StrategyStage.PAPER,
    criteria: PromotionCriteria | None = None,
    min_observation_days: int | None = None,
) -> ChallengerEvaluation:
    """Attempts to move `strategy_version_id` one step forward in the
    pipeline. Returns the resulting ChallengerEvaluation row — either a new
    stage (insert-only, so history is preserved) or the same stage again
    with updated `blocking_reasons` if it's not ready to advance yet.
    Terminal states (`promoted`/`rejected`) are returned as-is; caller
    commits."""
    version = await db.get(StrategyVersion, strategy_version_id)
    if version is None:
        raise ValueError(f"strategy_version {strategy_version_id} not found")

    previous = await latest_challenger_evaluation(db, strategy_version_id)
    current_stage = previous.pipeline_stage if previous is not None else "candidate"

    if current_stage in ("promoted", "rejected"):
        return previous

    now = datetime.now(timezone.utc)
    blocking_reasons: list[str] = []
    metrics_snapshot: dict = {}
    next_stage = current_stage

    if current_stage == "candidate":
        backtest = await latest_stage_metrics(db, strategy_version_id, StrategyStage.BACKTEST)
        if backtest is None:
            blocking_reasons.append("no_backtest_stage_metrics_yet")
        else:
            metrics_snapshot["backtest"] = {"trade_count": backtest.trade_count, "net_return_pct": backtest.net_return_pct}
            next_stage = "validation"

    elif current_stage == "validation":
        adversarial = await _latest_adversarial_report(db, strategy_version_id)
        if adversarial is None:
            blocking_reasons.append("no_adversarial_test_report_yet")
        elif not adversarial.passed:
            blocking_reasons.append(f"adversarial_testing_failed: {'; '.join(adversarial.failure_reasons)}")
        else:
            metrics_snapshot["adversarial"] = {
                "robustness_score": adversarial.robustness_score,
                "worst_case_max_drawdown_pct": adversarial.worst_case_max_drawdown_pct,
            }
            next_stage = "challenger"

    elif current_stage == "challenger":
        if version.stage not in _LIVE_DATA_STAGES:
            blocking_reasons.append(
                f"strategy_version.stage is {version.stage.value}, not yet in a live-data stage (PAPER/SHADOW/...)"
            )
        else:
            metrics_snapshot["entered_live_stage"] = version.stage.value
            next_stage = "observation"

    elif current_stage == "observation":
        required_days = min_observation_days or MIN_OBSERVATION_DAYS
        days_observed = (now - previous.entered_stage_at).days if previous else 0
        if days_observed < required_days:
            blocking_reasons.append(f"observation_track_record {days_observed}d < required {required_days}d")
        else:
            next_stage = "champion_comparison"

    elif current_stage == "champion_comparison":
        adjusted_criteria, advisory = await _build_advisory_criteria(
            db, strategy_version_id, criteria or PromotionCriteria()
        )
        metrics_snapshot["advisory"] = advisory
        decision = await evaluate_and_promote(db, strategy_version_id, stage=promotion_stage, criteria=adjusted_criteria)
        metrics_snapshot["promotion_decision"] = {"promote": decision.promote, "reasons": decision.reasons}
        if decision.promote:
            next_stage = "promoted"
        else:
            blocking_reasons.extend(decision.reasons)
            next_stage = "rejected"

    row = ChallengerEvaluation(
        strategy_version_id=strategy_version_id,
        pipeline_stage=next_stage,
        entered_stage_at=now if next_stage != current_stage else (previous.entered_stage_at if previous else now),
        min_observation_days_required=MIN_OBSERVATION_DAYS if next_stage == "observation" else None,
        metrics_snapshot=metrics_snapshot,
        blocking_reasons=blocking_reasons,
        computed_at=now,
    )
    db.add(row)
    return row


async def _latest_adversarial_report(db: AsyncSession, strategy_version_id: uuid.UUID) -> AdversarialTestReport | None:
    return (
        await db.execute(
            select(AdversarialTestReport)
            .where(AdversarialTestReport.strategy_version_id == strategy_version_id)
            .order_by(AdversarialTestReport.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_regime_validation_report(db: AsyncSession, strategy_version_id: uuid.UUID) -> RegimeValidationReport | None:
    return (
        await db.execute(
            select(RegimeValidationReport)
            .where(RegimeValidationReport.strategy_version_id == strategy_version_id)
            .order_by(RegimeValidationReport.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _build_advisory_criteria(
    db: AsyncSession, strategy_version_id: uuid.UUID, criteria: PromotionCriteria
) -> tuple[PromotionCriteria, dict]:
    """Tightens `min_fitness_improvement` for FRAGILE/UNSTABLE regime
    classification — an advisory penalty, never a hard veto: the
    candidate can still be promoted, just needs a clearer edge over the
    champion. Correlation/reality-gap are recorded for the audit trail but
    don't currently gate this module's own advancement (their job is
    upstream, in breeding-time diversity pressure and reporting)."""
    advisory: dict = {}
    adjusted = criteria

    regime_report = await _latest_regime_validation_report(db, strategy_version_id)
    if regime_report is not None:
        advisory["regime_classification"] = regime_report.classification
        if regime_report.classification in ("FRAGILE", "UNSTABLE"):
            adjusted = PromotionCriteria(**{**asdict(criteria), "min_fitness_improvement": criteria.min_fitness_improvement * 2})
            advisory["penalty_applied"] = "min_fitness_improvement doubled for FRAGILE/UNSTABLE regime classification"

    return adjusted, advisory
