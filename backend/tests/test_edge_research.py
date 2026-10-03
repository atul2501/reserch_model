"""Edge-research framework: chronology, leakage, costs, objective gate (incl. POSITIVE and NEGATIVE controls),
registry duplicate detection, seeds, proposer, microstructure data integrity."""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd
import pytest

from app.edge_research import evaluate as ev
from app.edge_research.datasets import bar_dataset, load_bbo, microstructure_dataset, signal_dataset
from app.edge_research.experiments import ExperimentData, run_experiment
from app.edge_research.proposer import LIBRARY, propose
from app.edge_research.registry import ExperimentRegistry, ExperimentSpec
from app.edge_research.seeds import SEEDS, install_seeds
from app.edge_research.walkforward import assert_no_leakage, make_windows, split

DAY = 86_400_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % 60_000)


def synthetic(days=12, *, signal=0.0, drift=0.0, noise=10.0, seed=1, kind="bar"):
    rng = np.random.default_rng(seed)
    n = int(days * 1440)
    t = T0 + np.arange(n) * 60_000
    x = rng.standard_normal(n)
    df = pd.DataFrame({"t": t, "bar": t, "x": x, "z": rng.standard_normal(n)})
    df["ret_5"] = signal * x + drift + noise * rng.standard_normal(n)
    if kind == "directional":
        df["side"] = 1.0
    return df


def spec(**kw):
    base = dict(hypothesis="test", signal_source="synthetic", features=("x", "z"), target="fwd_return_bps", horizon_min=5,
                model="ridge", hyperparameters={"alpha": 1.0, "cost_margin_bps": 0.0})
    base.update(kw)
    return ExperimentSpec(**base)


# --------------------------------------------------------------------------- chronology / leakage
def test_windows_are_chronological_non_overlapping_with_embargo():
    w = make_windows(T0, T0 + 10 * DAY, oos_ms=DAY, val_ms=DAY, min_train_ms=2 * DAY, embargo_ms=3_600_000)
    assert len(w) >= 4
    for a in w:
        assert a.train[1] + 3_600_000 <= a.val[0] and a.val[1] + 3_600_000 <= a.oos[0]
    for a, b in zip(w, w[1:]):
        assert a.oos[1] <= b.oos[0]                      # OOS windows never overlap
        assert b.train[1] >= a.train[1]                  # expanding training


def test_split_purges_labels_that_would_leak_into_the_next_split():
    df = synthetic(days=6)
    w = make_windows(T0, T0 + 6 * DAY, oos_ms=DAY, val_ms=DAY, min_train_ms=2 * DAY, embargo_ms=3_600_000)[0]
    tr, va, oo = split(df, w, horizon_ms=5 * 60_000)
    assert_no_leakage(tr, va, oo, horizon_ms=5 * 60_000)
    assert (tr.t + 5 * 60_000).max() < va.t.min() and (va.t + 5 * 60_000).max() < oo.t.min()


def test_oos_data_never_influences_the_selection(tmp_path):
    """Corrupting ONLY the OOS rows' returns cannot change the selection level chosen for that window."""
    df = synthetic(days=8, signal=20.0, noise=5.0)
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    a = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "test"), reg, dry_run=True)
    w0 = a["windows"][0]
    oos = (df.t >= w0["oos"][0]) & (df.t < w0["oos"][1])
    df2 = df.copy(); df2.loc[oos, "ret_5"] = -df2.loc[oos, "ret_5"]           # flip OOS outcomes only
    b = run_experiment(spec(), ExperimentData(df2, "bar", 14.0, "test"), ExperimentRegistry(tmp_path / "r2.jsonl"), dry_run=True)
    assert b["windows"][0]["selection_frac"] == w0["selection_frac"]
    assert b["windows"][0]["validation_net_bps"] == pytest.approx(w0["validation_net_bps"])
    assert b["windows"][0]["net_expectancy_bps"] < 0 < w0["net_expectancy_bps"]


