"""Generation-breeding orchestrator (spec sections 25, 27, 29).

Wires the previously-uncalled mutation/crossover/diversity primitives into
an actual "spawn the next generation" pipeline: select survivors from the
current generation, breed children, and enforce a population-diversity
floor so the population doesn't homogenize onto one dominant strategy.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.crossover import crossover
from app.evolution.diversity import dna_distance, population_diversity_score
from app.evolution.mutation import mutate
from datetime import datetime, timezone
from typing import Callable

from app.models.agent import Agent
from app.models.enums import AgentStatus, EvolutionEventType, StrategyFamily, StrategyStage
from app.models.evolution import EvolutionEvent
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.factory import generate_population_dna

# diversity.py's own documented threshold for a homogenized population.
DIVERSITY_FLOOR = 0.15
# Attempts to fix a below-floor population before giving up and accepting
# whatever diversity score results from the final attempt.
MAX_DIVERSITY_REPAIR_ATTEMPTS = 5


@dataclass
class BreedingResult:
    strategy_version_ids: list[uuid.UUID]
    diversity_score: float
    injected_fresh_count: int
    rejected_and_remutated_count: int
    validation_rejected_count: int = 0
    events_recorded: int = 0


async def select_survivors(
    db: AsyncSession, *, generation_number: int, survivor_count: int,
    max_family_survivor_fraction: float | None = None,
) -> list[Agent]:
    """Ranks every agent in `generation_number` by `Agent.fitness` (falling
    back to `equity` for agents that haven't had fitness computed yet) and
    returns the top `survivor_count`.

    `max_family_survivor_fraction`, when given, caps how many survivors may
    come from any single strategy_family (anti-cloning: prevents one
    dominant, highly-correlated family from taking every survivor slot).
    None (the default) preserves the original pure-fitness-ranking
    behavior exactly."""
    # DEAD agents are never parents (their DNA lost the entire account). RETIRED
    # agents of a finished generation are eligible: they survived to the end.
    agents = (
        await db.execute(
            select(Agent).where(Agent.generation == generation_number, Agent.status != AgentStatus.DEAD)
        )
    ).scalars().all()
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
) -> BreedingResult:
    """Selects survivors from `generation_number`, breeds
    `next_generation_size` children via crossover+mutation, and enforces
    `diversity_floor` on the candidate DNA set before persisting each child
    as a new Strategy + StrategyVersion row. Does NOT call create_generation
    — the caller does that with the returned strategy_version_ids.

    `preserve_family_codes`/`mutation_rate_multiplier`/
    `max_family_survivor_fraction` are the diversity-pressure signals
    StrategyCorrelationEngine's `apply_diversity_pressure` produces
    (app/evolution/correlation_service.py) — all optional, all no-ops at
    their defaults, so calling this without them is unchanged behavior."""
    rng = rng or random.Random()

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

    # candidates[i] = (dna, parent_a_version_id | None, parent_b_version_id | None)
    candidates: list[tuple[StrategyDNA, uuid.UUID | None, uuid.UUID | None]] = []
    for _ in range(next_generation_size):
        parent_a_id, parent_a_dna = rng.choice(survivor_pairs)
        parent_b_id, parent_b_dna = rng.choice(survivor_pairs)
        child_dna = mutate(crossover(parent_a_dna, parent_b_dna, rng), rng)
        # Extra mutation passes, probabilistically, when diversity pressure
        # calls for it (mutation_rate_multiplier > 1.0) — never touches
        # mutation.py's own MUTATION_RATE constant, just layers additional
        # independent passes on top.
        extra_passes = mutation_rate_multiplier - 1.0
        while extra_passes > 0:
            if rng.random() < min(1.0, extra_passes):
                child_dna = mutate(child_dna, rng)
            extra_passes -= 1.0
        candidates.append((child_dna, parent_a_id, parent_b_id))

    injected_fresh = 0
    rejected_remutated = 0
    candidate_dnas = [c[0] for c in candidates]
    diversity = population_diversity_score(candidate_dnas)

    inject_distribution = _preserve_family_distribution(preserve_family_codes)

    attempts = 0
    while diversity < diversity_floor and attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS and len(candidate_dnas) >= 2:
        i, j = _most_correlated_pair(candidate_dnas)
        if attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS - 1:
            new_dna = mutate(candidate_dnas[j], rng)
            candidate_dnas[j] = new_dna
            candidates[j] = (new_dna, candidates[j][1], candidates[j][2])
            rejected_remutated += 1
        else:
            fresh = generate_population_dna(
                1, distribution=inject_distribution, seed=rng.randint(0, 2**31 - 1)
            )[0]
            candidate_dnas[j] = fresh
            candidates[j] = (fresh, None, None)
            injected_fresh += 1
        diversity = population_diversity_score(candidate_dnas)
        attempts += 1

    # ---- candidate validation: a child must pass the (in-sample) validator BEFORE it is born ----
    validation_rejected = 0
    validation_info: list[dict] = [{} for _ in candidates]
    if candidate_validator is not None:
        for idx, (dna, pa, pb) in enumerate(candidates):
            ok, info = candidate_validator(dna)
            tries = 0
            while not ok and tries < max_validation_attempts:
                dna = mutate(dna, rng)
                validation_rejected += 1
                ok, info = candidate_validator(dna)
                tries += 1
            if not ok:  # give up on this lineage: inject a fresh, validated-if-possible founder instead
                for _ in range(max_validation_attempts):
                    dna = generate_population_dna(1, distribution=inject_distribution, seed=rng.randint(0, 2**31 - 1))[0]
                    ok, info = candidate_validator(dna)
                    if ok:
                        break
                pa = pb = None
                injected_fresh += 1
            candidates[idx] = (dna, pa, pb)
            validation_info[idx] = {**info, "validation_attempts": tries, "passed_validation": ok}

    # Lineage roots of the parents (champion/challenger competes within a lineage).
    parent_ids = {c[1] for c in candidates if c[1]} | {c[2] for c in candidates if c[2]}
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
    strategy_version_ids: list[uuid.UUID] = []
    events = 0
    for (dna, pa_id, pb_id), info in zip(candidates, validation_info):
        code = f"STRAT-{dna.strategy_family.value.upper()}-GEN{next_generation_number:02d}-{uuid.uuid4().hex[:8]}"
        strategy = Strategy(
            code=code, family=dna.strategy_family, name=code,
            lineage_id=lineage_by_version.get(pa_id) if pa_id else None,
        )
        db.add(strategy)
        await db.flush()
        if strategy.lineage_id is None:
            strategy.lineage_id = strategy.id  # a founder starts its own lineage

        version = StrategyVersion(
            strategy_id=strategy.id,
            version=1,
            generation=next_generation_number,
            parent_strategy_version_id=pa_id,
            parent_b_strategy_version_id=pb_id,
            dna=dna.model_dump(mode="json"),
            proposed_by="system",
            # New generations trade on paper from birth; research metrics live in StageMetrics.
            stage=StrategyStage.PAPER,
            stage_entered_at=now,
            experiment_id=experiment_id,
        )
        db.add(version)
        await db.flush()
        strategy_version_ids.append(version.id)

        if pa_id is None:
            etype = EvolutionEventType.NOVEL_GENERATION
        elif pb_id is not None and pb_id != pa_id:
            etype = EvolutionEventType.CROSSOVER
        else:
            etype = EvolutionEventType.MUTATION
        db.add(EvolutionEvent(
            event_type=etype, parent_strategy_version_id=pa_id, parent_strategy_version_id_2=pb_id,
            child_strategy_version_id=version.id, generation=next_generation_number,
            validation_result={"experiment_id": experiment_id, **info}, accepted=True,
        ))
        events += 1

    await db.commit()

    return BreedingResult(
        strategy_version_ids=strategy_version_ids,
        diversity_score=diversity,
        injected_fresh_count=injected_fresh,
        rejected_and_remutated_count=rejected_remutated,
        validation_rejected_count=validation_rejected,
        events_recorded=events,
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
    """O(n^2) pairwise scan for the least-diverse pair. Fine at the ~500-agent
    scale this pipeline runs at."""
    best_i, best_j, best_distance = 0, 1, float("inf")
    for i in range(len(dnas)):
        for j in range(i + 1, len(dnas)):
            d = dna_distance(dnas[i], dnas[j])
            if d < best_distance:
                best_i, best_j, best_distance = i, j, d
    return best_i, best_j
