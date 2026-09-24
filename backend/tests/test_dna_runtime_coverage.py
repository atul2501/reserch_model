"""Every DNA field must either change runtime behaviour (with a test proving it)
or be explicitly documented metadata (spec phase 3): no silent dead fields."""
from __future__ import annotations

from pathlib import Path

from app.schemas.strategy_dna import StrategyDNA

T = Path(__file__).parent

# field -> [(test file, test function)] proving it drives runtime behaviour
COVERAGE: dict[str, list[tuple[str, str]]] = {
    "strategy_family": [("test_strategy_engine_families.py", "test_auto_direction_is_resolved_by_family_not_by_a_universal_trend_rule"),
                        ("test_strategy_engine_families.py", "test_families_disagree_on_the_same_market")],
    "indicators": [("test_strategy_engine_families.py", "test_rules_read_the_indicator_period_the_dna_declared"),
                   ("test_backtest_parity.py", "test_declared_indicator_periods_drive_backtest_behaviour"),
                   ("test_indicators_dynamic.py", "test_ema_20_and_ema_50_are_different_series_matching_pandas")],
    "entry_rules": [("test_strategy_engine_families.py", "test_explicit_direction_modes")],
    "exit_rules": [("test_strategy_engine_families.py", "test_short_positions_use_short_exit_rules")],
    "direction_mode": [("test_strategy_engine_families.py", "test_explicit_direction_modes")],
    "short_entry_rules": [("test_strategy_engine_families.py", "test_explicit_direction_modes")],
    "short_exit_rules": [("test_strategy_engine_families.py", "test_short_positions_use_short_exit_rules")],
    "regime_preferences": [("test_strategy_engine_families.py", "test_regime_preference_gates_entries_but_never_exits")],
    "risk_profile": [("test_risk_engine.py", "test_risk_per_trade_limit_reduces_notional_so_a_stop_out_never_costs_more_than_the_limit"),
                     ("test_margin_liquidation.py", "test_leverage_multiplies_notional_but_margin_stays_within_the_cap")],
    "position_sizing": [("test_sizing.py", "test_risk_based_notional_is_risk_over_stop_distance_capped_by_leverage"),
                        ("test_backtest_parity.py", "test_every_dna_sizing_method_trades_in_the_backtest")],
    "stop_loss": [("test_stops_trailing.py", "test_worker_applies_stop_loss_from_dna")],
    "take_profit": [("test_stops_trailing.py", "test_worker_applies_take_profit_from_dna")],
    "trailing_stop": [("test_stops_trailing.py", "test_worker_trailing_stop_arms_then_exits")],
    "cooldown": [("test_cooldown_limits.py", "test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows")],
    "max_trades_per_day": [("test_cooldown_limits.py", "test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day")],
    "leverage_limit": [("test_margin_liquidation.py", "test_leverage_multiplies_notional_but_margin_stays_within_the_cap")],
}
# Documented metadata: no runtime behaviour by design (see the field's comment in strategy_dna.py).
METADATA = {"lookback_periods"}


def test_every_dna_field_is_either_runtime_covered_or_documented_metadata():
    fields = set(StrategyDNA.model_fields)
    assert fields == set(COVERAGE) | METADATA, f"uncategorised DNA fields: {fields ^ (set(COVERAGE) | METADATA)}"


import ast  # noqa: E402


