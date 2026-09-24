"""StrategyEngine — deterministic evaluation of a StrategyDNA (spec phase 4).

    StrategyDNA + FeatureView(static context features + declared dynamic
    indicators) + RegimeContext  ->  Signal

* Every rule reads the features the DNA actually declared: `ema_20` for an
  EMA(20) agent, `ema_50` for an EMA(50) agent.
* Direction is explicit (`direction_mode`) or family-resolved (`auto`).
* Regime preferences gate ENTRIES only; exits are always evaluated.
* Unknown/unavailable features never crash and never silently pass: the
  condition is False and the missing keys are reported in `reasoning`.
* `population_indicator_specs` + `compute_indicator_features` let the worker
  compute each distinct indicator once for the whole population.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from app.models.enums import Bias, MarketRegime, Side
from app.schemas.market_context import MarketContext, static_feature_names
from app.schemas.strategy_dna import Condition, RuleSet, StrategyDNA
from app.strategies.families import get_family
from app.strategies.indicators import (
    IndicatorSpec,
    UnknownIndicatorError,
    compute_indicator_features,
    feature_keys_for,
    resolve_spec,
)

logger = logging.getLogger(__name__)

ENGINE_VERSION = "2.0"


@dataclass
class Signal:
    bias: Bias
    confidence: float
    matched_entry: bool
    matched_exit: bool
    reasoning: dict = field(default_factory=dict)


@dataclass
class FeatureView:
    current: dict
    previous: dict
    regime: MarketRegime
    regime_confidence: float


def build_feature_view(
    context: MarketContext,
    prev_context: MarketContext | None,
    dynamic_current: dict | None = None,
    dynamic_previous: dict | None = None,
) -> FeatureView:
    current = context.flat_features()
    current.update(dynamic_current or {})
    previous = prev_context.flat_features() if prev_context is not None else {}
    previous.update(dynamic_previous or {})
    return FeatureView(current, previous, context.regime.regime, context.regime.confidence)


# --------------------------------------------------------------------------- #
# DNA <-> indicator wiring
# --------------------------------------------------------------------------- #
def dna_indicator_specs(dna: StrategyDNA) -> set[IndicatorSpec]:
    """Distinct indicator specs a DNA declares. Legacy/invalid entries are
    skipped (logged) rather than crashing the population's cycle."""
    specs: set[IndicatorSpec] = set()
    for cfg in dna.indicators:
        params = dict(cfg.params)
        # Legacy DNA used `window`/`length` for the period.
        for alias in ("window", "length"):
            if alias in params and "period" not in params:
                params["period"] = params.pop(alias)
        try:
            specs.add(resolve_spec(cfg.name, params))
        except (UnknownIndicatorError, ValueError, TypeError) as exc:
            try:  # drop unknown params but keep the indicator
                base = resolve_spec(cfg.name, {})
                specs.add(base)
            except UnknownIndicatorError:
                logger.warning("strategy_engine.skipping_unknown_indicator name=%s err=%s", cfg.name, exc)
    return specs


def population_indicator_specs(dnas) -> set[IndicatorSpec]:
    specs: set[IndicatorSpec] = set()
    for dna in dnas:
        specs |= dna_indicator_specs(dna)
    return specs


def compute_population_features(candles: pd.DataFrame, dnas) -> tuple[dict, dict]:
    """Each distinct (indicator, params) computed once for the whole population."""
    return compute_indicator_features(candles, population_indicator_specs(dnas))


def _condition_features(rules: RuleSet | None) -> set[str]:
    keys: set[str] = set()
    if rules is None:
        return keys
    for c in rules.conditions:
        keys.add(c.feature)
        if isinstance(c.value, str):
            keys.add(c.value)
    return keys


def _all_rulesets(dna: StrategyDNA):
    return (dna.entry_rules, dna.exit_rules, dna.short_entry_rules, dna.short_exit_rules)


def available_feature_keys(dna: StrategyDNA) -> set[str]:
    keys = set(static_feature_names())
    for spec in dna_indicator_specs(dna):
        keys.update(feature_keys_for(spec))
    return keys


def unknown_features(dna: StrategyDNA) -> list[str]:
    """Rule features that are neither static nor produced by a declared
    indicator. Creation paths (factory/mutation/researcher) must reject DNA
    with a non-empty result; the runtime reports them instead of guessing."""
    known = available_feature_keys(dna)
    # A string `value` that is not a feature name is a literal (e.g. a regime label).
    unknown = {c.feature for rs in _all_rulesets(dna) if rs for c in rs.conditions} - known
    for rs in _all_rulesets(dna):
        if rs is None:
            continue
        for c in rs.conditions:
            if isinstance(c.value, str) and c.value not in known and c.value not in {r.value for r in MarketRegime}:
                unknown.add(c.value)
    return sorted(unknown)


