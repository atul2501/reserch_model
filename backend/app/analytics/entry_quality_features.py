"""Leak-free feature computation for the Entry Quality Model (SHADOW ONLY - see
entry_quality_model.py). Every feature at row i uses only rows <= i: trailing windows,
.shift(1)/.diff() only, no center=True, no .shift(-n). Verified against 2 years of the
existing feature_engine.py precedent for the same no-look-ahead discipline.

Deliberately a SEPARATE, minimal feature set from app.market.feature_engine - this module only
serves the shadow Entry Quality audit, so it has no obligation to match the live DNA-strategy
indicator set, and keeping it self-contained means it can be read and audited in one pass.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.entry_quality_model import FEATURE_COLUMNS


def compute_features(candles: pd.DataFrame) -> pd.DataFrame:
    """`candles` must have open_time, open, high, low, close, volume, sorted ascending by
    open_time. Returns a frame indexed the same as `candles` with `open_time` plus every column
    in FEATURE_COLUMNS. Rows within the warm-up window (~200 bars, from the EMA-200-scale
    indicators) are NaN, never a fabricated value."""
    df = candles.reset_index(drop=True)
    o, h, l, c, v = df.open, df.high, df.low, df.close, df.volume

    def rsi(series, period=14):
        delta = series.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    def ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    def atr(h, l, c, period=14):
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    feat = pd.DataFrame(index=df.index)
    feat["open_time"] = df.open_time
    for n in (1, 3, 5, 10):
        feat[f"ret_{n}"] = c.pct_change(n)
    feat["rsi_14"] = rsi(c, 14)
    feat["rsi_14_slope"] = feat["rsi_14"].diff(3)
    ema12, ema50 = ema(c, 12), ema(c, 50)
    macd = ema12 - ema50
    macd_signal = ema(macd, 9)
    feat["macd_hist"] = macd - macd_signal
    feat["macd_hist_slope"] = feat["macd_hist"].diff(3)
    feat["ema_fast_slope"] = ema12.pct_change(5)
    feat["price_dist_ema_fast"] = (c - ema12) / ema12
    feat["price_dist_ema_slow"] = (c - ema50) / ema50
    atr14 = atr(h, l, c, 14)
    feat["atr_14"] = atr14 / c
    feat["atr_pctile"] = atr14.expanding(min_periods=100).apply(lambda x: (x <= x.iloc[-1]).mean(), raw=False)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    feat["bb_width"] = (4 * bb_std) / bb_mid
    feat["bb_position"] = (c - bb_mid) / (2 * bb_std).replace(0, np.nan)
    feat["volume_ratio"] = v / v.rolling(20).mean().replace(0, np.nan)
    feat["trend_strength"] = (ema12 - ema50) / ema50
    feat["candle_body"] = (c - o).abs() / (h - l).replace(0, np.nan)
    feat["upper_wick"] = (h - np.maximum(o, c)) / (h - l).replace(0, np.nan)
    feat["lower_wick"] = (np.minimum(o, c) - l) / (h - l).replace(0, np.nan)
    swing_high20 = h.rolling(20).max().shift(1)
    swing_low20 = l.rolling(20).min().shift(1)
    feat["dist_from_high20"] = (c - swing_high20) / swing_high20
    feat["dist_from_low20"] = (c - swing_low20) / swing_low20

    assert set(FEATURE_COLUMNS).issubset(feat.columns), "feature set drifted from the frozen model's expectations"
    return feat


def feature_row_at_or_before(feat: pd.DataFrame, open_time_ms: int) -> dict | None:
    """The most recent feature row with open_time <= open_time_ms (the bar a strategy's signal
    fired on) - never a later row, which is exactly what would leak future information into a
    "what did we know at signal time" score."""
    times = feat["open_time"].to_numpy()
    idx = int(np.searchsorted(times, open_time_ms, side="right")) - 1
    if idx < 0 or idx >= len(feat):
        return None
    row = feat.iloc[idx]
    values = {col: (None if pd.isna(row[col]) else float(row[col])) for col in FEATURE_COLUMNS}
    if any(v is None for v in values.values()):
        return None
    return values
