"""DNA mutation (spec section 25). Produces a new, independently-valid
StrategyDNA by perturbing an existing one — never returns an invalid
payload (Pydantic re-validation on construction guarantees this)."""
from __future__ import annotations

import random

from app.schemas.strategy_dna import StrategyDNA
from app.strategies.indicators import UnknownIndicatorError, feature_keys_for, resolve_spec

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

    for name in ("entry_rules", "exit_rules", "short_entry_rules", "short_exit_rules"):
        if data.get(name) and rng.random() < MUTATION_RATE:
            _mutate_ruleset_thresholds(data[name], rng)

    if rng.random() < MUTATION_RATE:
        _mutate_indicator_period(data, rng)

    # Keep the cross-field invariant instead of raising on an unlucky draw.
    data["leverage_limit"] = min(data["leverage_limit"], data["risk_profile"]["max_leverage"])
    return StrategyDNA.model_validate(data)


_RULESETS = ("entry_rules", "exit_rules", "short_entry_rules", "short_exit_rules")


def _mutate_indicator_period(data: dict, rng: random.Random) -> None:
    """Changes one declared indicator's period AND rewrites every rule that
    referenced its old feature key, so the mutated DNA still reads exactly
    the indicators it declares (a period change must never orphan a rule)."""
    candidates = [i for i, cfg in enumerate(data["indicators"]) if isinstance(cfg["params"].get("period"), (int, float)) and cfg["params"]["period"] > 0]
    if not candidates:
        return
    idx = rng.choice(candidates)
    cfg = data["indicators"][idx]
    old_period = int(cfg["params"]["period"])
    new_period = max(2, min(200, int(round(old_period * rng.uniform(0.7, 1.4)))))
    if new_period == old_period:
        return
    try:
        old_spec = resolve_spec(cfg["name"], cfg["params"])
        new_params = {**cfg["params"], "period": new_period}
        new_spec = resolve_spec(cfg["name"], new_params)
    except (UnknownIndicatorError, ValueError):
        return
    # Refuse a rename that would collide with another declared indicator.
    for j, other in enumerate(data["indicators"]):
        if j != idx:
            try:
                if resolve_spec(other["name"], other["params"]) == new_spec:
                    return
            except (UnknownIndicatorError, ValueError):
                continue
    mapping = {o: n for o, n in zip(feature_keys_for(old_spec), feature_keys_for(new_spec)) if o != n}
    cfg["params"] = new_params
    for name in _RULESETS:
        rs = data.get(name)
        if not rs:
            continue
        for cond in rs["conditions"]:
            cond["feature"] = mapping.get(cond["feature"], cond["feature"])
            if isinstance(cond["value"], str):
                cond["value"] = mapping.get(cond["value"], cond["value"])


def jitter(value: float, rng: random.Random, lo: float, hi: float, spread: float = 0.25) -> float:
    delta = value * spread * rng.uniform(-1, 1)
    return round(max(lo, min(hi, value + delta)), 4)


def _mutate_ruleset_thresholds(ruleset: dict, rng: random.Random) -> None:
    for condition in ruleset["conditions"]:
        if isinstance(condition["value"], (int, float)):
            condition["value"] = round(condition["value"] * rng.uniform(0.85, 1.15), 4)
