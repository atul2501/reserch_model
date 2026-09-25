"""Deterministic feature engine (spec section 7).

Takes a rolling window of closed candles (oldest -> newest, the *last* row
being the candle just closed) and computes the full MarketContext. This
module contains no look-ahead: every computation for candle[t] uses only
candles[0..t].

Called exactly once per closed candle by the market-data pipeline; the
resulting MarketContext is fanned out to the council and all agents rather
than recomputed per-agent (spec section 4/6).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.models.enums import MarketRegime
from app.schemas.market_context import (
    MarketContext,
    MomentumFeatures,
    PriceActionFeatures,
    RegimeState,
    StructureFeatures,
    TrendFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)

MIN_CANDLES_REQUIRED = 210  # enough for a 200-period SMA/EMA plus warmup
# The trailing window of confirmed candles fed to `compute_features` for ONE decision. The live worker, the backtest
# (`app.backtesting.data`) and walk-forward all use this single constant: EMA seeding, rank-based volatility
# percentiles and the window VWAP depend on the window length, so a different length in any path would make the
# same DNA see different features on the same candles.
FEATURE_WINDOW = 300

_TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


class InsufficientDataError(ValueError):
    pass


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = _sma(close, period)
    std = close.rolling(window=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def _vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical = (high + low + close) / 3
    cum_vol = volume.cumsum().replace(0, np.nan)
    return (typical * volume).cumsum() / cum_vol


def _swing_points(high: pd.Series, low: pd.Series, window: int = 5) -> tuple[float | None, float | None, bool, bool, bool, bool]:
    """Fractal swing detection: a swing high (low) is a bar whose high (low) is the extreme of the `window` bars on
    EACH side. It is therefore only CONFIRMED `window` bars later, so the newest `window` bars are never a swing
    (no look-ahead) and every confirmed bar in the frame is scanned. HH/HL/LH/LL compare the last two confirmed
    swings of the same kind; `last_swing_*` is the most recent confirmed one."""
    n = len(high)
    if n < window * 2 + 1:
        return None, None, False, False, False, False

    span = window * 2 + 1
    high_v, low_v = high.to_numpy(), low.to_numpy()
    # Centered rolling extreme is NaN within `window` bars of either edge, so those bars compare False.
    swing_highs = high_v[high_v == high.rolling(span, center=True).max().to_numpy()]
    swing_lows = low_v[low_v == low.rolling(span, center=True).min().to_numpy()]

    last_swing_high = float(swing_highs[-1]) if len(swing_highs) else None
    last_swing_low = float(swing_lows[-1]) if len(swing_lows) else None

    higher_high = lower_high = higher_low = lower_low = False
    if len(swing_highs) >= 2:
        higher_high = bool(swing_highs[-1] > swing_highs[-2])
        lower_high = bool(swing_highs[-1] < swing_highs[-2])
    if len(swing_lows) >= 2:
        higher_low = bool(swing_lows[-1] > swing_lows[-2])
        lower_low = bool(swing_lows[-1] < swing_lows[-2])

    return last_swing_high, last_swing_low, higher_high, lower_high, higher_low, lower_low


def compute_features(candles: pd.DataFrame, symbol: str, timeframe: str) -> MarketContext:
    """`candles` must have columns: open_time, open, high, low, close,
    volume — sorted ascending by open_time, with the last row being the
    candle just closed. Raises InsufficientDataError if too short."""
    required_cols = {"open_time", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(candles.columns)
    if missing:
        raise ValueError(f"candles frame missing columns: {missing}")
    if len(candles) < MIN_CANDLES_REQUIRED:
        raise InsufficientDataError(
            f"need at least {MIN_CANDLES_REQUIRED} candles, got {len(candles)}"
        )

    df = candles.reset_index(drop=True)
    close, high, low, open_ = df["close"], df["high"], df["low"], df["open"]
    volume = df["volume"]

    ema_fast, ema_slow = _ema(close, 12), _ema(close, 50)
    sma_fast, sma_slow = _sma(close, 20), _sma(close, 200)
    ema_slope = float(ema_fast.iloc[-1] - ema_fast.iloc[-5]) if len(ema_fast) >= 5 else 0.0
    trend_strength = float((ema_fast.iloc[-1] - ema_slow.iloc[-1]) / ema_slow.iloc[-1]) if ema_slow.iloc[-1] else 0.0

    rsi = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    roc_10 = close.pct_change(10) * 100

    atr = _atr(high, low, close, 14)
    realized_vol = close.pct_change().rolling(20).std() * np.sqrt(1440)  # annualize-ish over 1m bars/day
    vol_percentile = float(atr.rank(pct=True).iloc[-1])
    bb_upper, bb_middle, bb_lower = _bollinger(close, 20, 2.0)
    bb_width = float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1]) if bb_middle.iloc[-1] else 0.0

    swing_high, swing_low, higher_high, lower_high, higher_low, lower_low = _swing_points(high, low)
    break_of_structure = bool(swing_high is not None and close.iloc[-1] > swing_high) or bool(
        swing_low is not None and close.iloc[-1] < swing_low
    )

    vol_sma_20 = _sma(volume, 20)
    volume_ratio = float(volume.iloc[-1] / vol_sma_20.iloc[-1]) if vol_sma_20.iloc[-1] else 1.0
    vwap = _vwap(high, low, close, volume)

    body = float(close.iloc[-1] - open_.iloc[-1])
    candle_range = float(high.iloc[-1] - low.iloc[-1])
    upper_wick = float(high.iloc[-1] - max(close.iloc[-1], open_.iloc[-1]))
    lower_wick = float(min(close.iloc[-1], open_.iloc[-1]) - low.iloc[-1])
    wick_ratio = float((upper_wick + lower_wick) / candle_range) if candle_range else 0.0
    gap = float(open_.iloc[-1] - close.iloc[-2]) if len(close) >= 2 else 0.0
    is_momentum_candle = bool(abs(body) > candle_range * 0.6) if candle_range else False

    regime_state = detect_regime(
        trend_strength=trend_strength,
        ema_slope=ema_slope,
        atr=float(atr.iloc[-1]),
        bb_width=bb_width,
        vol_percentile=vol_percentile,
        break_of_structure=break_of_structure,
        close_above_swing_high=bool(swing_high is not None and close.iloc[-1] > swing_high >= close.iloc[-2]),
        close_below_swing_low=bool(swing_low is not None and close.iloc[-1] < swing_low <= close.iloc[-2]),
    )

    return MarketContext(
        symbol=symbol,
        timeframe=timeframe,
        candle_open_time=int(df["open_time"].iloc[-1]),
        close_price=float(close.iloc[-1]),
        candle_open=float(open_.iloc[-1]),
        candle_high=float(high.iloc[-1]),
        candle_low=float(low.iloc[-1]),
        candle_close_time=int(df["open_time"].iloc[-1]) + _TIMEFRAME_MS.get(timeframe, 60_000) - 1,
        funding_rate=(float(df["funding_rate"].iloc[-1]) if "funding_rate" in df and pd.notna(df["funding_rate"].iloc[-1]) else None),
        open_interest=(float(df["open_interest"].iloc[-1]) if "open_interest" in df and pd.notna(df["open_interest"].iloc[-1]) else None),
        trend=TrendFeatures(
            ema_fast=float(ema_fast.iloc[-1]),
            ema_slow=float(ema_slow.iloc[-1]),
            sma_fast=float(sma_fast.iloc[-1]),
            sma_slow=float(sma_slow.iloc[-1]),
            ema_slope=ema_slope,
            trend_strength=trend_strength,
        ),
        momentum=MomentumFeatures(
            rsi_14=float(rsi.iloc[-1]),
            macd=float(macd_line.iloc[-1]),
            macd_signal=float(macd_signal.iloc[-1]),
            macd_hist=float(macd_hist.iloc[-1]),
            roc_10=float(roc_10.iloc[-1]) if not pd.isna(roc_10.iloc[-1]) else 0.0,
        ),
        volatility=VolatilityFeatures(
            atr_14=float(atr.iloc[-1]),
            realized_vol=float(realized_vol.iloc[-1]) if not pd.isna(realized_vol.iloc[-1]) else 0.0,
            volatility_percentile=vol_percentile,
            bb_upper=float(bb_upper.iloc[-1]),
            bb_middle=float(bb_middle.iloc[-1]),
            bb_lower=float(bb_lower.iloc[-1]),
            bb_width=bb_width,
        ),
        structure=StructureFeatures(
            swing_high=swing_high,
            swing_low=swing_low,
            break_of_structure=break_of_structure,
            higher_high=higher_high,
            lower_high=lower_high,
            higher_low=higher_low,
            lower_low=lower_low,
            nearest_support=swing_low,
            nearest_resistance=swing_high,
        ),
        volume=VolumeFeatures(
            volume_sma_20=float(vol_sma_20.iloc[-1]) if not pd.isna(vol_sma_20.iloc[-1]) else 0.0,
            volume_ratio=volume_ratio,
            volume_spike=bool(volume_ratio > 2.0),
            vwap=float(vwap.iloc[-1]),
        ),
        price_action=PriceActionFeatures(
            body=body,
            wick_ratio=wick_ratio,
            candle_range=candle_range,
            gap=gap,
            is_momentum_candle=is_momentum_candle,
        ),
        regime=regime_state,
    )


def detect_regime(
    *,
    trend_strength: float,
    ema_slope: float,
    atr: float,
    bb_width: float,
    vol_percentile: float,
    break_of_structure: bool,
    close_above_swing_high: bool,
    close_below_swing_low: bool,
) -> RegimeState:
    """Deterministic regime classifier (spec section 7), detector v2. Thresholds are
    intentionally simple/interpretable rather than ML-fit — this is a
    baseline the evolution/research loop can later challenge with
    data-driven alternatives, but the *interface* stays deterministic.

    v2 (correctness only, no new thresholds):
      * `close_above_swing_high` / `close_below_swing_low` are EVENTS: this bar is the first close beyond the last
        confirmed swing (v1 passed the persistent state, labelling 33-39% of bars BREAKOUT/BREAKDOWN).
      * A trend is checked BEFORE the ATR-percentile buckets (v1 checked it after, so a strong trend - which raises
        ATR - was always pre-empted by HIGH_VOLATILITY and TREND_UP/DOWN were practically unreachable).
      * RANGE is the residual class ("nothing above applies"): 1m Bollinger width is < 2% on ~97% of bars, so it
        carries no ranging information - choppiness does not persist at this timeframe (corr ~0.01)."""

    if close_above_swing_high and trend_strength > 0:
        return RegimeState(regime=MarketRegime.BREAKOUT, confidence=min(0.95, 0.6 + vol_percentile * 0.3))
    if close_below_swing_low and trend_strength < 0:
        return RegimeState(regime=MarketRegime.BREAKDOWN, confidence=min(0.95, 0.6 + vol_percentile * 0.3))

    if trend_strength > 0.004 and ema_slope > 0:
        return RegimeState(regime=MarketRegime.TREND_UP, confidence=min(0.9, abs(trend_strength) * 100))
    if trend_strength < -0.004 and ema_slope < 0:
        return RegimeState(regime=MarketRegime.TREND_DOWN, confidence=min(0.9, abs(trend_strength) * 100))

    if vol_percentile > 0.85:
        return RegimeState(regime=MarketRegime.HIGH_VOLATILITY, confidence=vol_percentile)
    if vol_percentile < 0.15:
        return RegimeState(regime=MarketRegime.LOW_VOLATILITY, confidence=1 - vol_percentile)

    if bb_width < 0.02:
        return RegimeState(regime=MarketRegime.RANGE, confidence=0.7)

    return RegimeState(regime=MarketRegime.UNCERTAIN, confidence=0.4)


def minimal_context(row, *, symbol: str, timeframe: str) -> MarketContext:
    """A NEUTRAL-feature context for one CONFIRMED stored candle (open/high/low/close/time only).

    Used by the protective pass for bars the worker could not run a full decision on (failed attempt, poison
    candle, skipped catch-up bar): stops, take-profit, trailing, funding and liquidation only need the bar's OHLC.
    The regime is recorded as UNCERTAIN and no strategy signal is ever evaluated from it."""
    close = float(row["close"])
    open_time = int(row["open_time"])
    return MarketContext(
        symbol=symbol, timeframe=timeframe, candle_open_time=open_time, close_price=close,
        candle_open=float(row["open"]), candle_high=float(row["high"]), candle_low=float(row["low"]),
        candle_close_time=open_time + _TIMEFRAME_MS.get(timeframe, 60_000) - 1,
        trend=TrendFeatures(ema_fast=close, ema_slow=close, sma_fast=close, sma_slow=close, ema_slope=0.0, trend_strength=0.0),
        momentum=MomentumFeatures(rsi_14=50.0, macd=0.0, macd_signal=0.0, macd_hist=0.0, roc_10=0.0),
        volatility=VolatilityFeatures(atr_14=0.0, realized_vol=0.0, volatility_percentile=0.5, bb_upper=close,
                                      bb_middle=close, bb_lower=close, bb_width=0.0),
        structure=StructureFeatures(),
        volume=VolumeFeatures(volume_sma_20=0.0, volume_ratio=1.0, volume_spike=False, vwap=close),
        price_action=PriceActionFeatures(body=0.0, wick_ratio=0.0, candle_range=0.0, gap=0.0, is_momentum_candle=False),
        regime=RegimeState(regime="UNCERTAIN", confidence=0.0),
        is_final=True,
    )
