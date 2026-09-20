"""DNA validation, mutation, crossover, versioning (spec section 45)."""
from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from app.evolution.crossover import crossover
from app.evolution.diversity import dna_distance, population_diversity_score
from app.evolution.mutation import mutate
from app.models.enums import MarketRegime, StrategyFamily
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA
from app.strategies.factory import generate_population_dna


def _minimal_dna(**overrides) -> StrategyDNA:
    base = dict(
        strategy_family=StrategyFamily.MOMENTUM,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=50)]),
    )
    base.update(overrides)
    return StrategyDNA.model_validate(base)


def test_valid_dna_constructs():
    dna = _minimal_dna()
    assert dna.strategy_family == StrategyFamily.MOMENTUM
    assert dna.leverage_limit <= dna.risk_profile.max_leverage


def test_leverage_limit_cannot_exceed_risk_profile_max():
    with pytest.raises(ValidationError):
        _minimal_dna(leverage_limit=10.0, risk_profile=RiskProfile(max_leverage=2.0))


def test_duplicate_indicators_rejected():
    with pytest.raises(ValidationError):
        _minimal_dna(
            indicators=[
                {"name": "rsi", "params": {"period": 14}},
                {"name": "rsi", "params": {"period": 14}},
            ]
        )


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        StrategyDNA.model_validate(
            {
                "strategy_family": "momentum",
                "indicators": [{"name": "rsi", "params": {}}],
                "entry_rules": {"conditions": [{"feature": "rsi_14", "operator": "gt", "value": 1}]},
                "exit_rules": {"conditions": [{"feature": "rsi_14", "operator": "lt", "value": 1}]},
                "not_a_real_field": True,
            }
        )


def test_mutation_always_produces_valid_dna():
    rng = random.Random(1)
    dna = _minimal_dna()
    for _ in range(50):
        dna = mutate(dna, rng)
        assert isinstance(dna, StrategyDNA)


def test_crossover_produces_valid_dna_and_respects_leverage_constraint():
    rng = random.Random(2)
    parent_a = _minimal_dna(risk_profile=RiskProfile(max_leverage=2.0), leverage_limit=2.0)
    parent_b = _minimal_dna(risk_profile=RiskProfile(max_leverage=5.0), leverage_limit=5.0)
    for _ in range(20):
        child = crossover(parent_a, parent_b, rng)
        assert child.leverage_limit <= child.risk_profile.max_leverage


def test_generate_population_dna_is_deterministic_and_diverse():
    pop_a = generate_population_dna(500, seed=7)
    pop_b = generate_population_dna(500, seed=7)
    assert [d.model_dump() for d in pop_a] == [d.model_dump() for d in pop_b]

    families = {d.strategy_family for d in pop_a}
    assert len(families) > 1, "initial population must not be a single strategy family"

    diversity = population_diversity_score(pop_a)
    assert diversity > 0.0


def test_dna_distance_zero_for_identical():
    dna = _minimal_dna()
    assert dna_distance(dna, dna) == 0.0


def test_dna_distance_max_for_different_family():
    a = _minimal_dna(strategy_family=StrategyFamily.MOMENTUM)
    b = _minimal_dna(strategy_family=StrategyFamily.BREAKOUT)
    assert dna_distance(a, b) == 1.0
