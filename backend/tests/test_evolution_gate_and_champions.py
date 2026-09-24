"""Evolution hard gate, atomicity, reproducibility (spec phase 18) and champion/challenger that actually drives the
population (phase 19)."""
from __future__ import annotations

import random
import zlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.evolution.breeding import (
    NoValidCandidatesError, check_candidate_schema, select_and_breed_next_generation, select_elite_versions, select_survivors,
)
from app.evolution.champion import PromotionCriteria
from app.evolution.champion_challenger_service import advance_pipeline_stage
from app.models.agent import Agent
from app.models.champion_challenger import ChallengerEvaluation
from app.models.enums import ChampionStatus, EvolutionEventType, StrategyStage
from app.models.evolution import EvolutionEvent
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet
from app.strategies.factory import generate_population_dna
from tests.helpers_agents import make_agents
from tests.test_champion_challenger_service import _seed_evaluation, _seed_version


async def _population(db, n=12):
    agents = await make_agents(db, generate_population_dna(n, seed=5), generation=1, stage=StrategyStage.PAPER)
    for i, a in enumerate(agents):
        a.equity = a.balance = 100.0 + i
    await db.commit()
    return agents


def _half_the_time(dna) -> tuple[bool, dict]:
    ok = zlib.crc32(dna.model_dump_json().encode()) % 2 == 0
    return ok, {"probe": "half"}


async def _count(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


# --- the hard candidate gate ---------------------------------------------------------------------------------


async def test_a_failed_candidate_is_never_recorded_as_accepted_or_inserted(db_session):
    await _population(db_session)
    before = await _count(db_session, StrategyVersion)
    res = await select_and_breed_next_generation(
        db_session, generation_number=1, survivor_count=6, next_generation_size=10, rng=random.Random(1),
        candidate_validator=_half_the_time, max_validation_attempts=1,
    )
    events = (await db_session.execute(select(EvolutionEvent).where(EvolutionEvent.generation == 2))).scalars().all()
    accepted = [e for e in events if e.accepted]
    rejected = [e for e in events if e.accepted is False]
    # every accepted event has a child version that PASSED the gate; every rejected one has no child at all
    assert accepted and all(e.child_strategy_version_id is not None and e.validation_result["passed_validation"] for e in accepted)
    assert rejected and all(e.child_strategy_version_id is None and e.event_type == EvolutionEventType.REJECTION
                            and e.rejection_reason == "candidate_validation_failed" for e in rejected)
    assert len(res.strategy_version_ids) == len(accepted) and res.dropped_candidates == len(rejected)
    assert await _count(db_session, StrategyVersion) == before + len(accepted)   # rejected candidates left no strategy behind
    versions = (await db_session.execute(select(StrategyVersion).where(StrategyVersion.generation == 2))).scalars().all()
    assert all(_half_the_time(__import__("app.schemas.strategy_dna", fromlist=["StrategyDNA"]).StrategyDNA.model_validate(v.dna))[0]
               for v in versions)                                                    # only validator-approved DNA exists


async def test_when_every_candidate_fails_nothing_is_born(db_session):
    await _population(db_session)
    versions_before = await _count(db_session, StrategyVersion)
    strategies_before = await _count(db_session, Strategy)
    with pytest.raises(NoValidCandidatesError):
        await select_and_breed_next_generation(
            db_session, generation_number=1, survivor_count=6, next_generation_size=8, rng=random.Random(2),
            candidate_validator=lambda dna: (False, {"why": "always"}), max_validation_attempts=2,
        )
    assert await _count(db_session, StrategyVersion) == versions_before and await _count(db_session, Strategy) == strategies_before


def test_the_schema_gate_rejects_rules_that_reference_unknown_features():
    dna = generate_population_dna(1, seed=3)[0]
    assert check_candidate_schema(dna) == []
    bad = dna.model_copy(update={"entry_rules": RuleSet(conditions=[Condition(feature="totally_made_up_feature", operator="gt", value=1)])})
    problems = check_candidate_schema(bad)
    assert problems and "unknown_features" in problems[0]


async def test_schema_failures_are_rejected_before_the_validator_is_even_consulted(db_session, monkeypatch):
    await _population(db_session)
    from app.evolution import breeding

    calls = {"validator": 0}
    monkeypatch.setattr(breeding, "check_candidate_schema", lambda dna: ["forced schema failure"])

    def validator(dna):
        calls["validator"] += 1
        return True, {}

    with pytest.raises(NoValidCandidatesError):
        await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=6, next_generation_size=4,
                                               rng=random.Random(3), candidate_validator=validator, max_validation_attempts=1)
    assert calls["validator"] == 0


