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
    assert seen["config"].max_acceptable_drawdown == 0.33 and seen["config"].min_acceptable_worst_case_return == -0.11
    assert seen["cost_multipliers"] == [(1.0, 1.0), (4.0, 6.0)]


# --- reproducibility / provenance / funding / configuration (spec phase 22) ---------------------------------


def _fingerprint(report):
    return [(r.scenario_name, r.fee_multiplier, r.dna_variant_index, round(r.result.net_return_pct, 12), len(r.result.trades))
            for r in report.scenario_results]


def test_same_seed_reproduces_the_report_exactly_and_a_different_seed_changes_it():
    c = candles(520, seed=2)
    a = suite(ema_cross_dna(5, 20), c, seed=11)
    b = suite(ema_cross_dna(5, 20), c, seed=11)
    other = suite(ema_cross_dna(5, 20), c, seed=12)
    assert a.seed == 11 and _fingerprint(a) == _fingerprint(b)
    assert a.scenario_config == b.scenario_config
    assert _fingerprint(a) != _fingerprint(other)          # the DNA perturbations / dropped candles depend on the seed


def test_scenario_parameters_come_from_configuration_and_are_recorded():
    c = candles(520, seed=2)
    cfg = adv.AdversarialConfig(gap_pct=-0.12, execution_delay_bars=5, partial_fill_fraction=0.25, reject_probability=0.5)
    r = suite(ema_cross_dna(5, 20), c, seed=1, config=cfg)
    names = {x.scenario_name for x in r.scenario_results}
    assert {"gap_down_12pct", "delayed_execution_5bars", "partial_fills_25pct", "rejected_or_unknown_orders_50pct"} <= names
    assert r.scenario_config["gap_pct"] == -0.12 and "scenarios" in r.scenario_config and r.scenario_config["risk_engine_enforced"]


def test_settings_drive_the_config_including_the_formerly_dead_knobs(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "adversarial_partial_fill_fraction", 0.4)
    monkeypatch.setattr(s, "adversarial_execution_delay_bars", 7)
    cfg = adv.AdversarialConfig.from_settings(s)
    assert cfg.partial_fill_fraction == 0.4 and cfg.execution_delay_bars == 7


def test_funding_is_part_of_the_adversarial_scenarios():
    c = candles(520, seed=2)
    t0 = int(c["open_time"].iloc[0])
    funding = [(t0 + h * 1_800_000, 0.002) for h in range(1, 40)]
    with_f = suite(ema_cross_dna(5, 20), c, seed=1, funding=funding)
    without = suite(ema_cross_dna(5, 20), c, seed=1)
    assert sum(r.result.total_funding for r in with_f.scenario_results) != 0.0
    assert sum(r.result.total_funding for r in without.scenario_results) == 0.0
    assert with_f.scenario_config["funding_events"] == len(funding)


def test_robustness_normalisers_follow_the_report_limits_not_module_constants():
    from app.backtesting.adversarial import AdversarialReport, ScenarioResult
    from app.backtesting.engine import BacktestResult

    res = BacktestResult(equity_curve=[100.0, 90.0], trades=[object()], final_equity=90.0, starting_equity=100.0)
    rep = AdversarialReport(scenario_results=[ScenarioResult("x", 1, 1, 0, res)], scenario_config={"k": 1},
                            worst_case_max_drawdown_pct=0.10, worst_case_net_return_pct=-0.10, total_trades=1)
    lenient = adv.compute_robustness_score(AdversarialReport(**{**rep.__dict__, "max_drawdown_limit": 0.9, "min_return_limit": -0.9}))
    strict = adv.compute_robustness_score(AdversarialReport(**{**rep.__dict__, "max_drawdown_limit": 0.12, "min_return_limit": -0.11}))
    assert lenient > strict


async def test_service_persists_full_provenance_and_is_reproducible(db_session):
    from app.evolution import adversarial_service as svc
    from app.models.adversarial import AdversarialTestReport
    from tests.helpers_agents import make_agents
    from sqlalchemy import select

    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    kw = dict(symbol="SOL", timeframe="1m", starting_equity=100.0, base_fee_rate=0.00045, base_slippage_bps=2.0,
              n_dna_variants=1)
    c = candles(520, seed=3)
    r1 = await svc.run_and_persist_adversarial_suite(db_session, agent.strategy_version_id, c, experiment_id="EXP-1", **kw)
    r2 = await svc.run_and_persist_adversarial_suite(db_session, agent.strategy_version_id, c, experiment_id="EXP-2", **kw)
    await db_session.commit()
    assert r1.experiment_id == "EXP-1" and r1.random_seed is not None and len(r1.dataset_fingerprint) == 64
    assert r1.code_version and r1.scenario_config["scenarios"] and r1.scenario_config["gap_pct"] == -0.08
    # same (version, dataset, research seed) => same seed => identical result
    assert r1.random_seed == r2.random_seed and r1.worst_case_net_return_pct == r2.worst_case_net_return_pct
    assert r1.scenario_breakdown == r2.scenario_breakdown
    rows = (await db_session.execute(select(AdversarialTestReport))).scalars().all()
    assert len(rows) == 2
