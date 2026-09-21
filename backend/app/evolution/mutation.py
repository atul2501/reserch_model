"""DNA mutation (spec section 25). Produces a new, independently-valid
StrategyDNA by perturbing an existing one — never returns an invalid
payload (Pydantic re-validation on construction guarantees this)."""
from __future__ import annotations

import random

from app.schemas.strategy_dna import StrategyDNA

MUTATION_RATE = 0.3  # probability any given mutable field is touched


def mutate(dna: StrategyDNA, rng: random.Random | None = None) -> StrategyDNA:
    rng = rng or random.Random()
    data = dna.model_dump()

    if rng.random() < MUTATION_RATE:
        data["risk_profile"]["max_position_fraction"] = jitter(
            data["risk_profile"]["max_position_fraction"], rng, 0.01, 1.0
        )
    if rng.random() < MUTATION_RATE:
        data["risk_profile"]["max_leverage"] = float(rng.choice([1.0, 2.0, 3.0, 5.0]))

    if rng.random() < MUTATION_RATE:
        data["stop_loss"]["value"] = jitter(data["stop_loss"]["value"], rng, 0.5, 6.0)
    if rng.random() < MUTATION_RATE:
        data["take_profit"]["value"] = jitter(data["take_profit"]["value"], rng, 0.5, 8.0)

    if rng.random() < MUTATION_RATE:
        data["position_sizing"]["fraction_of_equity"] = jitter(
            data["position_sizing"]["fraction_of_equity"], rng, 0.005, 0.5
        )

    if rng.random() < MUTATION_RATE:
        data["max_trades_per_day"] = max(1, int(jitter(data["max_trades_per_day"], rng, 1, 200)))

    if rng.random() < MUTATION_RATE:
        _mutate_ruleset_thresholds(data["entry_rules"], rng)
    if rng.random() < MUTATION_RATE:
        _mutate_ruleset_thresholds(data["exit_rules"], rng)

    return StrategyDNA.model_validate(data)


def jitter(value: float, rng: random.Random, lo: float, hi: float, spread: float = 0.25) -> float:
    delta = value * spread * rng.uniform(-1, 1)
    return round(max(lo, min(hi, value + delta)), 4)


def _mutate_ruleset_thresholds(ruleset: dict, rng: random.Random) -> None:
    for condition in ruleset["conditions"]:
        if isinstance(condition["value"], (int, float)):
            condition["value"] = round(condition["value"] * rng.uniform(0.85, 1.15), 4)
