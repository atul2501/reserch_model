"""Scheduled evolution pipeline (spec phases 22-24, 29-32): gates, the full
Population -> ... -> New generation flow, OOS protection, lineage, snapshots."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.enums import AgentStatus, EvolutionEventType, StrategyStage
from app.models.evolution import EvolutionEvent
from app.models.market import FundingRate, MarketCandle
from app.models.research import Experiment, OosEvaluation, ResearchEpoch
from app.models.stage_metrics import StageMetrics
from app.models.strategy import AgentSnapshot, Generation, Strategy, StrategyVersion
from app.models.adversarial import AdversarialTestReport
from app.models.regime_validation import RegimeValidationReport
from app.evolution.rng import derive_seed
from app.research import dataset as ds
from app.research.pipeline import evaluate_gates, run_research_cycle
from app.strategies.factory import generate_population_dna
from tests.helpers_agents import make_agents
from tests.test_backtest_parity import candles as make_candles

N_AGENTS = 10


@pytest.fixture
def cfg(monkeypatch):
    s = get_settings()
    for k, v in dict(agent_count=N_AGENTS, evolution_enabled=True, evolution_interval_hours=24, research_min_candles=800,
                     research_window_candles=1600, research_min_generation_age_hours=0.0, research_min_closed_trades=0,
                     research_adversarial_top_k=2, research_adversarial_bars=450, adversarial_n_dna_variants=1,
                     research_candidate_min_trades=1, research_candidate_max_drawdown=0.95, research_max_child_attempts=1,
                     paper_latency_ms=0, paper_latency_jitter_ms=0).items():
        monkeypatch.setattr(s, k, v)
    return s


async def _seed_candles(db, n=1600, seed=31):
    c = make_candles(n, seed=seed, drift=0.005, vol=0.5)
    db.add_all([MarketCandle(symbol="SOL", timeframe="1m", open_time=int(r.open_time), close_time=int(r.open_time) + 59_999,
                             open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close), volume=float(r.volume),
                             is_final=True) for r in c.itertuples()])
    t0 = int(c["open_time"].iloc[0])
    db.add_all([FundingRate(symbol="SOL", time_ms=t0 + h * 3_600_000, rate=0.00001) for h in range(1, 26)])
    await db.commit()
    return c


async def _seed_population(db, n=N_AGENTS, dead=2):
    dnas = generate_population_dna(n, seed=5)
    agents = await make_agents(db, dnas, generation=1, stage=StrategyStage.PAPER)
    for i, a in enumerate(agents):
        a.equity = a.balance = 100.0 + (i - 4) * 3.0          # a fitness gradient: later agents richer
        a.peak_equity = max(100.0, a.equity)
    dead_ids = set()
    for a in agents[:dead]:
        a.status, a.death_reason, a.equity, a.balance = AgentStatus.DEAD, "equity_depleted", 0.0, 0.0
        dead_ids.add(a.strategy_version_id)
    await db.commit()
    return agents, dead_ids


# ---------------------------------------------------------------- gates ---------------- #
async def test_gate_evolution_disabled(db_session, cfg, monkeypatch):
    monkeypatch.setattr(cfg, "evolution_enabled", False)
    ok, reason, _ = await evaluate_gates(db_session)
    assert not ok and reason == "evolution_disabled"


async def test_gate_no_generation(db_session, cfg):
    ok, reason, _ = await evaluate_gates(db_session)
    assert not ok and reason == "no_generation"


async def test_gate_generation_too_young(db_session, cfg, monkeypatch):
    await _seed_population(db_session)
    monkeypatch.setattr(cfg, "research_min_generation_age_hours", 12.0)
    ok, reason, _ = await evaluate_gates(db_session)
    assert not ok and reason == "generation_too_young"
    ok, reason, _ = await evaluate_gates(db_session, now=datetime.now(timezone.utc) + timedelta(hours=13))
    assert ok


async def test_gate_needs_real_paper_history(db_session, cfg, monkeypatch):
    await _seed_population(db_session)
    monkeypatch.setattr(cfg, "research_min_closed_trades", 30)
    ok, reason, _ = await evaluate_gates(db_session)
    assert not ok and reason.startswith("insufficient_paper_history")


async def test_skips_are_recorded_and_no_evolution_happens_without_enough_market_data(db_session, cfg):
    await _seed_population(db_session)
    report = await run_research_cycle(db_session)
    assert report.status == "SKIPPED" and report.reason.startswith("insufficient_market_data")
    exp = (await db_session.execute(select(Experiment).where(Experiment.kind == "evolution"))).scalar_one()
    assert exp.status == "SKIPPED" and "insufficient_market_data" in exp.result["reason"]
    assert (await db_session.execute(select(func.count()).select_from(Generation))).scalar_one() == 1     # nothing evolved


# ------------------------------------------------------------- full pipeline ------------- #
async def test_full_pipeline_produces_a_validated_next_generation_and_protects_oos(db_session, cfg):
    c = await _seed_candles(db_session)
    agents, dead_versions = await _seed_population(db_session)
    old_versions = {a.strategy_version_id for a in agents}

    report = await run_research_cycle(db_session)
    assert report.status == "COMPLETED", report.reason
    assert report.generation_from == 1 and report.generation_to == 2

    # ---- experiment registry ------------------------------------------------ #
    exp = (await db_session.execute(select(Experiment).where(Experiment.experiment_id == report.experiment_id))).scalar_one()
    epoch = (await db_session.execute(select(ResearchEpoch).where(ResearchEpoch.epoch_id == report.epoch_id))).scalar_one()
    assert exp.status == "COMPLETED" and exp.dataset_fingerprint == epoch.dataset_fingerprint and exp.random_seed == derive_seed(cfg.research_seed, epoch.epoch_id, 1)
    assert exp.code_version and exp.schema_version and exp.oos_period["start_ms"] == epoch.validation_end_ms

    # ---- new generation: fresh $100, old one frozen, dead never revived ------- #
    new_agents = (await db_session.execute(select(Agent).where(Agent.generation == 2))).scalars().all()
    assert len(new_agents) == N_AGENTS
    assert all(a.starting_balance == a.balance == a.equity == 100.0 and a.status == AgentStatus.ACTIVE for a in new_agents)
    old_agents = (await db_session.execute(select(Agent).where(Agent.generation == 1))).scalars().all()
    statuses = {a.status for a in old_agents}
    assert statuses == {AgentStatus.DEAD, AgentStatus.RETIRED}
    assert sum(a.status == AgentStatus.DEAD for a in old_agents) == 2
    assert all(a.final_equity is not None for a in old_agents if a.status == AgentStatus.RETIRED)

    # ---- selection: dead agents' DNA never became a parent ------------------ #
    new_versions = (await db_session.execute(select(StrategyVersion).where(StrategyVersion.generation == 2))).scalars().all()
    parents = {v.parent_strategy_version_id for v in new_versions} | {v.parent_b_strategy_version_id for v in new_versions}
    assert not (parents & dead_versions)
    assert all(v.stage == StrategyStage.PAPER and v.experiment_id == exp.experiment_id and v.stage_entered_at for v in new_versions)

    # ---- evolution events: crossover/mutation/novel with both parents recorded --- #
    events = (await db_session.execute(select(EvolutionEvent).where(EvolutionEvent.generation == 2))).scalars().all()
    elites = report.counts.get("elites_carried", 0)   # challengers under observation are carried forward unchanged
    assert elites >= 1 and len(events) == N_AGENTS - elites and len(new_versions) == N_AGENTS - elites
    assert {e.event_type for e in events} <= {EvolutionEventType.CROSSOVER, EvolutionEventType.MUTATION, EvolutionEventType.NOVEL_GENERATION}
    crossovers = [e for e in events if e.event_type == EvolutionEventType.CROSSOVER]
    assert crossovers and all(e.parent_strategy_version_id and e.parent_strategy_version_id_2 for e in crossovers)
    assert all("passed_validation" in e.validation_result for e in events)

    # ---- lineage: children stay in their ancestors' family tree ---------------- #
    lineages = {s.lineage_id for s in (await db_session.execute(select(Strategy))).scalars().all() if s.lineage_id}
    assert lineages

    # ---- evaluation evidence written for the evaluated generation ---------------- #
    bt = (await db_session.execute(select(StageMetrics).where(StageMetrics.stage == StrategyStage.BACKTEST))).scalars().all()
    wfo = (await db_session.execute(select(StageMetrics).where(StageMetrics.stage == StrategyStage.WALK_FORWARD))).scalars().all()
    assert {r.strategy_version_id for r in bt} >= old_versions - dead_versions and wfo
    assert (await db_session.execute(select(func.count()).select_from(RegimeValidationReport))).scalar_one() >= 1
    adv = (await db_session.execute(select(AdversarialTestReport))).scalars().all()
    assert 1 <= len(adv) <= cfg.research_adversarial_top_k

    # ---- OOS protection ---------------------------------------------------------- #
    # backtest metrics were computed strictly on train(+validation) -> none of the OOS candles were used;
    # the OOS slice was consumed only for nominated survivors, once each.
    oos = (await db_session.execute(select(OosEvaluation))).scalars().all()
    assert 1 <= len(oos) <= cfg.research_adversarial_top_k
    assert len({(o.strategy_version_id, o.dataset_fingerprint) for o in oos}) == len(oos)
    assert all(o.dataset_fingerprint == epoch.dataset_fingerprint for o in oos)
    oos_stage = (await db_session.execute(select(StageMetrics).where(StageMetrics.stage == StrategyStage.OUT_OF_SAMPLE))).scalars().all()
    assert len(oos_stage) == len(oos)

    # ---- snapshots of the finished generation: immutable & provenance-complete ---- #
    snaps = (await db_session.execute(select(AgentSnapshot))).scalars().all()
    assert snaps and all(s.experiment_id == exp.experiment_id and s.dataset_fingerprint == epoch.dataset_fingerprint for s in snaps)

    # ---- the schedule: running again immediately does nothing ----------------------- #
    again = await run_research_cycle(db_session)
    assert again.status == "SKIPPED" and again.reason == "interval_not_elapsed"


async def test_pipeline_uses_a_seeded_rng_so_children_are_reproducible(db_session, cfg):
    """Same seed + same survivors -> identical child DNA (breeding is no longer unseeded)."""
    from app.evolution.breeding import select_and_breed_next_generation
    await _seed_population(db_session, dead=0)
    outs = []
    for _ in range(2):
        res = await select_and_breed_next_generation(db_session, generation_number=1, survivor_count=4, next_generation_size=6,
                                                     rng=random.Random(cfg.research_seed))
        versions = (await db_session.execute(select(StrategyVersion).where(StrategyVersion.id.in_(res.strategy_version_ids)))).scalars().all()
        outs.append(sorted(str(v.dna) for v in versions))
        strategy_ids = {v.strategy_id for v in versions}
        for v in versions:                      # clean between the two runs
            await db_session.execute(EvolutionEvent.__table__.delete().where(EvolutionEvent.child_strategy_version_id == v.id))
            await db_session.delete(v)
        await db_session.flush()
        for sid in strategy_ids:                # seed-derived strategy codes are reproducible too, so remove the rows
            await db_session.delete(await db_session.get(Strategy, sid))
        await db_session.commit()
    assert outs[0] == outs[1]


async def test_extinct_population_restarts_from_fresh_founders_never_reviving_the_dead(db_session, cfg):
    await _seed_candles(db_session)
    agents, dead_versions = await _seed_population(db_session, dead=N_AGENTS)
    report = await run_research_cycle(db_session)
    assert report.status == "COMPLETED" and report.counts.get("extinction_restart") is True
    new_agents = (await db_session.execute(select(Agent).where(Agent.generation == 2))).scalars().all()
    assert len(new_agents) == N_AGENTS and all(a.equity == 100.0 for a in new_agents)
    old = (await db_session.execute(select(Agent).where(Agent.generation == 1))).scalars().all()
    assert all(a.status == AgentStatus.DEAD for a in old)      # still dead


async def test_a_failed_cycle_is_recorded_and_leaves_the_population_intact(db_session, cfg, monkeypatch):
    await _seed_candles(db_session)
    await _seed_population(db_session)
    from app.research import pipeline
    async def boom(*a, **k):
        raise RuntimeError("selection blew up")
    monkeypatch.setattr(pipeline, "select_and_breed_next_generation", boom)
    report = await run_research_cycle(db_session)
    assert report.status == "FAILED" and "selection blew up" in report.reason
    exp = (await db_session.execute(select(Experiment).where(Experiment.experiment_id == report.experiment_id))).scalar_one()
    assert exp.status == "FAILED"
    assert (await db_session.execute(select(func.count()).select_from(Generation))).scalar_one() == 1
    assert (await db_session.execute(select(func.count()).select_from(Agent).where(Agent.status == AgentStatus.ACTIVE))).scalar_one() == N_AGENTS - 2