# --------------------------------------------------------------------------- costs
def test_net_equals_gross_minus_measured_cost():
    gross = np.array([20.0, -5.0, 10.0])
    m = ev.metrics(gross - 14.1, gross, np.arange(3) * 3_600_000 * 2, 14.1)
    assert m["net_expectancy_bps"] == pytest.approx(gross.mean() - 14.1)
    assert m["gross_expectancy_bps"] == pytest.approx(gross.mean()) and m["cost_per_trade_bps"] == 14.1


# --------------------------------------------------------------------------- the gate: positive & negative controls
def test_positive_control_a_real_edge_is_found(tmp_path):
    df = synthetic(days=12, signal=30.0, noise=10.0)
    out = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "test"), ExperimentRegistry(tmp_path / "r.jsonl"))
    assert out["status"] == "ROBUST OOS EDGE", out["reasons"]
    assert out["decision"] == "ACCEPTED_FOR_SHADOW" and out["oos_net_expectancy_bps"] > 0


def test_negative_control_pure_noise_is_not_an_edge(tmp_path):
    df = synthetic(days=12, signal=0.0, noise=10.0, seed=3)
    out = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "test"), ExperimentRegistry(tmp_path / "r.jsonl"))
    assert out["status"] in ("NO EDGE",) and out["decision"] in ("REJECTED", "OOS_FAILED")


def test_weak_edge_consumed_by_cost(tmp_path):
    df = synthetic(days=12, drift=5.0, noise=5.0, kind="directional")
    s = spec(model="rule", features=(), hyperparameters={})
    out = run_experiment(s, ExperimentData(df, "directional", 14.0, "test"), ExperimentRegistry(tmp_path / "r.jsonl"))
    assert out["status"] == "WEAK EDGE" and out["decision"] == "REJECTED"
    assert out["oos_gross_expectancy_bps"] > 0 > out["oos_net_expectancy_bps"]


def test_insufficient_data_is_never_a_rejection(tmp_path):
    df = synthetic(days=0.2, signal=0.0)
    out = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "test"), ExperimentRegistry(tmp_path / "r.jsonl"))
    assert out["decision"] == "NEEDS_MORE_DATA"


def test_classify_requires_every_robust_condition():
    w = [dict(trades=50, net_expectancy_bps=5.0, total_net_bps=250.0)] * 4
    pooled = dict(trades=200, independent_bars=400, net_expectancy_bps=5.0, net_ci95_low=1.0, p_one_sided_net=0.001,
                  profit_factor=1.5, gross_expectancy_bps=19.0, t_stat_gross=5.0, cost_per_trade_bps=14.0)
    assert ev.classify(w, pooled, n_tests=1, neighbours_positive=True, validation_net_bps=6)[0] == "ROBUST OOS EDGE"
    assert ev.classify(w, pooled, n_tests=1, neighbours_positive=False, validation_net_bps=6)[0] == "OOS POSITIVE"   # unstable
    assert ev.classify(w, pooled, n_tests=1000, neighbours_positive=True, validation_net_bps=6)[0] == "OOS POSITIVE"  # multiple testing
    assert ev.classify(w[:2], pooled, n_tests=1, neighbours_positive=True, validation_net_bps=6)[0] == "PROMISING"     # too few windows
    one = [dict(trades=50, net_expectancy_bps=5.0, total_net_bps=900.0)] + [dict(trades=50, net_expectancy_bps=1.0, total_net_bps=10.0)] * 3
    assert ev.classify(one, pooled, n_tests=1, neighbours_positive=True, validation_net_bps=6)[0] != "ROBUST OOS EDGE"  # one window carries it


def test_only_rule_and_ridge_models_are_allowed(tmp_path):
    with pytest.raises(ValueError, match="model shopping"):
        run_experiment(spec(model="xgboost"), ExperimentData(synthetic(days=1), "bar", 14.0, "t"), ExperimentRegistry(tmp_path / "r.jsonl"))


