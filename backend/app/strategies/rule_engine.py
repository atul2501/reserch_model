"""Deterministic strategy evaluator (spec sections 3/4/10).

Takes a StrategyDNA and a MarketContext (the shared, already-computed
feature set) and produces a Bias + confidence. No network calls, no LLM —
this must be fast enough to run for 500 agents on every candle.

Ollama never decides BUY/SELL directly; it only ever proposes/mutates the
DNA that this engine evaluates deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Bias
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA

# Feature keys that support crosses_above/crosses_below need the previous
# bar's value too; callers pass the prior MarketContext when available.


@dataclass
class SignalResult:
    bias: Bias
    confidence: float
    matched_entry: bool
    matched_exit: bool
    reasoning: dict = field(default_factory=dict)


def _eval_condition(cond: Condition, features: dict, prev_features: dict | None) -> bool:
    value = features.get(cond.feature)
    if value is None:
        return False

    target = cond.value
    if isinstance(target, str) and target in features:
        target = features[target]

    if cond.operator == "gt":
        return value > target
    if cond.operator == "lt":
        return value < target
    if cond.operator == "gte":
        return value >= target
    if cond.operator == "lte":
        return value <= target
    if cond.operator in ("crosses_above", "crosses_below"):
        if prev_features is None:
            return False
        prev_value = prev_features.get(cond.feature)
        if prev_value is None:
            return False
        prev_target = cond.value if not (isinstance(cond.value, str) and cond.value in prev_features) else prev_features[cond.value]
        if cond.operator == "crosses_above":
            return prev_value <= prev_target and value > target
        return prev_value >= prev_target and value < target
    raise ValueError(f"unsupported operator: {cond.operator}")


def _eval_ruleset(rules: RuleSet, features: dict, prev_features: dict | None) -> bool:
    results = [_eval_condition(c, features, prev_features) for c in rules.conditions]
    return all(results) if rules.logic == "AND" else any(results)


def evaluate(
    dna: StrategyDNA,
    context: MarketContext,
    prev_context: MarketContext | None = None,
    has_open_position: bool = False,
) -> SignalResult:
    features = context.flat_features()
    prev_features = prev_context.flat_features() if prev_context else None

    if dna.regime_preferences and context.regime.regime not in dna.regime_preferences:
        return SignalResult(
            bias=Bias.NEUTRAL,
            confidence=0.0,
            matched_entry=False,
            matched_exit=False,
            reasoning={"skipped": "regime_not_preferred", "regime": context.regime.regime.value},
        )

    if has_open_position:
        matched_exit = _eval_ruleset(dna.exit_rules, features, prev_features)
        return SignalResult(
            bias=Bias.NEUTRAL if matched_exit else Bias.LONG,  # caller interprets NEUTRAL-while-open as "close"
            confidence=1.0 if matched_exit else 0.5,
            matched_entry=False,
            matched_exit=matched_exit,
            reasoning={"exit_conditions_met": matched_exit},
        )

    matched_entry = _eval_ruleset(dna.entry_rules, features, prev_features)
    if not matched_entry:
        return SignalResult(
            bias=Bias.NEUTRAL,
            confidence=0.0,
            matched_entry=False,
            matched_exit=False,
            reasoning={"entry_conditions_met": False},
        )

    # Direction is inferred from trend_strength sign by convention for
    # families that don't encode direction explicitly in entry_rules.
    bias = Bias.LONG if features.get("trend_strength", 0) >= 0 else Bias.SHORT
    confidence = min(1.0, 0.5 + context.regime.confidence / 2)
    return SignalResult(
        bias=bias,
        confidence=confidence,
        matched_entry=True,
        matched_exit=False,
        reasoning={"entry_conditions_met": True, "regime": context.regime.regime.value},
    )
