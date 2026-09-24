"""Adversarial/stress testing harness: candle distortions, DNA parameter
perturbation, and the aggregate pass/fail suite (spec sections 22-25)."""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from app.backtesting.adversarial import (
    AdversarialReport,
    ScenarioResult,
    compute_robustness_score,
    inject_abnormal_volume,
    inject_extreme_move,
    inject_gap,
    inject_liquidity_reduction,
    inject_stale_period,
    inject_volatility_spike,
    perturb_dna_variants,
    run_adversarial_suite,
)
from app.backtesting.engine import BacktestResult
from app.models.enums import StrategyFamily
from app.schemas.strategy_dna import (
    Condition,
    PositionSizing,
    RiskProfile,
    RuleSet,
    StopLossConfig,
    StrategyDNA,
)


def _trending_candles(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(n):
        price += 0.05 + rng.normal(0, 0.15)
        open_ = price
        close = price + rng.normal(0, 0.1)
        high = max(open_, close) + abs(rng.normal(0, 0.05))
        low = min(open_, close) - abs(rng.normal(0, 0.05))
        volume = abs(rng.normal(1000, 50))
        rows.append({"open_time": i * 60_000, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
        price = close
    return pd.DataFrame(rows)


def _never_trades_dna() -> StrategyDNA:
    return StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=1000)]),  # impossible
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=-1000)]),
    )


def _fragile_dna() -> StrategyDNA:
    # Max leverage, max position size, and a stop wide enough that normal
    # noise won't trip it but a sudden double-digit-percent shock will —
    # with 20x notional on 100% of equity, one stop-out at a 10% adverse
    # price move wipes out ~2x the whole account.
    return StrategyDNA(
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        indicators=[{"name": "ema", "params": {"period": 12}}],
        entry_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="gt", value=0)]),
        exit_rules=RuleSet(conditions=[Condition(feature="trend_strength", operator="lt", value=-100)]),  # never exits via signal
        risk_profile=RiskProfile(max_leverage=20.0),
        position_sizing=PositionSizing(fraction_of_equity=1.0),
        stop_loss=StopLossConfig(enabled=True, method="fixed_pct", value=10.0),
        leverage_limit=20.0,
    )


def test_inject_volatility_spike_widens_range_at_index():
    candles = _trending_candles(50)
    idx = 25
    original_range = candles.loc[idx, "high"] - candles.loc[idx, "low"]
    stressed = inject_volatility_spike(candles, magnitude=3.0, at_index=idx)
    assert stressed.loc[idx, "high"] - stressed.loc[idx, "low"] == pytest.approx(original_range * 3.0)
    # untouched elsewhere
    assert stressed.loc[idx - 1, "high"] == candles.loc[idx - 1, "high"]


def test_inject_gap_shifts_price_level_from_index_onward():
    candles = _trending_candles(50)
    idx = 25
    before_close = candles.loc[idx - 1, "close"]
    stressed = inject_gap(candles, gap_pct=-0.08, at_index=idx)
    assert stressed.loc[idx, "close"] == pytest.approx(candles.loc[idx, "close"] * 0.92)
    assert stressed.loc[idx - 1, "close"] == before_close  # untouched before the gap


def test_inject_stale_period_flattens_ohlc_and_zeroes_volume():
    candles = _trending_candles(50)
    idx = 20
    stressed = inject_stale_period(candles, length=5, at_index=idx)
    last_close = candles.loc[idx - 1, "close"]
    for i in range(idx, idx + 5):
        assert stressed.loc[i, "open"] == pytest.approx(last_close)
        assert stressed.loc[i, "close"] == pytest.approx(last_close)
        assert stressed.loc[i, "volume"] == 0.0


def test_inject_extreme_move_applies_permanent_shock():
    candles = _trending_candles(50)
    idx = 25
    stressed = inject_extreme_move(candles, direction="down", magnitude=0.25, at_index=idx)
    assert stressed.loc[idx, "close"] == pytest.approx(candles.loc[idx, "close"] * 0.75)
    assert stressed.loc[len(candles) - 1, "close"] == pytest.approx(candles.loc[len(candles) - 1, "close"] * 0.75)


def test_inject_abnormal_volume_spikes_only_the_windowed_volume():
    candles = _trending_candles(50)
    idx = 20
    stressed = inject_abnormal_volume(candles, magnitude=5.0, at_index=idx, length=5)
    for i in range(idx, idx + 5):
        assert stressed.loc[i, "volume"] == pytest.approx(candles.loc[i, "volume"] * 5.0)
        assert stressed.loc[i, "close"] == candles.loc[i, "close"]  # price untouched
    assert stressed.loc[idx - 1, "volume"] == candles.loc[idx - 1, "volume"]  # untouched before window