# --- atomicity + reproducibility -----------------------------------------------------------------------------


async def test_breeding_does_not_commit_so_a_later_failure_leaves_no_orphans(db_session):
    await _population(db_session)
    before = (await _count(db_session, StrategyVersion), await _count(db_session, Strategy), await _count(db_session, EvolutionEvent))
    await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=6, next_generation_size=8,
                                           rng=random.Random(4))
    assert await _count(db_session, StrategyVersion) > before[0]          # visible inside the transaction ...
    await db_session.rollback()                                            # ... a failure later in the cycle rolls it ALL back
    assert (await _count(db_session, StrategyVersion), await _count(db_session, Strategy), await _count(db_session, EvolutionEvent)) == before


async def test_same_seed_reproduces_identical_children_including_codes(db_session):
    await _population(db_session)
    outs = []
    for _ in range(2):
        res = await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=6, next_generation_size=8,
                                                     rng=random.Random(99), candidate_validator=_half_the_time, max_validation_attempts=2)
        rows = (await db_session.execute(
            select(Strategy.code, StrategyVersion.dna).join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(StrategyVersion.id.in_(res.strategy_version_ids)).order_by(Strategy.code))).all()
        outs.append([(c, str(d)) for c, d in rows])
        await db_session.rollback()
    assert outs[0] == outs[1] and outs[0]
    other = await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=6, next_generation_size=8,
                                                   rng=random.Random(100))
    codes = [c for (c,) in (await db_session.execute(select(Strategy.code).join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
                                                     .where(StrategyVersion.id.in_(other.strategy_version_ids)))).all()]
    assert set(codes).isdisjoint({c for c, _ in outs[0]})                     # a different seed gives a different population


def test_forgetting_the_seed_is_still_reproducible_not_entropy_driven():
    from app.evolution.crossover import crossover
    from app.evolution.mutation import mutate

    a, b = generate_population_dna(2, seed=8)
    assert mutate(a).model_dump() == mutate(a).model_dump()
    assert crossover(a, b).model_dump() == crossover(a, b).model_dump()


# --- champion / challenger drives the population --------------------------------------------------------------


async def test_champions_and_observed_challengers_are_carried_forward_unchanged(db_session):
    agents = await _population(db_session)
    champ, challenger, rejected, retired, plain = (a.strategy_version_id for a in agents[:5])
    async def setv(vid, **kw):
        v = await db_session.get(StrategyVersion, vid)
        for k, val in kw.items():
            setattr(v, k, val)
    await setv(champ, champion_status=ChampionStatus.CHAMPION, promoted_at=datetime.now(timezone.utc))
    await setv(rejected, champion_status=ChampionStatus.REJECTED)
    await setv(retired, champion_status=ChampionStatus.RETIRED)
    await db_session.commit()
    await _seed_evaluation(db_session, challenger, pipeline_stage="observation",
                           entered_stage_at=datetime.now(timezone.utc) - timedelta(days=3))
    await _seed_evaluation(db_session, rejected, pipeline_stage="observation")     # stale row: status says REJECTED

    elites = await select_elite_versions(db_session, limit=5)
    assert elites[0] == champ and challenger in elites and rejected not in elites and retired not in elites
    assert plain not in elites

    res = await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=8, next_generation_size=10,
                                                 rng=random.Random(5), elite_slots=5)
    assert res.strategy_version_ids[:2] == [champ, challenger] and set(res.elite_version_ids) == {champ, challenger}
    assert len(res.strategy_version_ids) == 10
    # the elite is the SAME version (not a copy): its champion state, promotion time and observation clock survive
    kept = await db_session.get(StrategyVersion, champ)
    assert kept.champion_status == ChampionStatus.CHAMPION and kept.promoted_at is not None
    children = (await db_session.execute(select(StrategyVersion).where(StrategyVersion.generation == 2))).scalars().all()
    assert len(children) == 8
    parents = {v.parent_strategy_version_id for v in children} | {v.parent_b_strategy_version_id for v in children}
    assert not ({rejected, retired} & parents)                                   # demoted/rejected DNA never breeds


async def test_elite_slots_zero_carries_nothing(db_session):
    agents = await _population(db_session)
    v = await db_session.get(StrategyVersion, agents[0].strategy_version_id)
    v.champion_status = ChampionStatus.CHAMPION
    await db_session.commit()
    res = await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=6, next_generation_size=6,
                                                 rng=random.Random(6), elite_slots=0)
    assert res.elite_version_ids == [] and len(res.strategy_version_ids) == 6


