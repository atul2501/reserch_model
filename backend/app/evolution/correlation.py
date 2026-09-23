"""DNA-structural similarity — extends app/evolution/diversity.py's
`dna_distance`, which only compares 7 scalar risk/exit fields and ignores
indicators/entry_rules/exit_rules/regime_preferences entirely. These three
functions fill exactly that gap for StrategyCorrelationEngine; they are
pure and CPU-only (no DB I/O — see correlation_service.py for the
behavioral, trade-derived dimensions).
"""
from __future__ import annotations

from app.schemas.strategy_dna import RuleSet, StrategyDNA
from app.strategies.engine import dna_indicator_specs


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def feature_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    """Jaccard similarity over each DNA's (indicator name, sorted params)
    set plus its lookback_periods keys — 1.0 means the two strategies
    depend on an identical feature set, 0.0 means no overlap at all."""
    # Resolved indicator specs: EMA(20) and EMA(50) are DIFFERENT features.
    set_a: set = set(dna_indicator_specs(a))
    set_a |= {f"lookback:{k}" for k in a.lookback_periods}
    set_b: set = set(dna_indicator_specs(b))
    set_b |= {f"lookback:{k}" for k in b.lookback_periods}
    return _jaccard(set_a, set_b)


def _condition_set(ruleset: RuleSet) -> set[tuple[str, str, float | str]]:
    return {(c.feature, c.operator, c.value) for c in ruleset.conditions}


def _ruleset_similarity(a: RuleSet, b: RuleSet) -> float:
    jaccard = _jaccard(_condition_set(a), _condition_set(b))
    logic_match = 1.0 if a.logic == b.logic else 0.0
    return (jaccard + logic_match) / 2


def entry_condition_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    """Jaccard similarity over (feature, operator, value) entry conditions,
    averaged with whether both use the same AND/OR combination logic."""
    return _ruleset_similarity(a.entry_rules, b.entry_rules)


def exit_condition_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    return _ruleset_similarity(a.exit_rules, b.exit_rules)
