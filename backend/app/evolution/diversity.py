"""Strategy diversity tracking (spec section 27/29).

Measures how similar two DNA payloads are so the evolution engine can
detect population homogenization and correlated agent behavior before it
becomes a hidden single point of failure.
"""
from __future__ import annotations

from app.schemas.strategy_dna import StrategyDNA


def dna_distance(a: StrategyDNA, b: StrategyDNA) -> float:
    """A simple, interpretable [0, 1] distance: 0 = identical family and
    near-identical parameters, 1 = maximally different. Not a learned
    embedding — deliberately auditable."""
    if a.strategy_family != b.strategy_family:
        return 1.0

    fields = [
        (a.risk_profile.max_leverage, b.risk_profile.max_leverage, 20.0),
        (a.risk_profile.max_position_fraction, b.risk_profile.max_position_fraction, 1.0),
        (a.stop_loss.value, b.stop_loss.value, 6.0),
        (a.take_profit.value, b.take_profit.value, 8.0),
        (a.position_sizing.fraction_of_equity, b.position_sizing.fraction_of_equity, 1.0),
        (a.max_trades_per_day, b.max_trades_per_day, 200.0),
        (a.leverage_limit, b.leverage_limit, 20.0),
    ]
    diffs = [abs(x - y) / scale for x, y, scale in fields]
    # Behavioural structure, not just scalar risk parameters: which indicators
    # (with which periods) a strategy reads, and how it chooses direction.
    specs_a, specs_b = _spec_set(a), _spec_set(b)
    union = specs_a | specs_b
    diffs.append(1.0 - (len(specs_a & specs_b) / len(union)) if union else 0.0)
    diffs.append(0.0 if a.direction_mode == b.direction_mode else 1.0)
    return sum(diffs) / len(diffs)


def _spec_set(dna: StrategyDNA) -> set:
    from app.strategies.engine import dna_indicator_specs
    return dna_indicator_specs(dna)


def population_diversity_score(dnas: list[StrategyDNA]) -> float:
    """Average pairwise distance across the population. Low values (e.g.
    < 0.15) indicate the population has homogenized and diversity pressure
    (more mutation, novel-family injection) should be applied."""
    if len(dnas) < 2:
        return 1.0
    total, count = 0.0, 0
    for i in range(len(dnas)):
        for j in range(i + 1, len(dnas)):
            total += dna_distance(dnas[i], dnas[j])
            count += 1
    return total / count if count else 1.0


def family_distribution(dnas: list[StrategyDNA]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for dna in dnas:
        key = dna.strategy_family.value
        dist[key] = dist.get(key, 0) + 1
    return dist