def has_asserting_test(source: str, fn: str) -> bool:
    """A REAL test function (not a comment, docstring or helper) that contains at least one `assert`."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn and node.name.startswith("test_"):
            return any(isinstance(n, ast.Assert) for n in ast.walk(node))
    return False


def test_every_coverage_reference_points_at_a_real_asserting_test():
    for field, refs in COVERAGE.items():
        assert refs, field
        for file, fn in refs:
            assert has_asserting_test((T / file).read_text(), fn), f"{field}: no asserting test {file}::{fn}"


def test_metadata_fields_are_documented_as_such_in_the_schema():
    src = (Path(__file__).resolve().parents[1] / "app" / "schemas" / "strategy_dna.py").read_text()
    assert "METADATA ONLY" in src


# --- SUBFIELDS: every behaviour-defining nested field must have a test that actually changes its value ------------------
# (a top-level mapping is not enough: `trailing_stop` "covered" while `trail_pct` is inert would still pass it).
SUBFIELD_COVERAGE: dict[str, tuple[str, str]] = {
    "risk_profile.max_leverage": ("test_risk_engine.py", "test_reduces_excessive_leverage"),
    "risk_profile.max_position_fraction": ("test_risk_engine.py", "test_risk_per_trade_limit_reduces_notional_so_a_stop_out_never_costs_more_than_the_limit"),
    "risk_profile.max_daily_loss_fraction": ("test_dna_subfield_behaviour.py", "test_dna_daily_loss_and_drawdown_limits_are_enforced"),
    "risk_profile.max_drawdown_fraction": ("test_dna_subfield_behaviour.py", "test_dna_daily_loss_and_drawdown_limits_are_enforced"),
    "position_sizing.method": ("test_backtest_parity.py", "test_every_dna_sizing_method_trades_in_the_backtest"),
    "position_sizing.fraction_of_equity": ("test_sizing.py", "test_risk_based_notional_is_risk_over_stop_distance_capped_by_leverage"),
    "position_sizing.max_notional": ("test_dna_subfield_behaviour.py", "test_position_sizing_max_notional_caps_the_order"),
    "stop_loss.enabled": ("test_dna_subfield_behaviour.py", "test_stop_and_take_profit_can_be_disabled"),
    "stop_loss.method": ("test_dna_subfield_behaviour.py", "test_every_stop_loss_method_places_a_different_stop"),
    "stop_loss.value": ("test_stops_trailing.py", "test_worker_applies_stop_loss_from_dna"),
    "take_profit.enabled": ("test_dna_subfield_behaviour.py", "test_stop_and_take_profit_can_be_disabled"),
    "take_profit.method": ("test_dna_subfield_behaviour.py", "test_every_take_profit_method_places_a_different_target"),
    "take_profit.value": ("test_stops_trailing.py", "test_worker_applies_take_profit_from_dna"),
    "trailing_stop.enabled": ("test_stops_trailing.py", "test_worker_trailing_stop_arms_then_exits"),
    "trailing_stop.activation_pct": ("test_stops_trailing.py", "test_trailing_arms_only_after_activation_pct"),
    "trailing_stop.trail_pct": ("test_dna_subfield_behaviour.py", "test_trailing_distance_comes_from_trail_pct"),
    "cooldown.bars_after_loss": ("test_cooldown_limits.py", "test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows"),
    "cooldown.bars_after_win": ("test_dna_subfield_behaviour.py", "test_cooldown_after_a_win_uses_bars_after_win"),
}


def _model_subfields() -> set[str]:
    from pydantic import BaseModel

    out: set[str] = set()
    for name, field in StrategyDNA.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel) and name not in ("entry_rules", "exit_rules"):
            out |= {f"{name}.{sub}" for sub in ann.model_fields}
    return out


def test_every_nested_dna_field_is_covered_by_a_named_behaviour_test():
    assert _model_subfields() == set(SUBFIELD_COVERAGE), _model_subfields() ^ set(SUBFIELD_COVERAGE)


def test_every_subfield_reference_points_at_a_real_asserting_test():
    for sub, (file, fn) in SUBFIELD_COVERAGE.items():
        assert has_asserting_test((T / file).read_text(), fn), f"{sub}: no asserting test {file}::{fn}"


def test_the_reference_check_rejects_commented_out_empty_and_missing_tests():
    """The previous check was a substring search: a commented-out `def` or an empty test satisfied it."""
    assert has_asserting_test("def test_a():\n    assert 1 == 1\n", "test_a")
    assert not has_asserting_test("# def test_a():\n#     assert 1\n", "test_a")            # commented out
    assert not has_asserting_test("def test_a():\n    pass\n", "test_a")                      # no assertion
    assert not has_asserting_test("def helper():\n    assert 1\n", "helper")                  # not a test
    assert not has_asserting_test("def test_b():\n    assert 1\n", "test_a")                  # missing
