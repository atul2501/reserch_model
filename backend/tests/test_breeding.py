"""Generation-breeding orchestrator: survivor selection and the
population-diversity floor (spec sections 25, 27, 29)."""
from __future__ import annotations

import random
import uuid

import pytest
from sqlalchemy import select

from app.agents.lifecycle import create_generation
from app.evolution.breeding import select_and_breed_next_generation, select_survivors
from app.models.agent import Agent
from app.models.enums import StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA


def _dna(family: StrategyFamily = StrategyFamily.MOMENTUM) -> StrategyDNA:
    return StrategyDNA(
        strategy_family=family,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=40)]),
    )


async def _seed_generation(db_session, *, generation_number: int, count: int, family: StrategyFamily = StrategyFamily.MOMENTUM):
    strategy_version_ids = []
    for i in range(count):
        code = f"STRAT-TEST-{generation_number}-{i}-{uuid.uuid4().hex[:6]}"
        strategy = Strategy(code=code, family=family, name=code)
        db_session.add(strategy)
        await db_session.flush()
        version = StrategyVersion(
            strategy_id=strategy.id, version=1, generation=generation_number, dna=_dna(family).model_dump(mode="json")
        )
        db_session.add(version)
        await db_session.flush()
        strategy_version_ids.append(version.id)
    await db_session.commit()
    await create_generation(
        db_session, generation_number=generation_number, strategy_version_ids=strategy_version_ids, starting_balance=100.0
    )


@pytest.mark.asyncio
async def test_select_survivors_ranks_by_fitness_then_equity(db_session):
    await _seed_generation(db_session, generation_number=1, count=3)
    agents = (await db_session.execute(select(Agent).where(Agent.generation == 1))).scalars().all()
    agents[0].fitness = 0.9
    agents[1].fitness = None
    agents[1].equity = 500.0  # no fitness yet, but highest equity of the untested ones
    agents[2].fitness = 0.1
    await db_session.commit()

    survivors = await select_survivors(db_session, generation_number=1, survivor_count=2)

    assert [a.id for a in survivors] == [agents[1].id, agents[0].id]


@pytest.mark.asyncio
async def test_breeding_enforces_diversity_floor(db_session):
    # All survivors share one family/near-identical DNA, so naive breeding
    # would collapse diversity well below the floor without repair.
    await _seed_generation(db_session, generation_number=1, count=5, family=StrategyFamily.MOMENTUM)

    result = await select_and_breed_next_generation(
        db_session,
        generation_number=1,
        survivor_count=5,
        next_generation_size=10,
        rng=random.Random(42),
    )

    assert len(result.strategy_version_ids) == 10
    assert result.diversity_score >= 0.15 or (
        result.rejected_and_remutated_count + result.injected_fresh_count > 0
    )

    versions = (
        await db_session.execute(select(StrategyVersion).where(StrategyVersion.id.in_(result.strategy_version_ids)))
    ).scalars().all()
    assert len(versions) == 10
    assert all(v.generation == 2 for v in versions)


@pytest.mark.asyncio
async def test_select_and_breed_raises_with_no_survivors(db_session):
    with pytest.raises(ValueError):
        await select_and_breed_next_generation(
            db_session, generation_number=999, survivor_count=5, next_generation_size=10
        )


@pytest.mark.asyncio
async def test_max_family_survivor_fraction_caps_a_dominant_family(db_session):
    """Without the cap, 5 high-fitness MOMENTUM agents would take every
    survivor slot and the 2 lower-fitness BREAKOUT agents would be fully
    excluded. With max_family_survivor_fraction=0.4 (cap=2 for
    survivor_count=5), BREAKOUT gets guaranteed representation instead —
    the anti-cloning mechanism StrategyCorrelationEngine relies on."""
    strategy_version_ids = []
    for family, count in ((StrategyFamily.MOMENTUM, 5), (StrategyFamily.BREAKOUT, 2)):
        for i in range(count):
            code = f"STRAT-TEST-{family.value}-{i}-{uuid.uuid4().hex[:6]}"
            strategy = Strategy(code=code, family=family, name=code)
            db_session.add(strategy)
            await db_session.flush()
            version = StrategyVersion(
                strategy_id=strategy.id, version=1, generation=1, dna=_dna(family).model_dump(mode="json")
            )
            db_session.add(version)
            await db_session.flush()
            strategy_version_ids.append(version.id)
    await db_session.commit()
    await create_generation(
        db_session, generation_number=1, strategy_version_ids=strategy_version_ids, starting_balance=100.0
    )

    agents = (await db_session.execute(select(Agent).where(Agent.generation == 1))).scalars().all()
    # Explicit fitness so ranking is deterministic: all 5 momentum agents
    # rank above both breakout agents.
    momentum_fitness = [0.9, 0.85, 0.8, 0.75, 0.7]
    breakout_fitness = [0.5, 0.45]
    version_ids = {a.strategy_version_id for a in agents}
    versions = (await db_session.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))).scalars().all()
    strategies = (await db_session.execute(select(Strategy))).scalars().all()
    family_by_strategy_id = {s.id: s.family for s in strategies}
    family_by_version_id = {v.id: family_by_strategy_id[v.strategy_id] for v in versions}

    m_i, b_i = 0, 0
    for a in agents:
        family = family_by_version_id[a.strategy_version_id]
        if family == StrategyFamily.MOMENTUM:
            a.fitness = momentum_fitness[m_i]
            m_i += 1
        else:
            a.fitness = breakout_fitness[b_i]
            b_i += 1
    await db_session.commit()

    uncapped = await select_survivors(db_session, generation_number=1, survivor_count=5)
    uncapped_families = [family_by_version_id[a.strategy_version_id] for a in uncapped]
    assert uncapped_families.count(StrategyFamily.BREAKOUT) == 0  # confirms the cap is doing something

    capped = await select_survivors(
        db_session, generation_number=1, survivor_count=5, max_family_survivor_fraction=0.4
    )
    capped_families = [family_by_version_id[a.strategy_version_id] for a in capped]
    assert capped_families.count(StrategyFamily.BREAKOUT) == 2
    assert len(capped) == 5


def test_preserve_family_distribution_biases_toward_preserved_families():
    from app.evolution.breeding import _preserve_family_distribution

    dist = _preserve_family_distribution({"breakout"})
    assert dist is not None
    assert dist[StrategyFamily.BREAKOUT] > dist[StrategyFamily.MOMENTUM]
    assert sum(dist.values()) == pytest.approx(1.0)


def test_preserve_family_distribution_is_none_without_families():
    from app.evolution.breeding import _preserve_family_distribution

    assert _preserve_family_distribution(None) is None
    assert _preserve_family_distribution(set()) is None


@pytest.mark.asyncio
async def test_breeding_accepts_diversity_pressure_signals_without_error(db_session):
    await _seed_generation(db_session, generation_number=1, count=5, family=StrategyFamily.MOMENTUM)

    result = await select_and_breed_next_generation(
        db_session,
        generation_number=1,
        survivor_count=5,
        next_generation_size=6,
        rng=random.Random(7),
        preserve_family_codes={"breakout"},
        mutation_rate_multiplier=1.8,
        max_family_survivor_fraction=0.5,
    )

    assert len(result.strategy_version_ids) == 6
