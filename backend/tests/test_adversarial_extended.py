"""Adversarial testing v2 (spec phase 28): execution-fault scenarios, configured
thresholds, failures recorded not swallowed."""
from __future__ import annotations

import random

import pytest

from app.backtesting import adversarial as adv
from app.backtesting.adversarial import (
    drop_random_candles, duplicate_random_candles, run_adversarial_suite,
)
from tests.test_backtest_parity import candles, ema_cross_dna


def suite(dna, c, **kw):
    return run_adversarial_suite(dna, c, symbol="SOL", timeframe="1m", starting_equity=100.0, base_fee_rate=0.00045,
                                 base_slippage_bps=2, n_dna_variants=1, rng=random.Random(3), **kw)


def test_new_frame_transforms():
    c = candles(500, seed=1)
    assert len(drop_random_candles(c, 0.05, seed=1)) == 475
    assert len(duplicate_random_candles(c, 0.05, seed=1)) == 525
    assert drop_random_candles(c, 0.05, seed=1)["open_time"].is_monotonic_increasing


def test_suite_covers_market_cost_and_execution_fault_scenarios():
    r = suite(ema_cross_dna(5, 20), candles(520, seed=2))
    names = {s.scenario_name for s in r.scenario_results}
    assert {"baseline", "volatility_spike", "gap_down_8pct", "stale_period_20", "extreme_move_down_25pct",
            "missing_candles_2pct", "duplicate_candles_2pct", "delayed_execution_3bars", "partial_fills_50pct",
            "rejected_or_unknown_orders_30pct", "abnormal_volume_spike_5x", "liquidity_reduction"} <= names
    costs = {(s.fee_multiplier, s.slippage_multiplier) for s in r.scenario_results}
    assert (1.0, 1.0) in costs and (2.0, 3.0) in costs                 # normal and high fee/slippage
    assert len({s.dna_variant_index for s in r.scenario_results}) == 2  # base + perturbed parameters


def test_unexpected_scenario_errors_are_recorded_as_failures_not_swallowed(monkeypatch):
    real = adv.run_backtest
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if kw.get("execution_delay_bars"):
            raise RuntimeError("engine exploded under delayed execution")
        return real(*a, **kw)

    monkeypatch.setattr(adv, "run_backtest", flaky)
    r = suite(ema_cross_dna(5, 20), candles(520, seed=2))
    assert r.scenario_errors and "delayed_execution_3bars" in r.scenario_errors[0]
    assert r.passed is False and any("raised errors" in x for x in r.failure_reasons)


def test_thresholds_are_configurable():
    c = candles(520, seed=2)
    lenient = suite(ema_cross_dna(5, 20), c, max_acceptable_drawdown=0.99, min_acceptable_worst_case_return=-0.99)
    strict = suite(ema_cross_dna(5, 20), c, max_acceptable_drawdown=0.0001, min_acceptable_worst_case_return=0.5)
    assert lenient.passed and not strict.passed
    assert any("worst_case_max_drawdown" in x for x in strict.failure_reasons)


async def test_service_passes_the_configured_thresholds_and_cost_stress_to_the_suite(monkeypatch, db_session):
    from app.core.config import get_settings
    from app.evolution import adversarial_service as svc
    from tests.helpers_agents import make_agents
    seen = {}

    def fake_suite(dna, candles, **kw):
        seen.update(kw)
        return adv.AdversarialReport(passed=True, worst_case_max_drawdown_pct=0.1, worst_case_net_return_pct=0.0)

    monkeypatch.setattr(svc, "run_adversarial_suite", fake_suite)
    s = get_settings()
    monkeypatch.setattr(s, "adversarial_max_acceptable_drawdown", 0.33)
    monkeypatch.setattr(s, "adversarial_min_acceptable_worst_case_return", -0.11)
    monkeypatch.setattr(s, "adversarial_fee_stress_multiplier", 4.0)
    monkeypatch.setattr(s, "adversarial_slippage_stress_multiplier", 6.0)
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    await svc.run_and_persist_adversarial_suite(
        db_session, agent.strategy_version_id, candles(300), symbol="SOL", timeframe="1m", starting_equity=100.0,
        base_fee_rate=0.00045, base_slippage_bps=2.0,
    )
    assert seen["max_acceptable_drawdown"] == 0.33 and seen["min_acceptable_worst_case_return"] == -0.11
    assert seen["cost_multipliers"] == [(1.0, 1.0), (4.0, 6.0)]
