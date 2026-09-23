"""Dynamic indicator registry + shared per-candle feature computation.

A StrategyDNA declares the indicators it uses, e.g.
    {"name": "ema", "params": {"period": 20}}   ->  feature key `ema_20`
    {"name": "rsi", "params": {"period": 7}}    ->  feature key `rsi_7`
so two agents with EMA(20) and EMA(50) genuinely read two different series.
DNA rules then reference those keys (`{"feature": "ema_20", ...}`).

Efficiency: the union of every distinct (name, resolved params) across the
whole population is computed ONCE per candle by `compute_indicator_features`
(500 agents sharing 30 distinct specs = 30 computations, not 500). Each
indicator returns the last TWO values of every output so `crosses_above` /
`crosses_below` conditions work on dynamic features without a previous
MarketContext.

Everything here is deterministic, uses only candles[0..t] (no look-ahead) and
has no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

import numpy as np
import pandas as pd

# feature_key -> full series (index-aligned with the input frame)
IndicatorSeries = dict[str, pd.Series]
# feature_key -> (current, previous) at the last bar
IndicatorOutput = dict[str, tuple[float, float]]


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    params: tuple[tuple[str, float | int | str], ...]

    def as_dict(self) -> dict[str, float | int | str]:
        return dict(self.params)


class UnknownIndicatorError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Primitive series
# --------------------------------------------------------------------------- #
def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(window=period).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    return _true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def _last2(series: pd.Series) -> tuple[float, float]:
    """(current, previous) as floats; NaN when unavailable."""
    cur = float(series.iloc[-1]) if len(series) >= 1 else math.nan
    prev = float(series.iloc[-2]) if len(series) >= 2 else math.nan
    return cur, prev


def _pack(key: str, series: pd.Series, out: IndicatorSeries) -> None:
    out[key] = series


# --------------------------------------------------------------------------- #
# Indicator implementations: fn(df, **resolved_params) -> IndicatorOutput
# --------------------------------------------------------------------------- #
def _ind_ema(df, period):
    out: IndicatorSeries = {}
    _pack(f"ema_{period}", _ema(df["close"], period), out)
    return out


def _ind_sma(df, period):
    out: IndicatorSeries = {}
    _pack(f"sma_{period}", _sma(df["close"], period), out)
    return out


def _ind_rsi(df, period):
    out: IndicatorSeries = {}
    _pack(f"rsi_{period}", _rsi(df["close"], period), out)
    return out


def _ind_roc(df, period):
    out: IndicatorSeries = {}
    _pack(f"roc_{period}", df["close"].pct_change(period) * 100, out)
    return out


def _ind_atr(df, period):
    atr = _atr(df, period)
    out: IndicatorSeries = {}
    _pack(f"atr_{period}", atr, out)
    _pack(f"atr_pct_{period}", atr / df["close"], out)
    return out


def _ind_bbands(df, period, std):
    close = df["close"]
    mid = _sma(close, period)
    sd = close.rolling(period).std()
    upper, lower = mid + std * sd, mid - std * sd
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    tag = f"{period}" if float(std) == 2.0 else f"{period}_{std:g}"
    out: IndicatorSeries = {}
    for name, ser in (("upper", upper), ("middle", mid), ("lower", lower), ("width", width), ("pct_b", pct_b)):
        _pack(f"bb_{name}_{tag}", ser, out)
    return out


def _ind_macd(df, fast, slow, signal):
    macd = _ema(df["close"], fast) - _ema(df["close"], slow)
    sig = _ema(macd, signal)
    tag = f"{fast}_{slow}_{signal}"
    out: IndicatorSeries = {}
    _pack(f"macd_{tag}", macd, out)
    _pack(f"macd_signal_{tag}", sig, out)
    _pack(f"macd_hist_{tag}", macd - sig, out)
    return out


def _ind_donchian(df, period):
    # Channel of the PRIOR `period` bars (shifted) so "close > donchian_high"
    # is a genuine breakout of already-known levels, never self-referential.
    hi = df["high"].rolling(period).max().shift(1)
    lo = df["low"].rolling(period).min().shift(1)
    out: IndicatorSeries = {}
    _pack(f"donchian_high_{period}", hi, out)
    _pack(f"donchian_low_{period}", lo, out)
    return out


def _ind_stoch(df, period):
    lo, hi = df["low"].rolling(period).min(), df["high"].rolling(period).max()
    k = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    out: IndicatorSeries = {}
    _pack(f"stoch_k_{period}", k.fillna(50.0), out)
    return out


def _ind_zscore(df, period):
    close = df["close"]
    z = (close - close.rolling(period).mean()) / close.rolling(period).std().replace(0, np.nan)
    out: IndicatorSeries = {}
    _pack(f"zscore_{period}", z.fillna(0.0), out)
    return out


def _ind_vwap(df, period):
    typical = (df["high"] + df["low"] + df["close"]) / 3
    if period == 0:  # session VWAP anchored at 00:00 UTC of the latest bar's day
        day = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.floor("D")
        pv = (typical * df["volume"]).groupby(day).cumsum()
        vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
        vwap, key = pv / vv, "vwap_session"
    else:
        pv = (typical * df["volume"]).rolling(period).sum()
        vv = df["volume"].rolling(period).sum().replace(0, np.nan)
        vwap, key = pv / vv, f"vwap_{period}"
    out: IndicatorSeries = {}
    _pack(key, vwap, out)
    _pack(key.replace("vwap", "vwap_dev", 1), df["close"] / vwap - 1, out)
    return out


def _ind_volume_ratio(df, period):
    out: IndicatorSeries = {}
    _pack(f"volume_ratio_{period}", df["volume"] / df["volume"].rolling(period).mean().replace(0, np.nan), out)
    return out


def _ind_realized_vol(df, period):
    out: IndicatorSeries = {}
    _pack(f"realized_vol_{period}", df["close"].pct_change().rolling(period).std() * math.sqrt(1440), out)
    return out


def _ind_adx(df, period):
    up, down = df["high"].diff(), -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr = _atr(df, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out: IndicatorSeries = {}
    _pack(f"adx_{period}", dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0), out)
    _pack(f"plus_di_{period}", plus_di.fillna(0.0), out)
    _pack(f"minus_di_{period}", minus_di.fillna(0.0), out)
    return out


def _ind_flow_imbalance(df, period):
    """Order-flow PROXY from bars (no tape data): volume-weighted candle
    direction over `period` bars in [-1, 1]. Documented as a proxy."""
    signed = np.sign(df["close"] - df["open"]) * df["volume"]
    out: IndicatorSeries = {}
    _pack(
        f"flow_imbalance_{period}",
        (signed.rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, np.nan)).fillna(0.0),
        out,
    )
    return out


def _ind_oi_change(df, period):
    out: IndicatorSeries = {}
    if "open_interest" in df and df["open_interest"].notna().sum() >= 2:
        oi = df["open_interest"].ffill()
        _pack(f"oi_change_{period}", oi.pct_change(period) * 100, out)
    else:
        out[f"oi_change_{period}"] = pd.Series(0.0, index=df.index)  # OI unavailable -> neutral, never invented
    return out


def _ind_range_pct(df, period):
    out: IndicatorSeries = {}
    _pack(
        f"range_pct_{period}",
        (df["high"].rolling(period).max() - df["low"].rolling(period).min()) / df["close"],
        out,
    )
    return out


def _ind_swing(df, period):
    """Rolling structure levels of the prior `period` bars (alias of a
    channel, named for market-structure strategies)."""
    out: IndicatorSeries = {}
    _pack(f"swing_high_{period}", df["high"].rolling(period).max().shift(1), out)
    _pack(f"swing_low_{period}", df["low"].rolling(period).min().shift(1), out)
    return out


# name -> (fn, {param: default}, min_period_param or None)
_REGISTRY: dict[str, tuple[Callable[..., IndicatorOutput], dict[str, float | int]]] = {
    "ema": (_ind_ema, {"period": 20}),
    "sma": (_ind_sma, {"period": 20}),
    "rsi": (_ind_rsi, {"period": 14}),
    "roc": (_ind_roc, {"period": 10}),
    "atr": (_ind_atr, {"period": 14}),
    "bbands": (_ind_bbands, {"period": 20, "std": 2.0}),
    "macd": (_ind_macd, {"fast": 12, "slow": 26, "signal": 9}),
    "donchian": (_ind_donchian, {"period": 20}),
    "stoch": (_ind_stoch, {"period": 14}),
    "zscore": (_ind_zscore, {"period": 20}),
    "vwap": (_ind_vwap, {"period": 0}),  # 0 = session-anchored
    "volume_ratio": (_ind_volume_ratio, {"period": 20}),
    "realized_vol": (_ind_realized_vol, {"period": 20}),
    "adx": (_ind_adx, {"period": 14}),
    "flow_imbalance": (_ind_flow_imbalance, {"period": 10}),
    "oi_change": (_ind_oi_change, {"period": 10}),
    "range_pct": (_ind_range_pct, {"period": 20}),
    "swing": (_ind_swing, {"period": 20}),
}

# Aliases the legacy factory/LLM DNA may use.
_ALIASES = {"bollinger": "bbands", "bb": "bbands", "stochastic": "stoch"}

MAX_PERIOD = 250  # bounded by the 300-bar frame the worker supplies


def known_indicator_names() -> list[str]:
    return sorted(_REGISTRY)


def resolve_spec(name: str, params: dict | None = None) -> IndicatorSpec:
    """Canonicalises (name, params): alias resolution, defaults filled, unknown
    parameters rejected, periods bounded. Deterministic ordering => stable keys."""
    canonical = _ALIASES.get(name.lower(), name.lower())
    if canonical not in _REGISTRY:
        raise UnknownIndicatorError(f"unknown indicator {name!r}; known: {known_indicator_names()}")
    _, defaults = _REGISTRY[canonical]
    params = dict(params or {})
    unknown = set(params) - set(defaults)
    if unknown:
        raise UnknownIndicatorError(f"indicator {canonical!r} has no parameter(s) {sorted(unknown)}")
    resolved: dict[str, float | int] = {}
    for key, default in defaults.items():
        value = params.get(key, default)
        if isinstance(default, int) and not isinstance(default, bool):
            value = int(value)
            if value < 0 or value > MAX_PERIOD:
                raise UnknownIndicatorError(f"{canonical}.{key}={value} out of range [0, {MAX_PERIOD}]")
        else:
            value = float(value)
        resolved[key] = value
    return IndicatorSpec(canonical, tuple(sorted(resolved.items())))


def compute_indicator_series(df: pd.DataFrame, spec: IndicatorSpec) -> IndicatorSeries:
    """Full per-bar series of every output (used by the backtester, which
    computes each distinct spec ONCE per dataset for the whole population)."""
    fn, _ = _REGISTRY[spec.name]
    return fn(df, **spec.as_dict())


def compute_indicator(df: pd.DataFrame, spec: IndicatorSpec) -> IndicatorOutput:
    return {key: _last2(series) for key, series in compute_indicator_series(df, spec).items()}


def compute_indicator_features(
    df: pd.DataFrame, specs: set[IndicatorSpec] | list[IndicatorSpec]
) -> tuple[dict[str, float], dict[str, float]]:
    """Computes each distinct spec once. Returns (current, previous) flat
    feature dicts; NaN outputs are omitted (a missing feature makes a rule
    False and is reported by the engine, never silently coerced to 0)."""
    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    for spec in set(specs):
        for key, (cur, prev) in compute_indicator(df, spec).items():
            if not math.isnan(cur):
                current[key] = cur
            if not math.isnan(prev):
                previous[key] = prev
    return current, previous


@lru_cache(maxsize=4096)
def _feature_keys_cached(spec: IndicatorSpec) -> tuple[str, ...]:
    probe = pd.DataFrame(
        {
            "open_time": np.arange(1, 6) * 60_000,
            "open": np.ones(5), "high": np.ones(5) * 1.1, "low": np.ones(5) * 0.9,
            "close": np.ones(5), "volume": np.ones(5), "open_interest": np.ones(5),
        }
    )
    return tuple(compute_indicator_series(probe, spec).keys())


def feature_keys_for(spec: IndicatorSpec) -> list[str]:
    """Feature keys a spec produces (used to validate DNA rules against DNA indicators)."""
    return list(_feature_keys_cached(spec))
