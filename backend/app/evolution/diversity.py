"""Strategy diversity tracking (spec section 27/29).

Measures how similar two DNA payloads are so the evolution engine can
detect population homogenization and correlated agent behavior before it
becomes a hidden single point of failure.
"""
from __future__ import annotations

from app.schemas.strategy_dna import StrategyDNA


_SCALES = (20.0, 1.0, 6.0, 8.0, 1.0, 200.0, 20.0)


def dna_signature(dna: StrategyDNA) -> tuple:
    """Everything `dna_distance` needs, resolved ONCE per DNA. Resolving indicator specs is the expensive part; the
    O(n^2) population scans below used to redo it for every pair (~125k times for 500 agents) on the event loop."""
    return (
        dna.strategy_family,
        (
            dna.risk_profile.max_leverage, dna.risk_profile.max_position_fraction, dna.stop_loss.value,
            dna.take_profit.value, dna.position_sizing.fraction_of_equity, dna.max_trades_per_day, dna.leverage_limit,
        ),
        frozenset(_spec_set(dna)),
        dna.direction_mode,
    )


def signature_distance(sa: tuple, sb: tuple) -> float:
    if sa[0] != sb[0]:
        return 1.0
    diffs = [abs(x - y) / scale for x, y, scale in zip(sa[1], sb[1], _SCALES)]
    specs_a, specs_b = sa[2], sb[2]
    union = specs_a | specs_b
    diffs.append(1.0 - (len(specs_a & specs_b) / len(union)) if union else 0.0)
    diffs.append(0.0 if sa[3] == sb[3] else 1.0)
    return sum(diffs) / len(diffs)


def dna_distance(a: StrategyDNA, b: StrategyDNA) -> float:
    """A simple, interpretable [0, 1] distance: 0 = identical family and near-identical parameters, 1 = maximally
    different. Not a learned embedding - deliberately auditable. Behavioural structure (which indicators with which
    periods, how direction is chosen) counts, not just scalar risk parameters."""
    return signature_distance(dna_signature(a), dna_signature(b))


def _spec_set(dna: StrategyDNA) -> set:
    from app.strategies.engine import dna_indicator_specs
    return dna_indicator_specs(dna)


def population_diversity_score(dnas: list[StrategyDNA], signatures: list[tuple] | None = None) -> float:
    """Average pairwise distance across the population. Low values (e.g. < 0.15) indicate the population has
    homogenized and diversity pressure (more mutation, novel-family injection) should be applied."""
    if len(dnas) < 2:
        return 1.0
    sigs = signatures if signatures is not None else [dna_signature(d) for d in dnas]
    total, count = 0.0, 0
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            total += signature_distance(sigs[i], sigs[j])
            count += 1
    return total / count if count else 1.0


def most_similar_pair(dnas: list[StrategyDNA], signatures: list[tuple] | None = None) -> tuple[int, int]:
    """Indices of the least-diverse pair (O(n^2) over precomputed signatures)."""
    sigs = signatures if signatures is not None else [dna_signature(d) for d in dnas]
    best_i, best_j, best_distance = 0, 1, float("inf")
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            d = signature_distance(sigs[i], sigs[j])
            if d < best_distance:
                best_i, best_j, best_distance = i, j, d
    return best_i, best_j


def family_distribution(dnas: list[StrategyDNA]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for dna in dnas:
        key = dna.strategy_family.value
        dist[key] = dist.get(key, 0) + 1
    return dist