async def test_rejected_and_retired_versions_are_not_survivors(db_session):
    agents = await _population(db_session)
    top = max(agents, key=lambda a: a.equity)
    v = await db_session.get(StrategyVersion, top.strategy_version_id)
    v.champion_status = ChampionStatus.REJECTED
    await db_session.commit()
    survivors = await select_survivors(db_session, generation_number=1, survivor_count=3)
    assert top.id not in {a.id for a in survivors}


async def test_promotion_stage_transitions_set_real_champion_status(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="validation")
    from app.models.adversarial import AdversarialTestReport
    db_session.add(AdversarialTestReport(strategy_version_id=version.id, worst_case_max_drawdown_pct=0.1,
                                         worst_case_net_return_pct=0.0, passed=True, robustness_score=0.9,
                                         computed_at=datetime.now(timezone.utc)))
    await db_session.commit()
    row = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()
    assert row.pipeline_stage == "challenger"
    await db_session.refresh(version)
    assert version.champion_status == ChampionStatus.CHALLENGER


async def test_a_failed_champion_comparison_marks_the_version_rejected(db_session):
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="champion_comparison")      # no evidence => the gate rejects
    row = await advance_pipeline_stage(db_session, version.id)
    await db_session.commit()
    assert row.pipeline_stage == "rejected"
    await db_session.refresh(version)
    assert version.champion_status == ChampionStatus.REJECTED


# --- the champion settings are real, not decoration -------------------------------------------------------------


def test_criteria_come_from_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "champion_min_stage_days", 3)
    monkeypatch.setattr(s, "champion_min_observation_days", 4)
    c = PromotionCriteria.from_settings()
    assert c.min_stage_days == 3 and c.min_observation_days == 4


async def test_the_observation_window_is_the_configured_one(db_session, monkeypatch):
    s = get_settings()
    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await _seed_evaluation(db_session, version.id, pipeline_stage="observation",
                           entered_stage_at=datetime.now(timezone.utc) - timedelta(days=5))
    monkeypatch.setattr(s, "champion_min_observation_days", 9)
    blocked = await advance_pipeline_stage(db_session, version.id)
    assert blocked.pipeline_stage == "observation" and any("required 9d" in r for r in blocked.blocking_reasons)
    await db_session.commit()
    monkeypatch.setattr(s, "champion_min_observation_days", 4)
    passed = await advance_pipeline_stage(db_session, version.id)
    assert passed.pipeline_stage == "champion_comparison"


async def test_min_stage_days_is_honoured_including_zero(db_session, monkeypatch):
    from app.evolution.promotion_service import evaluate_and_promote

    s = get_settings()
    version = await _seed_version(db_session, stage=StrategyStage.PAPER, created_at=datetime.now(timezone.utc) - timedelta(days=5))
    from app.models.stage_metrics import StageMetrics
    db_session.add(StageMetrics(strategy_version_id=version.id, stage=StrategyStage.PAPER, net_return_pct=0.1, max_drawdown_pct=0.05,
                                trade_count=150, computed_at=datetime.now(timezone.utc), observed_days=14.0))
    await db_session.commit()
    monkeypatch.setattr(s, "champion_min_stage_days", 30)
    d1 = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert any("stage_track_record 5d < required 30d" in r for r in d1.reasons)
    monkeypatch.setattr(s, "champion_min_stage_days", 0)               # 0 must mean "no track-record gate", not "fall back to 14"
    d2 = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert not any("stage_track_record" in r for r in d2.reasons)


async def test_promotion_records_promoted_at_and_the_elite_survives_generations(db_session):
    from app.evolution.promotion_service import evaluate_and_promote
    from app.models.stage_metrics import StageMetrics
    from tests.helpers_agents import add_promotion_evidence

    version = await _seed_version(db_session, stage=StrategyStage.PAPER)
    await add_promotion_evidence(db_session, version.id)
    db_session.add(StageMetrics(strategy_version_id=version.id, stage=StrategyStage.PAPER, net_return_pct=0.3, max_drawdown_pct=0.05,
                                win_rate=0.7, profit_factor=2.0, trade_count=150, oos_score=0.8, walk_forward_consistency=0.8,
                                computed_at=datetime.now(timezone.utc), observed_days=14.0))
    await db_session.commit()
    d = await evaluate_and_promote(db_session, version.id, stage=StrategyStage.PAPER)
    assert d.promote, d.reasons
    await db_session.refresh(version)
    assert version.champion_status == ChampionStatus.CHAMPION and version.promoted_at is not None
    assert version.id in await select_elite_versions(db_session, limit=3)      # promotion changes real breeding state
