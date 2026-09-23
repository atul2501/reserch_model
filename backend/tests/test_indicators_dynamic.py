"""Dynamic indicators (spec phase 5): the DNA's declared period is the period
actually computed; identical specs are computed once for the population."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.strategies import indicators as ind
from app.strategies.indicators import (
    IndicatorSpec, UnknownIndicatorError, compute_indicator_features, feature_keys_for, resolve_spec,
)


def _df(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    high, low = close + rng.uniform(0.05, 0.5, n), close - rng.uniform(0.05, 0.5, n)
    return pd.DataFrame({
        "open_time": np.arange(n) * 60_000 + 1_700_000_040_000, "open": close - 0.05, "high": high, "low": low,
        "close": close, "volume": rng.uniform(500, 1500, n), "open_interest": 1000 + np.arange(n),
    })


def test_ema_20_and_ema_50_are_different_series_matching_pandas():
    df = _df()
    cur, prev = compute_indicator_features(df, [resolve_spec("ema", {"period": 20}), resolve_spec("ema", {"period": 50})])
    assert set(cur) == {"ema_20", "ema_50"}
    assert cur["ema_20"] != cur["ema_50"]
    assert cur["ema_20"] == pytest.approx(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    assert cur["ema_50"] == pytest.approx(df["close"].ewm(span=50, adjust=False).mean().iloc[-1])
    assert prev["ema_20"] == pytest.approx(df["close"].ewm(span=20, adjust=False).mean().iloc[-2])


def test_rsi_periods_differ():
    df = _df()
    cur, _ = compute_indicator_features(df, [resolve_spec("rsi", {"period": 7}), resolve_spec("rsi", {"period": 21})])
    assert cur["rsi_7"] != cur["rsi_21"]


def test_defaults_are_filled_and_specs_canonicalised():
    assert resolve_spec("rsi", {}) == resolve_spec("RSI", {"period": 14})
    assert resolve_spec("bollinger", {"period": 20}).name == "bbands"
    assert "bb_pct_b_20" in feature_keys_for(resolve_spec("bbands", {}))
    assert "bb_upper_20" in feature_keys_for(resolve_spec("bbands", {}))            # default std=2 -> plain period tag
    assert "bb_upper_20_2.5" in feature_keys_for(resolve_spec("bbands", {"std": 2.5}))  # non-default std is part of the key


def test_unknown_indicator_and_bad_params_rejected():
    with pytest.raises(UnknownIndicatorError):
        resolve_spec("nonsense", {})
    with pytest.raises(UnknownIndicatorError):
        resolve_spec("ema", {"window": 5})
    with pytest.raises(UnknownIndicatorError):
        resolve_spec("ema", {"period": 100_000})


def test_each_distinct_spec_is_computed_once_for_the_population(monkeypatch):
    calls = []
    real = ind.compute_indicator

    def spy(df, spec):
        calls.append(spec)
        return real(df, spec)

    monkeypatch.setattr(ind, "compute_indicator", spy)
    specs = [resolve_spec("ema", {"period": 20})] * 250 + [resolve_spec("rsi", {"period": 14})] * 250
    compute_indicator_features(_df(), specs)
    assert len(calls) == 2  # 500 agents' worth of requests -> 2 computations


def test_no_lookahead_appending_future_bars_does_not_change_past_values():
    df = _df(300)
    spec = resolve_spec("rsi", {"period": 14})
    value_at_bar_249 = compute_indicator_features(df.iloc[:250], [spec])[0]["rsi_14"]
    # In a frame that also contains bar 250 (the "future"), the PREVIOUS value is bar 249's — unchanged.
    prev_in_longer_frame = compute_indicator_features(df.iloc[:251], [spec])[1]["rsi_14"]
    assert prev_in_longer_frame == pytest.approx(value_at_bar_249)


def test_donchian_uses_prior_bars_only():
    df = _df()
    cur, _ = compute_indicator_features(df, [resolve_spec("donchian", {"period": 20})])
    assert cur["donchian_high_20"] == pytest.approx(df["high"].iloc[-21:-1].max())  # excludes the current bar


def test_every_registered_indicator_produces_finite_features_on_normal_data():
    df = _df()
    for name in ind.known_indicator_names():
        cur, _ = compute_indicator_features(df, [resolve_spec(name, {})])
        assert cur, name
        assert all(np.isfinite(v) for v in cur.values()), name


def test_oi_change_is_neutral_not_invented_when_open_interest_missing():
    df = _df().drop(columns=["open_interest"])
    cur, _ = compute_indicator_features(df, [resolve_spec("oi_change", {"period": 10})])
    assert cur["oi_change_10"] == 0.0
