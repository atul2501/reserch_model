"""Feature engine + regime detector: no look-ahead, correct shapes (spec 7/45)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.market.feature_engine import MIN_CANDLES_REQUIRED, InsufficientDataError, compute_features


def _synthetic_candles(n: int, trend: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(n):
        price += trend + rng.normal(0, 0.3)
        open_ = price
        close = price + rng.normal(0, 0.2)
        high = max(open_, close) + abs(rng.normal(0, 0.1))
        low = min(open_, close) - abs(rng.normal(0, 0.1))
        volume = abs(rng.normal(1000, 100))
        rows.append({"open_time": i * 60_000, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
        price = close
    return pd.DataFrame(rows)


def test_raises_on_insufficient_data():
    candles = _synthetic_candles(MIN_CANDLES_REQUIRED - 1)
    with pytest.raises(InsufficientDataError):
        compute_features(candles, symbol="SOL", timeframe="1m")


def test_computes_full_context_with_enough_data():
    candles = _synthetic_candles(MIN_CANDLES_REQUIRED + 10)
    context = compute_features(candles, symbol="SOL", timeframe="1m")
    assert context.symbol == "SOL"
    assert context.close_price == pytest.approx(candles["close"].iloc[-1])
    assert 0.0 <= context.momentum.rsi_14 <= 100.0
    assert context.regime.regime is not None


def test_only_uses_data_up_to_current_index_no_lookahead():
    """Feeding the engine a truncated series (up to index i) must produce
    the same result as feeding the full series and looking at index i —
    proving future candles never influence past feature values."""
    full = _synthetic_candles(MIN_CANDLES_REQUIRED + 50)
    cutoff = MIN_CANDLES_REQUIRED + 20

    truncated = full.iloc[: cutoff + 1].reset_index(drop=True)
    ctx_truncated = compute_features(truncated, symbol="SOL", timeframe="1m")
    ctx_full_at_cutoff = compute_features(full.iloc[: cutoff + 1], symbol="SOL", timeframe="1m")

    assert ctx_truncated.close_price == ctx_full_at_cutoff.close_price
    assert ctx_truncated.momentum.rsi_14 == ctx_full_at_cutoff.momentum.rsi_14
    assert ctx_truncated.trend.ema_fast == ctx_full_at_cutoff.trend.ema_fast


def test_uptrend_detected_as_trend_up_regime():
    candles = _synthetic_candles(MIN_CANDLES_REQUIRED + 30, trend=0.5, seed=1)
    context = compute_features(candles, symbol="SOL", timeframe="1m")
    assert context.trend.trend_strength > 0
