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


def feature_set(dna: StrategyDNA) -> set:
    """Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the lookback_periods keys."""
    out: set = set(dna_indicator_specs(dna))
    out |= {f"lookback:{k}" for k in dna.lookback_periods}
    return out


def feature_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    """Jaccard similarity over each DNA's (indicator name, sorted params)
    set plus its lookback_periods keys — 1.0 means the two strategies
    depend on an identical feature set, 0.0 means no overlap at all."""
    return _jaccard(feature_set(a), feature_set(b))


def _condition_set(ruleset: RuleSet) -> set[tuple[str, str, float | str]]:
    return {(c.feature, c.operator, c.value) for c in ruleset.conditions}


def ruleset_signature(rs: RuleSet) -> tuple[frozenset, str]:
    return frozenset(_condition_set(rs)), rs.logic


def ruleset_signature_similarity(sa: tuple[frozenset, str], sb: tuple[frozenset, str]) -> float:
    return (_jaccard(sa[0], sb[0]) + (1.0 if sa[1] == sb[1] else 0.0)) / 2


def _ruleset_similarity(a: RuleSet, b: RuleSet) -> float:
    return ruleset_signature_similarity(ruleset_signature(a), ruleset_signature(b))


def entry_condition_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    """Jaccard similarity over (feature, operator, value) entry conditions,
    averaged with whether both use the same AND/OR combination logic."""
    return _ruleset_similarity(a.entry_rules, b.entry_rules)


def exit_condition_similarity(a: StrategyDNA, b: StrategyDNA) -> float:
    return _ruleset_similarity(a.exit_rules, b.exit_rules)
