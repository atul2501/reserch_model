"""ChampionChallengerEngine: the Candidate -> Validation -> Challenger ->
Observation -> Champion Comparison -> Promotion Decision state machine,
consuming StageMetrics/AdversarialTestReport/RegimeValidationReport as
advisory inputs — never a second promotion gate (evaluate_and_promote
stays the only one)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.helpers_agents import add_promotion_evidence
from sqlalchemy import select

from app.api.routes.champion_challenger import list_challengers
from app.core.config import get_settings
from app.evolution.champion_challenger_service import (
    advance_pipeline_stage,
    latest_challenger_evaluation,
)
from app.models.adversarial import AdversarialTestReport
from app.models.agent import Agent
from app.models.champion_challenger import ChallengerEvaluation
from app.models.enums import StrategyFamily, StrategyStage
from app.models.regime_validation import RegimeValidationReport
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA

MIN_OBSERVATION_DAYS = get_settings().champion_min_observation_days   # the CONFIGURED window, not a constant


async def _seed_version(
    db_session, *, stage: StrategyStage = StrategyStage.RESEARCH, created_at: datetime | None = None
) -> StrategyVersion:
    code = f"STRAT-TEST-{uuid.uuid4().hex[:8]}"
    strategy = Strategy(code=code, family=StrategyFamily.MOMENTUM, name=code)
    db_session.add(strategy)
    await db_session.flush()
    dna = StrategyDNA(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna=dna.model_dump(mode="json"), stage=stage)
    db_session.add(version)
    await db_session.flush()
    # promotion_service.evaluate_and_promote requires MIN_STAGE_DAYS of
    # track record since StrategyVersion.created_at — default to
    # comfortably past that so tests exercising champion_comparison don't
    # trip the track-record gate incidentally.
    version.created_at = created_at or (datetime.now(timezone.utc) - timedelta(days=30))
    await db_session.commit()
    return version


async def _seed_evaluation(db_session, version_id, *, pipeline_stage: str, entered_stage_at=None) -> ChallengerEvaluation:
    row = ChallengerEvaluation(
        strategy_version_id=version_id,
        pipeline_stage=pipeline_stage,
        entered_stage_at=entered_stage_at or datetime.now(timezone.utc),
        metrics_snapshot={},
        blocking_reasons=[],
        computed_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.asyncio
async def test_candidate_blocks_without_backtest_metrics(db_session):
    version = await _seed_version(db_session)
    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()
    assert result.pipeline_stage == "candidate"
    assert "no_backtest_stage_metrics_yet" in result.blocking_reasons


@pytest.mark.asyncio
async def test_candidate_advances_to_validation_with_backtest_metrics(db_session):
    version = await _seed_version(db_session)
    db_session.add(
        StageMetrics(
            strategy_version_id=version.id, stage=StrategyStage.BACKTEST,
            net_return_pct=0.15, max_drawdown_pct=0.05, win_rate=0.6, profit_factor=1.8,
            trade_count=120, computed_at=datetime.now(timezone.utc), observed_days=14.0)
    )
    await db_session.commit()

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "validation"
    assert result.blocking_reasons == []


@pytest.mark.asyncio
async def test_validation_blocks_without_adversarial_report(db_session):
    version = await _seed_version(db_session)
    await _seed_evaluation(db_session, version.id, pipeline_stage="validation")

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "validation"
    assert "no_adversarial_test_report_yet" in result.blocking_reasons


@pytest.mark.asyncio
async def test_validation_blocks_when_adversarial_failed(db_session):
    version = await _seed_version(db_session)
    await _seed_evaluation(db_session, version.id, pipeline_stage="validation")
    db_session.add(
        AdversarialTestReport(
            strategy_version_id=version.id, worst_case_max_drawdown_pct=0.5, worst_case_net_return_pct=-0.3,
            passed=False, failure_reasons=["worst_case_max_drawdown 50% > 40%"], scenario_breakdown={},
            robustness_score=0.1, computed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "validation"
    assert any("adversarial_testing_failed" in r for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_validation_advances_to_challenger_when_adversarial_passed(db_session):
    version = await _seed_version(db_session)
    await _seed_evaluation(db_session, version.id, pipeline_stage="validation")
    db_session.add(
        AdversarialTestReport(
            strategy_version_id=version.id, worst_case_max_drawdown_pct=0.1, worst_case_net_return_pct=-0.02,
            passed=True, failure_reasons=[], scenario_breakdown={}, robustness_score=0.9,
            computed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "challenger"


@pytest.mark.asyncio
async def test_challenger_blocks_until_a_live_data_stage(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.OUT_OF_SAMPLE)
    await _seed_evaluation(db_session, version.id, pipeline_stage="challenger")

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "challenger"
    assert any("not yet in a live-data stage" in r for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_challenger_advances_to_observation_once_in_paper_stage(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="challenger")

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "observation"
    assert result.min_observation_days_required == MIN_OBSERVATION_DAYS


@pytest.mark.asyncio
async def test_observation_blocks_until_minimum_days_elapsed(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    entered = datetime.now(timezone.utc) - timedelta(days=MIN_OBSERVATION_DAYS - 3)
    await _seed_evaluation(db_session, version.id, pipeline_stage="observation", entered_stage_at=entered)

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "observation"
    assert any("observation_track_record" in r for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_observation_advances_to_champion_comparison_after_minimum_days(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    entered = datetime.now(timezone.utc) - timedelta(days=MIN_OBSERVATION_DAYS + 1)
    await _seed_evaluation(db_session, version.id, pipeline_stage="observation", entered_stage_at=entered)

    result = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()

    assert result.pipeline_stage == "champion_comparison"


@pytest.mark.asyncio
async def test_champion_comparison_promotes_via_the_single_real_promotion_gate(db_session):
    """This is the one place advance_pipeline_stage calls
    evaluate_and_promote — no second gate is reimplemented here."""
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="champion_comparison")
    await add_promotion_evidence(db_session, version.id)
    db_session.add(
        StageMetrics(
            strategy_version_id=version.id, stage=StrategyStage.PAPER,
            net_return_pct=0.30, max_drawdown_pct=0.05, win_rate=0.7, profit_factor=2.0,
            trade_count=150, oos_score=0.8, walk_forward_consistency=0.8,
            computed_at=datetime.now(timezone.utc), observed_days=14.0)
    )
    db_session.add(
        Agent(
            identifier=f"AG-{uuid.uuid4().hex[:6]}", generation=1, strategy_version_id=version.id,
            starting_balance=100.0, balance=100.0, equity=100.0, peak_equity=100.0,
            day_start_equity=100.0, day_start_date=date.today(), fitness=0.5,
        )
    )
    await db_session.commit()

    result = await advance_pipeline_stage(db_session, version.id, promotion_stage=StrategyStage.PAPER)
    await db_session.commit()

    assert result.pipeline_stage == "promoted"
    await db_session.refresh(version)
    assert version.champion_status.value == "CHAMPION"


@pytest.mark.asyncio
async def test_fragile_regime_classification_tightens_criteria_without_hard_veto(db_session):
    """A FRAGILE classification must never be an automatic block — it
    doubles the required fitness-improvement margin, but a strong enough
    challenger (no prior champion in this fresh lineage, so the margin
    check doesn't even apply) still promotes."""
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="champion_comparison")
    await add_promotion_evidence(db_session, version.id, regime="FRAGILE")
    db_session.add(
        StageMetrics(
            strategy_version_id=version.id, stage=StrategyStage.PAPER,
            net_return_pct=0.30, max_drawdown_pct=0.05, win_rate=0.7, profit_factor=2.0,
            trade_count=150, oos_score=0.8, walk_forward_consistency=0.8,
            computed_at=datetime.now(timezone.utc), observed_days=14.0)
    )
    db_session.add(
        Agent(
            identifier=f"AG-{uuid.uuid4().hex[:6]}", generation=1, strategy_version_id=version.id,
            starting_balance=100.0, balance=100.0, equity=100.0, peak_equity=100.0,
            day_start_equity=100.0, day_start_date=date.today(), fitness=0.5,
        )
    )
    db_session.add(
        RegimeValidationReport(
            strategy_version_id=version.id, per_regime={}, classification="FRAGILE",
            classification_reasoning=["profitable in isolation, losing broadly"], computed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    result = await advance_pipeline_stage(db_session, version.id, promotion_stage=StrategyStage.PAPER)
    await db_session.commit()

    assert result.metrics_snapshot["advisory"]["regime_classification"] == "FRAGILE"
    assert "penalty_applied" in result.metrics_snapshot["advisory"]
    # No prior champion exists in this fresh lineage, so min_fitness_improvement
    # never gets checked regardless of its (doubled) value -> still promotes.
    assert result.pipeline_stage == "promoted"


@pytest.mark.asyncio
async def test_terminal_stages_are_returned_unchanged(db_session):
    version = await _seed_version(db_session)
    promoted = await _seed_evaluation(db_session, version.id, pipeline_stage="promoted")

    result = await advance_pipeline_stage(db_session, version.id)

    assert result.id == promoted.id
    assert result.pipeline_stage == "promoted"


@pytest.mark.asyncio
async def test_list_challengers_includes_versions_with_null_champion_status(db_session):
    """Regression guard: champion_status is nullable and most versions
    never had it set at all. A naive `champion_status != RETIRED` filter
    evaluates to SQL NULL (not true) for those rows under standard
    three-valued logic, silently excluding every never-evaluated
    version — this caught a real bug where the endpoint (and the
    evaluate_generation script's equivalent query) returned nothing for
    the entire population."""
    version = await _seed_version(db_session)  # champion_status left as None
    await _seed_evaluation(db_session, version.id, pipeline_stage="validation")

    results = await list_challengers(version.strategy_id, db=db_session)

    assert any(r.strategy_version_id == version.id for r in results)


@pytest.mark.asyncio
async def test_promotion_never_mutates_strategy_version_dna(db_session):
    """Champion snapshot immutability: StrategyVersion.dna must be bit-for-
    bit identical before and after a promotion — only champion_status may
    change."""
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    original_dna = dict(version.dna)
    await _seed_evaluation(db_session, version.id, pipeline_stage="champion_comparison")
    db_session.add(
        StageMetrics(
            strategy_version_id=version.id, stage=StrategyStage.PAPER,
            net_return_pct=0.30, max_drawdown_pct=0.05, win_rate=0.7, profit_factor=2.0,
            trade_count=150, oos_score=0.8, walk_forward_consistency=0.8,
            computed_at=datetime.now(timezone.utc), observed_days=14.0)
    )
    db_session.add(
        Agent(
            identifier=f"AG-{uuid.uuid4().hex[:6]}", generation=1, strategy_version_id=version.id,
            starting_balance=100.0, balance=100.0, equity=100.0, peak_equity=100.0,
            day_start_equity=100.0, day_start_date=date.today(), fitness=0.5,
        )
    )
    await db_session.commit()

    await advance_pipeline_stage(db_session, version.id, promotion_stage=StrategyStage.PAPER)
    await db_session.commit()

    await db_session.refresh(version)
    assert version.dna == original_dna