# --------------------------------------------------------------------------- #
# Rule evaluation
# --------------------------------------------------------------------------- #
def _resolve_target(cond: Condition, table: dict):
    target = cond.value
    if isinstance(target, str):
        if target in table:
            return table[target]
        return target if target in {r.value for r in MarketRegime} else None
    return target


def _eval_condition(cond: Condition, view: FeatureView, missing: set[str]) -> bool:
    value = view.current.get(cond.feature)
    target = _resolve_target(cond, view.current)
    if value is None or target is None:
        missing.add(cond.feature if value is None else str(cond.value))
        return False
    op = cond.operator.value if hasattr(cond.operator, "value") else cond.operator
    try:
        if op == "gt":
            return bool(value > target)
        if op == "lt":
            return bool(value < target)
        if op == "gte":
            return bool(value >= target)
        if op == "lte":
            return bool(value <= target)
        if op in ("crosses_above", "crosses_below"):
            prev_value = view.previous.get(cond.feature)
            prev_target = _resolve_target(cond, view.previous)
            if prev_value is None or prev_target is None:
                return False
            if op == "crosses_above":
                return bool(prev_value <= prev_target and value > target)
            return bool(prev_value >= prev_target and value < target)
    except TypeError:  # e.g. comparing a regime label with a number
        missing.add(cond.feature)
        return False
    raise ValueError(f"unsupported operator: {op}")


def _eval_ruleset(rules: RuleSet | None, view: FeatureView, missing: set[str]) -> bool:
    if rules is None:
        return False
    results = [_eval_condition(c, view, missing) for c in rules.conditions]
    return all(results) if rules.logic == "AND" else any(results)


def _entry_direction(dna: StrategyDNA, view: FeatureView, missing: set[str]) -> tuple[Bias, dict]:
    mode = dna.direction_mode
    if mode == "long_only":
        return (Bias.LONG if _eval_ruleset(dna.entry_rules, view, missing) else Bias.NEUTRAL), {"direction_source": "dna:long_only"}
    if mode == "short_only":
        return (Bias.SHORT if _eval_ruleset(dna.entry_rules, view, missing) else Bias.NEUTRAL), {"direction_source": "dna:short_only"}
    if mode == "both":
        long_ok = _eval_ruleset(dna.entry_rules, view, missing)
        short_ok = _eval_ruleset(dna.short_entry_rules, view, missing)
        if long_ok and not short_ok:
            return Bias.LONG, {"direction_source": "dna:both"}
        if short_ok and not long_ok:
            return Bias.SHORT, {"direction_source": "dna:both"}
        return Bias.NEUTRAL, {"direction_source": "dna:both", "conflict": bool(long_ok and short_ok)}
    if not _eval_ruleset(dna.entry_rules, view, missing):
        return Bias.NEUTRAL, {"direction_source": "family"}
    return get_family(dna.strategy_family).direction(view.current), {"direction_source": f"family:{dna.strategy_family.value}"}


def evaluate_signal(dna: StrategyDNA, view: FeatureView, *, position_side: Side | None = None) -> Signal:
    missing: set[str] = set()
    base = {"engine_version": ENGINE_VERSION, "family": dna.strategy_family.value}

    if position_side is not None:
        exit_rules = dna.exit_rules
        if position_side == Side.SHORT and dna.direction_mode == "both" and dna.short_exit_rules is not None:
            exit_rules = dna.short_exit_rules
        matched_exit = _eval_ruleset(exit_rules, view, missing)
        reason = "exit_rules"
        if not matched_exit and dna.direction_mode == "both":
            opposing = dna.short_entry_rules if position_side == Side.LONG else dna.entry_rules
            if _eval_ruleset(opposing, view, missing):
                matched_exit, reason = True, "signal_reversal"
        holding = Bias.LONG if position_side == Side.LONG else Bias.SHORT
        return Signal(
            bias=Bias.NEUTRAL if matched_exit else holding,
            confidence=1.0 if matched_exit else 0.5,
            matched_entry=False,
            matched_exit=matched_exit,
            reasoning={**base, "exit_conditions_met": matched_exit, "exit_reason": reason if matched_exit else None,
                       **({"missing_features": sorted(missing)} if missing else {})},
        )

    if dna.regime_preferences and view.regime not in dna.regime_preferences:
        return Signal(Bias.NEUTRAL, 0.0, False, False, {**base, "skipped": "regime_not_preferred", "regime": view.regime.value})

    direction, meta = _entry_direction(dna, view, missing)
    reasoning = {**base, **meta, "regime": view.regime.value}
    if missing:
        reasoning["missing_features"] = sorted(missing)
    if direction == Bias.NEUTRAL:
        reasoning["entry_conditions_met"] = False
        return Signal(Bias.NEUTRAL, 0.0, False, False, reasoning)

    strength = get_family(dna.strategy_family).strength(view.current, direction)
    confidence = min(0.95, 0.5 + 0.25 * strength + 0.25 * view.regime_confidence)
    reasoning.update(entry_conditions_met=True, setup_strength=round(strength, 4))
    return Signal(direction, confidence, True, False, reasoning)
