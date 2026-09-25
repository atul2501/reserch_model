"""Regime detector v2 (correctness fixes only; no new thresholds).

v1 defects, demonstrated on 4.8k real SOL 1m bars:
  * TREND_UP / TREND_DOWN were checked AFTER the relative ATR-percentile buckets, so every strong-trend bar was
    already labelled HIGH_VOLATILITY / LOW_VOLATILITY / BREAKOUT: 187 bars met the trend rule, 6 were labelled TREND.
    Any strategy gated on TREND regimes (TREND_FOLLOWING, MOMENTUM, VWAP...) could practically never enter.
  * BREAKOUT / BREAKDOWN were a persistent STATE ("close is somewhere beyond the last swing"): 33-39% of all bars.
    A breakout regime should mark the bar that BREAKS the level (an event, ~6% of bars).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.market.feature_engine import compute_features, detect_regime
from app.models.enums import MarketRegime
from app.schemas.market_context import RegimeState

from tests.test_swing_points import _candles, _zigzag_pivots

_QUIET = dict(ema_slope=0.0, atr=0.1, bb_width=0.004, break_of_structure=False,
              close_above_swing_high=False, close_below_swing_low=False)


def _regime(**over):
    args = {**_QUIET, "trend_strength": 0.0, "vol_percentile": 0.5, **over}
    return detect_regime(**args).regime


# --------------------------------------------------------------------------- #
# precedence: a strong trend is a trend even when ATR is in the top / bottom bucket
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("vol_percentile", [0.05, 0.5, 0.95])
def test_strong_uptrend_is_trend_up_whatever_the_atr_percentile(vol_percentile):
    assert _regime(trend_strength=0.006, ema_slope=0.3, vol_percentile=vol_percentile) == MarketRegime.TREND_UP


@pytest.mark.parametrize("vol_percentile", [0.05, 0.5, 0.95])
def test_strong_downtrend_is_trend_down_whatever_the_atr_percentile(vol_percentile):
    assert _regime(trend_strength=-0.006, ema_slope=-0.3, vol_percentile=vol_percentile) == MarketRegime.TREND_DOWN


def test_trend_needs_slope_agreement():
    assert _regime(trend_strength=0.006, ema_slope=-0.3, vol_percentile=0.95) == MarketRegime.HIGH_VOLATILITY


def test_volatility_buckets_still_apply_without_a_trend():
    assert _regime(vol_percentile=0.95) == MarketRegime.HIGH_VOLATILITY
    assert _regime(vol_percentile=0.05) == MarketRegime.LOW_VOLATILITY


def test_a_fresh_break_still_outranks_trend():
    assert _regime(trend_strength=0.006, ema_slope=0.3, close_above_swing_high=True) == MarketRegime.BREAKOUT
    assert _regime(trend_strength=-0.006, ema_slope=-0.3, close_below_swing_low=True) == MarketRegime.BREAKDOWN


def test_residual_classes_are_unchanged():
    assert _regime() == MarketRegime.RANGE
    assert _regime(bb_width=0.03) == MarketRegime.UNCERTAIN


def test_regime_state_carries_detector_version_v2():
    assert RegimeState(regime=MarketRegime.RANGE, confidence=0.5).detector_version == "v2"
    assert detect_regime(trend_strength=0.0, ema_slope=0.0, atr=0.1, bb_width=0.004, vol_percentile=0.5,
                         break_of_structure=False, close_above_swing_high=False,
                         close_below_swing_low=False).detector_version == "v2"


# --------------------------------------------------------------------------- #
# end to end through compute_features
# --------------------------------------------------------------------------- #
def _bar_regimes(candles: pd.DataFrame, last: int) -> list[tuple[MarketRegime, bool]]:
    """(regime, break_of_structure feature) for each of the last `last` bars, each computed on its own prefix."""
    out = []
    for k in range(len(candles) - last, len(candles)):
        ctx = compute_features(candles.iloc[: k + 1].reset_index(drop=True), symbol="SOL", timeframe="1m")
        out.append((ctx.regime.regime, ctx.structure.break_of_structure))
    return out


@pytest.mark.parametrize("direction, regime", [(1, MarketRegime.BREAKOUT), (-1, MarketRegime.BREAKDOWN)])
def test_breakout_regime_marks_only_the_bar_that_breaks_the_level(direction, regime):
    bars = _bar_regimes(_candles(_zigzag_pivots(direction)), last=8)
    broke = [i for i, (_, bos) in enumerate(bars) if bos]
    assert broke, "the surge never broke the last confirmed swing"
    first = broke[0]
    assert bars[first][0] == regime                      # the breaking bar IS the breakout
    for i in broke[1:]:                                  # bars that merely stay beyond the level are not
        assert bars[i][0] != regime
    assert sum(r == regime for r, _ in bars) == 1


def test_persistent_break_of_structure_feature_is_unchanged():
    # the BOS *feature* is still a state (strategies may read it); only the REGIME became an event
    bars = _bar_regimes(_candles(_zigzag_pivots(1)), last=8)
    assert sum(bos for _, bos in bars) >= 2


def test_strong_trend_with_high_atr_is_labelled_trend_end_to_end():
    rng = np.random.default_rng(7)
    calm = 100 + np.cumsum(rng.normal(0, 0.01, 250))
    rise = calm[-1] * (1 + 0.0015) ** np.arange(1, 41)          # +0.15% per bar: EMA12 pulls well away from EMA50
    close = np.concatenate([calm, rise])
    candles = pd.DataFrame({
        "open_time": np.arange(len(close)) * 60_000, "open": np.r_[close[0], close[:-1]],
        "high": close * 1.0004, "low": close * 0.9996, "close": close, "volume": 1000.0,
    })
    ctx = compute_features(candles, symbol="SOL", timeframe="1m")
    assert ctx.trend.trend_strength > 0.004 and ctx.volatility.volatility_percentile > 0.85
    assert ctx.regime.regime == MarketRegime.TREND_UP
