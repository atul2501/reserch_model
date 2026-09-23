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
    "position_sizing": [("test_sizing.py", "test_every_dna_sizing_method_trades_in_the_backtest") if False else ("test_sizing.py", "test_risk_based_notional_is_risk_over_stop_distance_capped_by_leverage"),
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


def test_every_coverage_reference_points_at_a_real_test():
    for field, refs in COVERAGE.items():
        assert refs, field
        for file, fn in refs:
            assert f"def {fn}" in (T / file).read_text(), f"{field}: missing {file}::{fn}"


def test_metadata_fields_are_documented_as_such_in_the_schema():
    src = (Path(__file__).resolve().parents[1] / "app" / "schemas" / "strategy_dna.py").read_text()
    assert "METADATA ONLY" in src
