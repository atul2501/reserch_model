"""Strategy engine (spec phases 3-5): every family behaves differently, DNA
fields drive runtime behaviour, unknown features are surfaced not swallowed."""
from __future__ import annotations

import random

import pytest

from app.evolution.mutation import mutate
from app.models.enums import Bias, MarketRegime, Side, StrategyFamily
from app.schemas.strategy_dna import Condition, RuleSet
from app.strategies.engine import (
    build_feature_view, dna_indicator_specs, evaluate_signal, population_indicator_specs, unknown_features,
)
from app.strategies.factory import generate_population_dna
from app.strategies.families import FAMILIES, get_family
from tests.helpers_agents import make_context, make_dna

ALWAYS = RuleSet(conditions=[Condition(feature="close", operator="gt", value=0)])


def _view(ctx, dyn=None, prev=None):
    return build_feature_view(ctx, prev, dyn or {}, {})


def test_all_ten_families_are_defined():
    assert set(FAMILIES) == set(StrategyFamily)


def test_families_disagree_on_the_same_market():
    """A stretched uptrend: trend follows it up, mean-reversion fades it."""
    ctx = make_context(1, 100.0, trend_strength=0.02, roc=2.0, macd_hist=0.5, rsi=80, atr=0.5)
    f = ctx.flat_features()
    f["bb_upper"], f["bb_lower"], f["bb_middle"] = 100.5, 96.0, 98.0   # close near the upper band
    assert get_family(StrategyFamily.TREND_FOLLOWING).direction(f) == Bias.LONG
    assert get_family(StrategyFamily.MOMENTUM).direction(f) == Bias.LONG
    assert get_family(StrategyFamily.MEAN_REVERSION).direction(f) == Bias.SHORT
    assert get_family(StrategyFamily.VWAP).direction({**f, "vwap": 97.0}) == Bias.SHORT   # >0.2% above VWAP -> revert
    assert get_family(StrategyFamily.VWAP).direction({**f, "vwap": 100.0}) == Bias.LONG   # hugging VWAP -> follow trend


def test_auto_direction_is_resolved_by_family_not_by_a_universal_trend_rule():
    dna_mr = make_dna(strategy_family=StrategyFamily.MEAN_REVERSION, entry_rules=ALWAYS)
    dna_tf = make_dna(strategy_family=StrategyFamily.TREND_FOLLOWING, entry_rules=ALWAYS)
    ctx = make_context(1, 100.0, trend_strength=0.02)
    view = _view(ctx)
    view.current.update(bb_upper=100.5, bb_lower=96.0)
    assert evaluate_signal(dna_tf, view).bias == Bias.LONG
    assert evaluate_signal(dna_mr, view).bias == Bias.SHORT


def test_explicit_direction_modes():
    ctx = make_context(1, 100.0)
    view = _view(ctx)
    assert evaluate_signal(make_dna(direction_mode="long_only", entry_rules=ALWAYS), view).bias == Bias.LONG
    assert evaluate_signal(make_dna(direction_mode="short_only", entry_rules=ALWAYS), view).bias == Bias.SHORT
    never = RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)])
    both_long = make_dna(direction_mode="both", entry_rules=ALWAYS, short_entry_rules=never)
    both_short = make_dna(direction_mode="both", entry_rules=never, short_entry_rules=ALWAYS)
    conflict = make_dna(direction_mode="both", entry_rules=ALWAYS, short_entry_rules=ALWAYS)
    assert evaluate_signal(both_long, view).bias == Bias.LONG
    assert evaluate_signal(both_short, view).bias == Bias.SHORT
    assert evaluate_signal(conflict, view).matched_entry is False  # ambiguous -> no trade


def test_both_mode_requires_short_rules():
    with pytest.raises(ValueError):
        make_dna(direction_mode="both", entry_rules=ALWAYS)


def test_short_positions_use_short_exit_rules():
    exit_long = RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)])   # never
    exit_short = RuleSet(conditions=[Condition(feature="close", operator="gt", value=0)])  # always
    never = RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)])
    dna = make_dna(direction_mode="both", entry_rules=never, short_entry_rules=never, exit_rules=exit_long, short_exit_rules=exit_short)
    view = _view(make_context(1, 100.0))
    assert evaluate_signal(dna, view, position_side=Side.LONG).matched_exit is False
    assert evaluate_signal(dna, view, position_side=Side.SHORT).matched_exit is True


def test_opposite_entry_signal_reverses_an_open_position():
    dna = make_dna(direction_mode="both", entry_rules=RuleSet(conditions=[Condition(feature="close", operator="lt", value=0)]),
                   short_entry_rules=ALWAYS)
    sig = evaluate_signal(dna, _view(make_context(1, 100.0)), position_side=Side.LONG)
    assert sig.matched_exit and sig.reasoning["exit_reason"] == "signal_reversal"


