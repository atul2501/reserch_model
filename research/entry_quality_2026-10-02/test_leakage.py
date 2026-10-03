"""Phase 12 leakage tests for the research dataset (pytest)."""
import numpy as np
import pandas as pd
import pytest
from features import ext_features, v1_compute, FEATURE_REGISTRY, V1_COLS
from lib import D, load_trades

PROHIBITED = ("mfe", "mae", "exit", "pnl", "closed", "hold", "fwd", "quality", "left_on_table", "post_exit", "win",
              "planned_stop", "planned_tp", "risk_amount", "expected_r")


@pytest.fixture(scope="module")
def candles():
    c = pd.read_parquet(f"{D}/candles.parquet")
    return c[c.is_final].sort_values("open_time").reset_index(drop=True)


@pytest.fixture(scope="module")
def full(candles):
    return v1_compute(candles[["open_time", "open", "high", "low", "close", "volume"]]).merge(ext_features(candles), on="open_time")


def test_no_prohibited_feature_names():
    for name in FEATURE_REGISTRY:
        assert not any(p in name for p in PROHIBITED), name


def test_registry_has_as_of_for_every_feature():
    for name, (src, as_of, _) in FEATURE_REGISTRY.items():
        assert src and as_of.startswith("signal_bar_close"), name


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_truncation_invariance(candles, full, seed):
    """Features at bar i computed from candles[:i+1] must equal features at i from the full series."""
    rng = np.random.default_rng(seed)
    cols = [c for c in full.columns if c != "open_time"]
    for i in rng.integers(400, len(candles) - 1, size=15):
        sub = candles.iloc[: i + 1]
        tr = v1_compute(sub[["open_time", "open", "high", "low", "close", "volume"]]).merge(ext_features(sub), on="open_time")
        a, b = tr.iloc[-1][cols].astype(float), full.iloc[i][cols].astype(float)
        assert np.allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-12, equal_nan=True), (i, (a - b).abs().idxmax())


def test_future_perturbation_does_not_change_past(candles, full):
    pert = candles.copy()
    k = len(pert) // 2
    pert.loc[k + 1:, ["open", "high", "low", "close"]] *= 1.05
    pert.loc[k + 1:, "volume"] *= 3
    pf = v1_compute(pert[["open_time", "open", "high", "low", "close", "volume"]]).merge(ext_features(pert), on="open_time")
    cols = [c for c in full.columns if c != "open_time"]
    assert np.allclose(pf.iloc[: k + 1][cols].to_numpy(float), full.iloc[: k + 1][cols].to_numpy(float), equal_nan=True)


def test_dataset_feature_bar_is_signal_bar_and_before_fill():
    ds = pd.read_parquet(f"{D}/dataset.parquet")
    opened_ms = ds.opened_at.astype("int64") // 10**6
    assert (ds.signal_bar + 60_000 <= opened_ms).all()  # decision time <= fill time
    assert (ds.rg_bar <= ds.signal_bar).all()           # regime as-of
    assert (ds.regime == ds.regime_asof).all()


def test_family_recent_perf_uses_only_trades_closed_before_decision():
    ds = pd.read_parquet(f"{D}/dataset.parquet").dropna(subset=["fam_recent_exp_6h"]).sample(200, random_state=0)
    allt = load_trades()
    allt = allt[allt.family.notna() & ~allt.flag_stale_rollover]
    cms = allt.closed_at.astype("int64") // 10**6
    for _, r in ds.iterrows():
        m = (allt.family == r.family) & (cms < r.decision_ms) & (cms >= r.decision_ms - 6 * 3600_000)
        assert abs(allt[m].net_bps.mean() - r.fam_recent_exp_6h) < 1e-9
