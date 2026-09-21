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
from app.models.agent import Agent
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


async def select_survivors(
    db: AsyncSession, *, generation_number: int, survivor_count: int
) -> list[Agent]:
    """Ranks every agent in `generation_number` by `Agent.fitness` (falling
    back to `equity` for agents that haven't had fitness computed yet) and
    returns the top `survivor_count`."""
    agents = (
        await db.execute(select(Agent).where(Agent.generation == generation_number))
    ).scalars().all()
    ranked = sorted(
        agents,
        key=lambda a: a.fitness if a.fitness is not None else a.equity,
        reverse=True,
    )
    return ranked[:survivor_count]


async def select_and_breed_next_generation(
    db: AsyncSession,
    *,
    generation_number: int,
    survivor_count: int,
    next_generation_size: int,
    diversity_floor: float = DIVERSITY_FLOOR,
    rng: random.Random | None = None,
) -> BreedingResult:
    """Selects survivors from `generation_number`, breeds
    `next_generation_size` children via crossover+mutation, and enforces
    `diversity_floor` on the candidate DNA set before persisting each child
    as a new Strategy + StrategyVersion row. Does NOT call create_generation
    — the caller does that with the returned strategy_version_ids."""
    rng = rng or random.Random()

    survivors = await select_survivors(
        db, generation_number=generation_number, survivor_count=survivor_count
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
        candidates.append((child_dna, parent_a_id, parent_b_id))

    injected_fresh = 0
    rejected_remutated = 0
    candidate_dnas = [c[0] for c in candidates]
    diversity = population_diversity_score(candidate_dnas)

    attempts = 0
    while diversity < diversity_floor and attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS and len(candidate_dnas) >= 2:
        i, j = _most_correlated_pair(candidate_dnas)
        if attempts < MAX_DIVERSITY_REPAIR_ATTEMPTS - 1:
            new_dna = mutate(candidate_dnas[j], rng)
            candidate_dnas[j] = new_dna
            candidates[j] = (new_dna, candidates[j][1], candidates[j][2])
            rejected_remutated += 1
        else:
            fresh = generate_population_dna(1, seed=rng.randint(0, 2**31 - 1))[0]
            candidate_dnas[j] = fresh
            candidates[j] = (fresh, None, None)
            injected_fresh += 1
        diversity = population_diversity_score(candidate_dnas)
        attempts += 1

    next_generation_number = generation_number + 1
    strategy_version_ids: list[uuid.UUID] = []
    for dna, parent_a_id, _parent_b_id in candidates:
        code = f"STRAT-{dna.strategy_family.value.upper()}-GEN{next_generation_number:02d}-{uuid.uuid4().hex[:8]}"
        strategy = Strategy(code=code, family=dna.strategy_family, name=code)
        db.add(strategy)
        await db.flush()

        version = StrategyVersion(
            strategy_id=strategy.id,
            version=1,
            generation=next_generation_number,
            parent_strategy_version_id=parent_a_id,
            dna=dna.model_dump(mode="json"),
            proposed_by="system",
        )
        db.add(version)
        await db.flush()
        strategy_version_ids.append(version.id)

    await db.commit()

    return BreedingResult(
        strategy_version_ids=strategy_version_ids,
        diversity_score=diversity,
        injected_fresh_count=injected_fresh,
        rejected_and_remutated_count=rejected_remutated,
    )


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