def test_inject_liquidity_reduction_collapses_windowed_volume():
    candles = _trending_candles(50)
    idx = 20
    stressed = inject_liquidity_reduction(candles, magnitude=0.05, at_index=idx, length=5)
    for i in range(idx, idx + 5):
        assert stressed.loc[i, "volume"] == pytest.approx(candles.loc[i, "volume"] * 0.05)
        assert stressed.loc[i, "close"] == candles.loc[i, "close"]


def test_perturb_dna_variants_produces_distinct_valid_variants():
    dna = _never_trades_dna()  # default-range stop_loss.value, unlike _fragile_dna's out-of-range fixed_pct value
    variants = perturb_dna_variants(dna, 5, rng=random.Random(1))
    assert len(variants) == 5
    assert all(isinstance(v, StrategyDNA) for v in variants)
    values = {v.stop_loss.value for v in variants}
    assert len(values) > 1  # jittering actually varies the parameter


def test_a_strategy_that_never_trades_does_not_pass_the_adversarial_suite():
    """No trades means no drawdown - and no evidence of robustness. Inactivity must never look perfectly robust."""
    candles = _trending_candles(600)
    report = run_adversarial_suite(
        _never_trades_dna(), candles, symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2, rng=random.Random(7),
    )
    assert report.passed is False and "strategy_never_traded_in_any_scenario" in report.failure_reasons
    assert report.total_trades == 0 and report.worst_case_net_return_pct == pytest.approx(0.0)
    assert compute_robustness_score(report) == 0.0


def test_adversarial_suite_fails_for_an_overleveraged_strategy_when_risk_engine_bypassed():
    """`bypass_risk_engine=True` is the test-only escape hatch for
    reproducing pre-Phase-0 behavior: with no Risk Engine in the loop at
    all, this DNA's own 20x-leverage/100%-notional/10%-stop combination is
    exactly as fragile as its docstring describes."""
    candles = _trending_candles(600)
    report = run_adversarial_suite(
        _fragile_dna(), candles, symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2, rng=random.Random(7),
        bypass_risk_engine=True,
    )
    assert report.passed is False
    assert report.failure_reasons


def _scenario_result(scenario_name: str, fee_mult: float, slip_mult: float, idx: int, net_return_pct: float) -> ScenarioResult:
    final_equity = 100.0 * (1 + net_return_pct)
    result = BacktestResult(
        equity_curve=[100.0, final_equity], trades=[], final_equity=final_equity, starting_equity=100.0
    )
    return ScenarioResult(scenario_name, fee_mult, slip_mult, idx, result)


def test_compute_robustness_score_is_zero_for_an_empty_report():
    assert compute_robustness_score(AdversarialReport()) == 0.0


def test_compute_robustness_score_penalizes_parameter_instability_even_with_a_fine_baseline():
    """Same worst-case drawdown/return in both reports — the only
    difference is how much return varies across perturb_dna_variants at
    the SAME scenario/cost combination. A strategy whose return swings
    wildly under small parameter jitter (the 'only works at exactly one
    parameter value' case) must score lower than one that doesn't, even
    though its baseline numbers look equally fine."""
    unstable_results = [
        _scenario_result("baseline", 1.0, 1.0, 0, 0.20),
        _scenario_result("baseline", 1.0, 1.0, 1, -0.15),
        _scenario_result("baseline", 1.0, 1.0, 2, 0.25),
        _scenario_result("baseline", 1.0, 1.0, 3, -0.20),
        _scenario_result("baseline", 1.0, 1.0, 4, 0.30),
    ]
    unstable_report = AdversarialReport(
        scenario_results=unstable_results, worst_case_max_drawdown_pct=0.05, worst_case_net_return_pct=0.05,
        passed=True, failure_reasons=[],
    )
    stable_results = [_scenario_result("baseline", 1.0, 1.0, i, 0.10) for i in range(5)]
    stable_report = AdversarialReport(
        scenario_results=stable_results, worst_case_max_drawdown_pct=0.05, worst_case_net_return_pct=0.10,
        passed=True, failure_reasons=[],
    )

    assert compute_robustness_score(unstable_report) < compute_robustness_score(stable_report)


def test_adversarial_suite_risk_gating_protects_even_an_overleveraged_strategy():
    """With the Risk Engine in the loop (the default, and the only mode any
    production caller may use), the same fragile DNA's proposed 20x
    leverage / 100% notional gets clamped down to the global limits before
    any entry is taken — so the stop-loss blowup this DNA was designed to
    trigger never actually happens. This is the Risk Engine's "final veto
    authority" working as intended, not a weaker test."""
    candles = _trending_candles(600)
    report = run_adversarial_suite(
        _fragile_dna(), candles, symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2, rng=random.Random(7),
    )
    assert report.passed is True
    assert report.worst_case_max_drawdown_pct < 0.40
