"""Adversarial/stress testing harness: candle distortions, DNA parameter
perturbation, and the aggregate pass/fail suite (spec sections 22-25)."""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from app.backtesting.adversarial import (
    inject_extreme_move,
    inject_gap,
    inject_stale_period,
    inject_volatility_spike,
    perturb_dna_variants,
    run_adversarial_suite,
)
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


def test_perturb_dna_variants_produces_distinct_valid_variants():
    dna = _never_trades_dna()  # default-range stop_loss.value, unlike _fragile_dna's out-of-range fixed_pct value
    variants = perturb_dna_variants(dna, 5, rng=random.Random(1))
    assert len(variants) == 5
    assert all(isinstance(v, StrategyDNA) for v in variants)
    values = {v.stop_loss.value for v in variants}
    assert len(values) > 1  # jittering actually varies the parameter


def test_adversarial_suite_passes_for_a_strategy_that_never_trades():
    candles = _trending_candles(600)
    report = run_adversarial_suite(
        _never_trades_dna(), candles, symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2, rng=random.Random(7),
    )
    assert report.passed is True
    assert report.worst_case_net_return_pct == pytest.approx(0.0)


def test_adversarial_suite_fails_for_an_overleveraged_unprotected_strategy():
    candles = _trending_candles(600)
    report = run_adversarial_suite(
        _fragile_dna(), candles, symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2, n_dna_variants=2, rng=random.Random(7),
    )
    assert report.passed is False
    assert report.failure_reasons
