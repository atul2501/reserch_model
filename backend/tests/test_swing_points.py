"""Swing-structure features: higher-high / higher-low / lower-high / lower-low, break-of-structure and the
BREAKOUT / BREAKDOWN regimes that depend on them.

Regression for a defect where `_swing_points` only scanned the last `window + 1` bars for swing candidates, each of
which must be the extreme of a +-`window` neighbourhood. Any two such candidates contain each other, so their values
are equal and HH/HL/LH/LL could never be strictly true; the newest swing also always contained the last bar, so
`close > swing_high` (BOS -> BREAKOUT) was impossible. MARKET_STRUCTURE agents and the BREAKOUT/BREAKDOWN regimes were
therefore dead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.market.feature_engine import _swing_points, compute_features
from app.models.enums import MarketRegime

WINDOW = 5


def _path(pivots: list[tuple[int, float]], half_range: float = 0.2) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Piecewise-linear price through `pivots` -> (high, low, close). Every pivot is a strict local extreme."""
    xs, ys = zip(*pivots)
    n = xs[-1] + 1
    mid = pd.Series(np.interp(np.arange(n), xs, ys))
    return mid + half_range, mid - half_range, mid


def _candles(pivots: list[tuple[int, float]]) -> pd.DataFrame:
    high, low, close = _path(pivots)
    return pd.DataFrame({
        "open_time": np.arange(len(close)) * 60_000, "open": close.shift(1).fillna(close.iloc[0]),
        "high": high, "low": low, "close": close, "volume": 1000.0,
    })


# --------------------------------------------------------------------------- #
# _swing_points: hand-built structure
# --------------------------------------------------------------------------- #
def test_higher_highs_and_higher_lows_are_detected():
    # peaks 105 -> 108 (HH), valleys 99 -> 100 (HL); the last pivot (idx 34) is unconfirmed
    high, low, _ = _path([(0, 101), (8, 105), (14, 99), (20, 108), (26, 100), (34, 103)])
    sh, sl, hh, lh, hl, ll = _swing_points(high, low)
    assert (hh, lh, hl, ll) == (True, False, True, False)
    assert sh == pytest.approx(108.2) and sl == pytest.approx(99.8)


def test_lower_highs_and_lower_lows_are_detected():
    # peaks 108 -> 105 (LH), valleys 100 -> 97 (LL)
    high, low, _ = _path([(0, 104), (8, 108), (14, 100), (20, 105), (26, 97), (34, 101)])
    sh, sl, hh, lh, hl, ll = _swing_points(high, low)
    assert (hh, lh, hl, ll) == (False, True, False, True)
    assert sh == pytest.approx(105.2) and sl == pytest.approx(96.8)


def test_swing_needs_confirmation_the_newest_bars_are_never_a_swing():
    # price rips to a new high on the very last bar: it cannot be a confirmed swing high (no bars to its right yet)
    high, low, _ = _path([(0, 101), (8, 105), (14, 99), (20, 108), (26, 100), (34, 112)])
    sh, _sl, hh, _lh, _hl, _ll = _swing_points(high, low)
    assert sh == pytest.approx(108.2)     # still the last CONFIRMED swing high, not the 112.2 of the newest bar
    assert hh is True                     # 108 vs 105: unaffected by the unconfirmed breakout bar


def test_too_short_a_series_reports_nothing():
    high, low, _ = _path([(0, 100), (2 * WINDOW - 1, 101)])   # 2*window bars: one short of the minimum
    assert _swing_points(high, low) == (None, None, False, False, False, False)


# --------------------------------------------------------------------------- #
# _swing_points: statistical property on random walks (the original defect made every one of these 0)
# --------------------------------------------------------------------------- #
def test_structure_flags_are_reachable_on_random_walks():
    rng = np.random.default_rng(0)
    counts = dict(hh=0, lh=0, hl=0, ll=0, above=0, below=0)
    trials = 1500
    for _ in range(trials):
        n = int(rng.integers(40, 200))
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        high = pd.Series(close + np.abs(rng.normal(0, 0.05, n)))
        low = pd.Series(close - np.abs(rng.normal(0, 0.05, n)))
        sh, sl, hh, lh, hl, ll = _swing_points(high, low)
        counts["hh"] += hh
        counts["lh"] += lh
        counts["hl"] += hl
        counts["ll"] += ll
        counts["above"] += bool(sh is not None and close[-1] > sh)
        counts["below"] += bool(sl is not None and close[-1] < sl)
    for key, value in counts.items():
        assert value > 0.05 * trials, f"{key} fired in only {value}/{trials} random windows"


# --------------------------------------------------------------------------- #
# End to end through compute_features: BOS and the BREAKOUT / BREAKDOWN regimes
# --------------------------------------------------------------------------- #
def _zigzag_pivots(direction: int, n_cycles: int = 10, breakout: bool = True) -> list[tuple[int, float]]:
    """A steadily trending zigzag (period 24 bars) that ends with a surge through the last confirmed swing."""
    pivots = [(0, 100.0)]
    for k in range(n_cycles):
        base = 100.0 + direction * 2.0 * k
        pivots.append((24 * k + 12, base + direction * 3.0))    # swing extreme in the trend direction
        pivots.append((24 * k + 24, base + direction * 0.5))    # pullback
    end = pivots[-1][0]
    if breakout:
        pivots.append((end + 8, pivots[-1][1] + direction * 12.0))
    return pivots


@pytest.mark.parametrize("direction", [1, -1])
def test_break_of_structure_can_occur(direction):
    # (the BREAKOUT / BREAKDOWN *regime* built on top of this feature is covered in test_regime_v2.py)
    candles = _candles(_zigzag_pivots(direction))
    ctx = compute_features(candles, symbol="SOL", timeframe="1m")
    assert ctx.structure.break_of_structure is True


def test_no_break_of_structure_inside_the_range():
    candles = _candles(_zigzag_pivots(1, breakout=False))
    ctx = compute_features(candles, symbol="SOL", timeframe="1m")
    assert ctx.structure.break_of_structure is False
    assert ctx.regime.regime not in (MarketRegime.BREAKOUT, MarketRegime.BREAKDOWN)


def test_uptrending_structure_reports_higher_highs_and_lows_via_compute_features():
    candles = _candles(_zigzag_pivots(1, breakout=False))
    ctx = compute_features(candles, symbol="SOL", timeframe="1m")
    assert ctx.structure.higher_high is True and ctx.structure.higher_low is True
    assert ctx.structure.lower_high is False and ctx.structure.lower_low is False