# --------------------------------------------------------------------------- registry
def test_exact_duplicate_is_refused_with_the_previous_result(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    df = synthetic(days=8, signal=0.0, seed=5)
    first = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "t"), reg)
    assert first["refused"] is False
    again = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "t"), reg)
    assert again["refused"] is True and again["duplicate_level"] == "EXACT"
    assert "already been tested" in again["message"] and first["experiment_id"] in again["message"]


def test_exact_replication_on_new_data_is_allowed(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    df = synthetic(days=8, signal=0.0, seed=5)
    run_experiment(spec(), ExperimentData(df, "bar", 14.0, "t"), reg)
    later = df.assign(t=df.t + 5 * DAY, bar=df.bar + 5 * DAY)
    out = run_experiment(spec(), ExperimentData(later, "bar", 14.0, "t"), reg)
    assert out["refused"] is False and out["duplicate_level"] == "EXACT_REPLICATION"


def test_material_retuning_of_a_failed_hypothesis_is_refused(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    df = synthetic(days=8, signal=0.0, seed=7)
    first = run_experiment(spec(), ExperimentData(df, "bar", 14.0, "t"), reg)
    assert first["decision"] in ("REJECTED", "OOS_FAILED")
    retuned = spec(horizon_min=5, hyperparameters={"alpha": 100.0, "cost_margin_bps": 2.0})
    out = run_experiment(retuned, ExperimentData(df, "bar", 14.0, "t"), reg)
    assert out["refused"] is True and out["duplicate_level"] == "MATERIAL" and "model shopping" in out["message"]
    later = df.assign(t=df.t + 5 * DAY, bar=df.bar + 5 * DAY)
    ok = run_experiment(retuned, ExperimentData(later, "bar", 14.0, "t"), reg, justification="new regime, new data")
    assert ok["refused"] is False and ok["duplicate_level"] == "MATERIAL_JUSTIFIED"


def test_needs_more_data_does_not_block_a_rerun_with_more_data(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    small = synthetic(days=0.3)
    assert run_experiment(spec(), ExperimentData(small, "bar", 14.0, "t"), reg)["decision"] == "NEEDS_MORE_DATA"
    bigger = synthetic(days=0.6)
    assert run_experiment(spec(), ExperimentData(bigger, "bar", 14.0, "t"), reg)["refused"] is False


def test_seeds_are_idempotent_and_block_repeating_prior_research(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    assert install_seeds(reg) == len(SEEDS) and install_seeds(reg) == 0
    prior = next(s for s in SEEDS if s["experiment_id"] == "SEED-HZN-traded-30")["spec"]
    chk = reg.check(prior, data_end_ms=1790958300000)
    assert not chk.allowed and "already been tested" in chk.message


def test_proposer_collects_data_before_running_and_skips_tested(tmp_path):
    reg = ExperimentRegistry(tmp_path / "r.jsonl")
    install_seeds(reg)
    p = propose(reg, data_days={"microstructure": 0.5, "candles_btc": 0.5})
    assert p["action"] == "COLLECT_DATA" and p["hypothesis"] == LIBRARY[0].key and "short" in p["why"]
    assert propose(reg, data_days={"microstructure": 30, "candles_btc": 30})["action"] == "RUN"


# --------------------------------------------------------------------------- datasets: no look-ahead
def test_bar_dataset_features_are_causal_and_horizons_exact():
    n = 400
    sol = pd.DataFrame({"open_time": T0 + np.arange(n) * 60_000, "close": 100 + np.cumsum(np.random.default_rng(0).normal(0, .1, n))})
    btc = sol.assign(close=sol.close * 600)
    full = bar_dataset(sol, btc)
    cut = bar_dataset(sol.iloc[:300], btc.iloc[:300])
    feats = [c for c in full.columns if not c.startswith("ret_") and c not in ("t", "bar")]
    pd.testing.assert_frame_equal(full.iloc[:300][feats].reset_index(drop=True), cut[feats].reset_index(drop=True))  # truncation-invariant
    assert full.ret_5.iloc[-5:].isna().all()                      # partial horizons are NULL, never estimated
    i = 100
    assert full.ret_5.iloc[i] == pytest.approx((sol.close.iloc[i + 5] / sol.close.iloc[i] - 1) * 1e4)


def test_signal_dataset_signs_returns_and_uses_next_open():
    c = pd.DataFrame({"open_time": T0 + np.arange(20) * 60_000, "open": np.arange(20) + 100.0, "close": np.arange(20) + 100.5})
    s = signal_dataset(pd.DataFrame({"bar": [T0 + 2 * 60_000, T0 + 2 * 60_000], "side": ["LONG", "SHORT"]}), c)
    up = (c.close[2 + 5] / c.open[3] - 1) * 1e4
    assert s.ret_5.tolist() == pytest.approx([up, -up])


def _write(root, coin, ch, rows, hour="2026100300"):
    d = root / hour[:8]; d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"{coin}_{ch}_{hour}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_microstructure_features_use_only_past_observations_and_tolerate_live_files(tmp_path):
    base = 1_791_000_000_000
    bbo = [{"recv_ms": base + i * 1000 + 200, "data": {"coin": "SOL", "time": base + i * 1000,
            "bbo": [{"px": str(100 + i * 0.01), "sz": "10", "n": 1}, {"px": str(100.02 + i * 0.01), "sz": "5", "n": 1}]}} for i in range(900)]
    _write(tmp_path, "SOL", "bbo", bbo)
    _write(tmp_path, "SOL", "trades", [{"recv_ms": base + i * 1000, "data": [{"coin": "SOL", "side": "B" if i % 3 else "A",
           "px": "100", "sz": "1", "time": base + i * 1000, "tid": i}]} for i in range(900)])
    d = microstructure_dataset(tmp_path, step_s=15, horizons_min=(1,))
    assert len(d) > 10 and (d.bbo_age_ms >= 0).all()                 # the bbo used is never from after t
    b = load_bbo(tmp_path, "SOL")
    for _, r in d.sample(5, random_state=0).iterrows():
        last = b[b.ts <= r.t].iloc[-1]
        assert r.mid == pytest.approx((last.bid + last.ask) / 2)
        fut = b[b.ts >= r.t + 60_000]
        assert (np.isnan(r.ret_1) and fut.empty) or r.ret_1 == pytest.approx(((fut.iloc[0].bid + fut.iloc[0].ask) / 2 / r.mid - 1) * 1e4)
    # a still-being-written gzip (no end marker) must not crash the reader
    raw = (tmp_path / "20261003"); raw.mkdir(exist_ok=True)
    full = gzip.compress(b"".join(json.dumps(x).encode() + b"\n" for x in bbo[:50]))
    (raw / "SOL_bbo_2026100301.jsonl.gz").write_bytes(full[:-12])
    assert len(load_bbo(tmp_path, "SOL")) >= 900


def test_collector_parses_channels_and_strips_identities(tmp_path):
    from scripts.collect_microstructure import HourlyWriter, handle_message
    w = HourlyWriter(tmp_path)
    assert handle_message(json.dumps({"channel": "trades", "data": [{"coin": "SOL", "side": "B", "px": "1", "sz": "2", "time": 5,
                                     "tid": 1, "hash": "0xabc", "users": ["0x1", "0x2"]}]}), w, 1_791_000_000_000)
    assert not handle_message(json.dumps({"channel": "subscriptionResponse", "data": {}}), w, 1)
    assert not handle_message("not json", w, 1)
    w.close()
    rows = [json.loads(l) for f in tmp_path.rglob("*.gz") for l in gzip.open(f, "rt")]
    assert rows and "users" not in rows[0]["data"][0] and "hash" not in rows[0]["data"][0] and rows[0]["recv_ms"] == 1_791_000_000_000