def test_regime_preference_gates_entries_but_never_exits():
    dna = make_dna(entry_rules=ALWAYS, direction_mode="long_only", regime_preferences=[MarketRegime.RANGE],
                   exit_rules=RuleSet(conditions=[Condition(feature="close", operator="gt", value=0)]))
    view = _view(make_context(1, 100.0, regime="TREND_UP"))
    entry = evaluate_signal(dna, view)
    assert entry.matched_entry is False and entry.reasoning["skipped"] == "regime_not_preferred"
    assert evaluate_signal(dna, view, position_side=Side.LONG).matched_exit is True  # exits ignore regime


def test_rules_read_the_indicator_period_the_dna_declared():
    ema20 = make_dna(indicators=[{"name": "ema", "params": {"period": 20}}], direction_mode="long_only",
                     entry_rules=RuleSet(conditions=[Condition(feature="close", operator="gt", value="ema_20")]))
    ema50 = make_dna(indicators=[{"name": "ema", "params": {"period": 50}}], direction_mode="long_only",
                     entry_rules=RuleSet(conditions=[Condition(feature="close", operator="gt", value="ema_50")]))
    dyn = {"ema_20": 99.0, "ema_50": 101.0}          # price between the two EMAs
    view = _view(make_context(1, 100.0), dyn)
    assert evaluate_signal(ema20, view).matched_entry is True
    assert evaluate_signal(ema50, view).matched_entry is False   # same market, different declared period -> different decision
    assert dna_indicator_specs(ema20) != dna_indicator_specs(ema50)


def test_crosses_operator_works_on_dynamic_features_without_prev_context():
    dna = make_dna(indicators=[{"name": "ema", "params": {"period": 12}}, {"name": "ema", "params": {"period": 26}}],
                   direction_mode="long_only",
                   entry_rules=RuleSet(conditions=[Condition(feature="ema_12", operator="crosses_above", value="ema_26")]))
    ctx = make_context(1, 100.0)
    crossed = build_feature_view(ctx, None, {"ema_12": 101.0, "ema_26": 100.0}, {"ema_12": 99.0, "ema_26": 100.0})
    not_crossed = build_feature_view(ctx, None, {"ema_12": 101.0, "ema_26": 100.0}, {"ema_12": 100.5, "ema_26": 100.0})
    assert evaluate_signal(dna, crossed).matched_entry is True
    assert evaluate_signal(dna, not_crossed).matched_entry is False


def test_unknown_feature_is_reported_and_never_silently_true():
    dna = make_dna(direction_mode="long_only", entry_rules=RuleSet(conditions=[Condition(feature="rsi_7", operator="gt", value=50)]))
    assert unknown_features(dna) == ["rsi_7"]          # rsi_7 not declared and not static
    sig = evaluate_signal(dna, _view(make_context(1, 100.0)))
    assert sig.matched_entry is False and "rsi_7" in sig.reasoning["missing_features"]


def test_factory_population_is_feature_consistent_and_diverse():
    dnas = generate_population_dna(500, seed=11)
    assert all(unknown_features(d) == [] for d in dnas)
    assert len({d.strategy_family for d in dnas}) == 10
    assert len({d.position_sizing.method for d in dnas}) >= 3
    assert sum(d.direction_mode == "both" for d in dnas) > 400
    # Indicator periods genuinely vary across agents of the same family.
    momentum_specs = {tuple(sorted(dna_indicator_specs(d), key=str)) for d in dnas if d.strategy_family == StrategyFamily.MOMENTUM}
    assert len(momentum_specs) > 3


def test_shared_specs_are_far_fewer_than_agents():
    dnas = generate_population_dna(500, seed=5)
    assert len(population_indicator_specs(dnas)) < 150


def test_mutation_keeps_rules_bound_to_declared_indicators():
    rng = random.Random(9)
    for dna in generate_population_dna(120, seed=2):
        for _ in range(4):
            assert unknown_features(mutate(dna, rng)) == []


def test_each_generated_dna_can_actually_produce_a_signal_somewhere():
    """No family is dead-on-arrival: on some plausible feature vector at least one DNA per family fires."""
    dnas = generate_population_dna(300, seed=3)
    fired: set[StrategyFamily] = set()
    import numpy as np, pandas as pd
    from app.strategies.engine import compute_population_features
    from app.market.feature_engine import compute_features
    rng = np.random.default_rng(7)
    for trial in range(40):
        n = 300
        close = 100 + np.cumsum(rng.normal(0.02 * (1 if trial % 2 else -1), 0.4, n))
        df = pd.DataFrame({"open_time": np.arange(n) * 60_000 + 1_700_000_040_000, "open": close - rng.normal(0, .1, n),
                           "high": close + rng.uniform(0.05, 0.8, n), "low": close - rng.uniform(0.05, 0.8, n), "close": close,
                           "volume": rng.uniform(200, 3000, n)})
        ctx = compute_features(df, "SOL", "1m")
        dyn, dynp = compute_population_features(df, dnas)
        view = build_feature_view(ctx, None, dyn, dynp)
        for d in dnas:
            d2 = d.model_copy(update={"regime_preferences": []})
            if evaluate_signal(d2, view).matched_entry:
                fired.add(d.strategy_family)
    assert len(fired) >= 8, fired
