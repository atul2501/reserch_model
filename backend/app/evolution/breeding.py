"""Generation-breeding orchestrator (spec sections 25, 27, 29).

Wires the previously-uncalled mutation/crossover/diversity primitives into
an actual "spawn the next generation" pipeline: select survivors from the
current generation, breed children, and enforce a population-diversity
floor so the population doesn't homogenize onto one dominant strategy.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tradability import untestable_agent_ids
from app.core import metrics
from app.core.logging import get_logger
from app.evolution.crossover import crossover
from app.evolution.diversity import dna_signature, most_similar_pair, population_diversity_score
from app.evolution.mutation import mutate
from datetime import datetime, timezone
from typing import Callable

from app.models.agent import Agent
from app.models.champion_challenger import ChallengerEvaluation
from app.models.enums import AgentStatus, ChampionStatus, EvolutionEventType, StrategyFamily, StrategyStage
from app.models.evolution import EvolutionEvent
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.factory import generate_population_dna

logger = get_logger(__name__)

# diversity.py's own documented threshold for a homogenized population.
DIVERSITY_FLOOR = 0.15
# Attempts to fix a below-floor population before giving up and accepting
# whatever diversity score results from the final attempt.
MAX_DIVERSITY_REPAIR_ATTEMPTS = 5


class NoValidCandidatesError(RuntimeError):
    """Every candidate (and every replacement founder) failed the validation gate: nothing may be born."""


@dataclass
class BreedingResult:
    strategy_version_ids: list[uuid.UUID]          # elites first (same versions, new capital), then the new children
    diversity_score: float
    injected_fresh_count: int
    rejected_and_remutated_count: int
    validation_rejected_count: int = 0
    events_recorded: int = 0
    elite_version_ids: list[uuid.UUID] = field(default_factory=list)
    dropped_candidates: int = 0        # candidates that never passed the gate: recorded as REJECTED, never inserted
    schema_rejected_count: int = 0


def check_candidate_schema(dna: StrategyDNA) -> list[str]:
    """Gate 1 of the candidate pipeline: the DNA must survive a strict round-trip through its schema and every rule must
    reference a feature that actually exists (static or declared by one of its indicators). Returns the problems."""
    from app.strategies.engine import unknown_features

    problems: list[str] = []
    try:
        StrategyDNA.model_validate(dna.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"schema: {type(exc).__name__}")
        return problems
    unknown = unknown_features(dna)
    if unknown:
        problems.append(f"unknown_features: {sorted(unknown)}")
    problems.extend(f"behaviour: {p}" for p in dna.behavioural_problems())
    return problems


async def select_elite_versions(db: AsyncSession, *, limit: int) -> list[uuid.UUID]:
    """Champion/challenger state that actually drives the population: current CHAMPIONS, then challengers still under
    OBSERVATION / champion-comparison, are carried into the next generation UNCHANGED (the very same StrategyVersion,
    fresh capital). That is what lets a challenger accumulate the observation days a promotion requires - a bred
    child lives one generation, so without carrying it no version could ever be promoted. Rejected/retired versions are
    never carried."""
    if limit <= 0:
        return []
    out: list[uuid.UUID] = []
    champs = (await db.execute(
        select(StrategyVersion.id).where(StrategyVersion.champion_status == ChampionStatus.CHAMPION)
        .order_by(StrategyVersion.promoted_at.desc().nulls_last())
    )).scalars().all()
    out.extend(champs)
    rows = (await db.execute(select(ChallengerEvaluation).order_by(ChallengerEvaluation.computed_at.desc()))).scalars().all()
    latest: dict[uuid.UUID, ChallengerEvaluation] = {}
    for r in rows:
        latest.setdefault(r.strategy_version_id, r)
    candidates = [r for r in latest.values() if r.pipeline_stage in ("observation", "champion_comparison")]
    candidates.sort(key=lambda r: r.entered_stage_at)          # closest to a decision first
    if candidates:
        blocked = set((await db.execute(
            select(StrategyVersion.id).where(
                StrategyVersion.id.in_([r.strategy_version_id for r in candidates]),
                StrategyVersion.champion_status.in_([ChampionStatus.REJECTED, ChampionStatus.RETIRED]),
            )
        )).scalars().all())
        out.extend(r.strategy_version_id for r in candidates if r.strategy_version_id not in blocked)
    return list(dict.fromkeys(out))[:limit]


async def select_survivors(
    db: AsyncSession, *, generation_number: int, survivor_count: int,
    max_family_survivor_fraction: float | None = None, exclude_untestable: bool = True,
) -> list[Agent]:
    """Ranks every agent in `generation_number` by `Agent.fitness` (falling
    back to `equity` for agents that haven't had fitness computed yet) and
    returns the top `survivor_count`.

    `max_family_survivor_fraction`, when given, caps how many survivors may
    come from any single strategy_family (anti-cloning: prevents one
    dominant, highly-correlated family from taking every survivor slot).
    None (the default) preserves the original pure-fitness-ranking
    behavior exactly.

    `exclude_untestable` (default True) drops agents that could not reach the exchange minimum order at their capital
    (see `app.agents.tradability`) from the ranking: they produced no trading evidence, and the fitness function
    scores inaction above a losing trade, so ranking them would select strategies that never traded."""
    # DEAD agents are never parents (their DNA lost the entire account). RETIRED
    # agents of a finished generation are eligible: they survived to the end.
    agents = (
        await db.execute(
            select(Agent).where(Agent.generation == generation_number, Agent.status != AgentStatus.DEAD)
        )
    ).scalars().all()
    # A version the champion/challenger process REJECTED or RETIRED (demoted) is never a parent.
    excluded = set((await db.execute(
        select(StrategyVersion.id).where(
            StrategyVersion.id.in_({a.strategy_version_id for a in agents}),
            StrategyVersion.champion_status.in_([ChampionStatus.REJECTED, ChampionStatus.RETIRED]),
        )
    )).scalars().all()) if agents else set()
    agents = [a for a in agents if a.strategy_version_id not in excluded]
    if exclude_untestable and agents:
        untestable = await untestable_agent_ids(db, agents)
        if untestable:
            logger.info("breeding.untestable_agents_excluded", generation=generation_number, excluded=len(untestable),
                        ranked=len(agents) - len(untestable))
            agents = [a for a in agents if a.id not in untestable]
    ranked = sorted(
        agents,
        key=lambda a: a.fitness if a.fitness is not None else a.equity,
        reverse=True,
    )
    if max_family_survivor_fraction is None:
        return ranked[:survivor_count]

    version_ids = {a.strategy_version_id for a in ranked}
    versions = (await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))).scalars().all()
    family_by_version_id = {v.id: StrategyDNA.model_validate(v.dna).strategy_family.value for v in versions}

    max_per_family = max(1, int(survivor_count * max_family_survivor_fraction))
    family_counts: dict[str, int] = {}
    selected: list[Agent] = []
    overflow: list[Agent] = []
    for agent in ranked:
        family = family_by_version_id[agent.strategy_version_id]
        if family_counts.get(family, 0) < max_per_family:
            selected.append(agent)
            family_counts[family] = family_counts.get(family, 0) + 1
        else:
            overflow.append(agent)
        if len(selected) == survivor_count:
            break
    if len(selected) < survivor_count:
        # Cap left us short (e.g. too few distinct families) — backfill
        # from the highest-ranked overflow rather than under-filling.
        selected.extend(overflow[: survivor_count - len(selected)])
    return selected


async def select_and_breed_next_generation(
    db: AsyncSession,
    *,
    generation_number: int,
    survivor_count: int,
    next_generation_size: int,
    diversity_floor: float = DIVERSITY_FLOOR,
    rng: random.Random | None = None,
    preserve_family_codes: set[str] | None = None,
    mutation_rate_multiplier: float = 1.0,
    max_family_survivor_fraction: float | None = None,
    candidate_validator: Callable[[StrategyDNA], tuple[bool, dict]] | None = None,
    max_validation_attempts: int = 3,
    experiment_id: str | None = None,
    elite_slots: int = 0,
) -> BreedingResult:
    """Selects survivors from `generation_number`, breeds children via crossover+mutation, enforces `diversity_floor`,
    and persists each child that passes the candidate gate as a new Strategy + StrategyVersion. Does NOT call
    create_generation and does NOT commit: the caller owns ONE transaction that also retires the old generation and
    creates the new one, so a failure anywhere leaves no orphan children behind.

    Candidate gate (in order; a candidate failing ANY step is REJECTED and never inserted as accepted):
      1. schema  - `check_candidate_schema`
      2. validator - the caller's in-sample backtest (through the real Risk Engine)
    The heavier evidence (walk-forward, OOS, adversarial, regime, correlation, reality gap) needs data a newborn does
    not have; it gates PROMOTION and eligibility as a parent/elite, never the birth of a paper-trading agent.

    Reproducible: with the same `rng` seed, survivors and inputs the result is identical (codes included)."""
    rng = rng or random.Random(0)

    survivors = await select_survivors(
        db, generation_number=generation_number, survivor_count=survivor_count,
        max_family_survivor_fraction=max_family_survivor_fraction,
    )
    if not survivors:
        raise ValueError(f"no survivors found for generation {generation_number}")

    survivor_version_ids = {a.strategy_version_id for a in survivors}
    versions = (
        await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_(survivor_version_ids)))
    ).scalars().all()
    dna_by_version_id = {v.id: StrategyDNA.model_validate(v.dna) for v in versions}
    survivor_pairs = [(a.strategy_version_id, dna_by_version_id[a.strategy_version_id]) for a in survivors]

    elite_ids = await select_elite_versions(db, limit=min(elite_slots, max(0, next_generation_size - 1)))
    children_wanted = next_generation_size - len(elite_ids)

    inject_distribution = _preserve_family_distribution(preserve_family_codes)

    def _make_candidates() -> tuple[list, int, int, float]:
        cands: list[tuple[StrategyDNA, uuid.UUID | None, uuid.UUID | None]] = []
        for _ in range(children_wanted):
            parent_a_id, parent_a_dna = rng.choice(survivor_pairs)
            parent_b_id, parent_b_dna = rng.choice(survivor_pairs)
            child_dna = mutate(crossover(parent_a_dna, parent_b_dna, rng), rng)
            # Extra mutation passes when diversity pressure calls for it (mutation_rate_multiplier > 1.0).
            extra_passes = mutation_rate_multiplier - 1.0
            while extra_passes > 0:
                if rng.random() < min(1.0, extra_passes):
                    child_dna = mutate(child_dna, rng)
                extra_passes -= 1.0
            cands.append((child_dna, parent_a_id, parent_b_id))

        fresh_injected = remutated = 0
        dnas = [c[0] for c in cands]
        sigs = [dna_signature(d) for d in dnas]
        diversity_now = population_diversity_score(dnas, sigs)
        attempts = 0
        while diversity_now < diversity_floor and attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS and len(dnas) >= 2:
            i, j = most_similar_pair(dnas, sigs)
            if attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS - 1:
                new_dna = mutate(dnas[j], rng)
                dnas[j] = new_dna
                cands[j] = (new_dna, cands[j][1], cands[j][2])
                remutated += 1
            else:
                fresh = generate_population_dna(1, distribution=inject_distribution, seed=rng.randint(0, 2**31 - 1))[0]
                dnas[j] = fresh
                cands[j] = (fresh, None, None)
                fresh_injected += 1
            sigs[j] = dna_signature(dnas[j])
            diversity_now = population_diversity_score(dnas, sigs)
            attempts += 1
        return cands, fresh_injected, remutated, diversity_now

    # CPU-heavy (O(n^2) diversity scans over ~500 DNAs): off the event loop so lease heartbeats keep running.
    candidates, injected_fresh, rejected_remutated, diversity = await asyncio.to_thread(_make_candidates)

    def _gate_candidates(cands: list) -> tuple[list, list, int, int, int]:
        """Runs schema + validator on every candidate. Returns (accepted, rejected, validation_rejected,
        injected_fresh, schema_rejected). Also runs a bounded number of replacement founders for dropped slots."""
        accepted: list = []
        rejected: list = []
        validation_rejected = fresh = schema_rejected = 0

        def gate(dna: StrategyDNA) -> tuple[bool, dict]:
            problems = check_candidate_schema(dna)
            if problems:
                return False, {"schema_problems": problems}
            if candidate_validator is None:
                return True, {}
            return candidate_validator(dna)

        for dna, pa, pb in cands:
            ok, info = gate(dna)
            tries = 0
            while not ok and tries < max_validation_attempts:
                if "schema_problems" in info:
                    schema_rejected += 1
                dna = mutate(dna, rng)
                validation_rejected += 1
                ok, info = gate(dna)
                tries += 1
            if not ok:  # give up on this lineage: try fresh founders in its place
                rejected.append((dna, pa, pb, {**info, "validation_attempts": tries, "passed_validation": False}))
                for _ in range(max_validation_attempts):
                    founder = generate_population_dna(1, distribution=inject_distribution, seed=rng.randint(0, 2**31 - 1))[0]
                    fok, finfo = gate(founder)
                    if fok:
                        accepted.append((founder, None, None, {**finfo, "validation_attempts": 0, "passed_validation": True,
                                                              "replaces_rejected_lineage": True}))
                        fresh += 1
                        break
                continue
            accepted.append((dna, pa, pb, {**info, "validation_attempts": tries, "passed_validation": True}))
        return accepted, rejected, validation_rejected, fresh, schema_rejected

    accepted, rejected, validation_rejected, fresh_gate, schema_rejected = await asyncio.to_thread(_gate_candidates, candidates)
    injected_fresh += fresh_gate
    if not accepted and not elite_ids:
        raise NoValidCandidatesError("every candidate and replacement founder failed the validation gate")

    # Lineage roots of the parents (champion/challenger competes within a lineage).
    parent_ids = {c[1] for c in accepted if c[1]} | {c[2] for c in accepted if c[2]}
    lineage_by_version: dict[uuid.UUID, uuid.UUID | None] = {}
    if parent_ids:
        rows = (
            await db.execute(
                select(StrategyVersion.id, Strategy.lineage_id, Strategy.id)
                .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
                .where(StrategyVersion.id.in_(parent_ids))
            )
        ).all()
        lineage_by_version = {vid: (lin or sid) for vid, lin, sid in rows}

    next_generation_number = generation_number + 1
    now = datetime.now(timezone.utc)
    strategy_version_ids: list[uuid.UUID] = list(elite_ids)
    events = 0

    def _etype(pa_id, pb_id) -> EvolutionEventType:
        if pa_id is None:
            return EvolutionEventType.NOVEL_GENERATION
        if pb_id is not None and pb_id != pa_id:
            return EvolutionEventType.CROSSOVER
        return EvolutionEventType.MUTATION

    for dna, pa_id, pb_id, info in accepted:
        # Seed-derived code (no uuid4): the same seed reproduces the same strategy codes.
        code = f"STRAT-{dna.strategy_family.value.upper()}-GEN{next_generation_number:02d}-{rng.getrandbits(32):08x}"
        strategy = Strategy(
            code=code, family=dna.strategy_family, name=code,
            lineage_id=lineage_by_version.get(pa_id) if pa_id else None,
        )
        db.add(strategy)
        await db.flush()
        if strategy.lineage_id is None:
            strategy.lineage_id = strategy.id  # a founder starts its own lineage

        version = StrategyVersion(
            strategy_id=strategy.id, version=1, generation=next_generation_number,
            parent_strategy_version_id=pa_id, parent_b_strategy_version_id=pb_id,
            dna=dna.model_dump(mode="json"), proposed_by="system",
            # New generations trade on paper from birth; research metrics live in StageMetrics.
            stage=StrategyStage.PAPER, stage_entered_at=now, experiment_id=experiment_id,
        )
        db.add(version)
        await db.flush()
        strategy_version_ids.append(version.id)
        db.add(EvolutionEvent(
            event_type=_etype(pa_id, pb_id), parent_strategy_version_id=pa_id, parent_strategy_version_id_2=pb_id,
            child_strategy_version_id=version.id, generation=next_generation_number,
            validation_result={"experiment_id": experiment_id, **info}, accepted=True,
        ))
        events += 1

    for dna, pa_id, pb_id, info in rejected:
        # A candidate that failed the gate is recorded as REJECTED. It is not a strategy, it has no version row and
        # it can never appear as an accepted child.
        db.add(EvolutionEvent(
            event_type=EvolutionEventType.REJECTION, parent_strategy_version_id=pa_id, parent_strategy_version_id_2=pb_id,
            child_strategy_version_id=None, generation=next_generation_number,
            validation_result={"experiment_id": experiment_id, **info}, accepted=False,
            rejection_reason="candidate_validation_failed",
        ))
        events += 1
        metrics.inc("evolution_candidates_rejected")

    await db.flush()   # NOT a commit: the caller's transaction covers breeding + retirement + the new generation

    return BreedingResult(
        strategy_version_ids=strategy_version_ids,
        diversity_score=diversity,
        injected_fresh_count=injected_fresh,
        rejected_and_remutated_count=rejected_remutated,
        validation_rejected_count=validation_rejected,
        events_recorded=events,
        elite_version_ids=list(elite_ids),
        dropped_candidates=len(rejected),
        schema_rejected_count=schema_rejected,
    )


def _preserve_family_distribution(preserve_family_codes: set[str] | None) -> dict[StrategyFamily, float] | None:
    """Biases fresh-DNA injection toward minority families
    apply_diversity_pressure flagged as under-represented: 80% of weight
    split across the preserved families, 20% across everything else (never
    fully excludes non-preserved families). None (the default) leaves
    generate_population_dna's own default distribution untouched."""
    if not preserve_family_codes:
        return None
    all_families = list(StrategyFamily)
    preserved = [f for f in all_families if f.value in preserve_family_codes]
    others = [f for f in all_families if f.value not in preserve_family_codes]
    if not preserved or not others:
        return None
    distribution: dict[StrategyFamily, float] = {}
    for f in preserved:
        distribution[f] = 0.8 / len(preserved)
    for f in others:
        distribution[f] = 0.2 / len(others)
    return distribution


def _most_correlated_pair(dnas: list[StrategyDNA]) -> tuple[int, int]:
    """The least-diverse pair (O(n^2) over precomputed signatures; kept for callers/tests)."""
    return most_similar_pair(dnas)
