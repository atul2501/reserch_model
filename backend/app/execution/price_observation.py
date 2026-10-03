"""Timestamped price observations and the "no fill before the decision" rule.

A simulated fill may only use a price that was actually OBSERVED at or after the moment the order could have been sent.
With 1-minute OHLCV the only timestamped prices are a bar's OPEN (at open_time) and CLOSE (at open_time + interval);
a bar's high/low carry no timestamp and are therefore never a fill price. Nothing here interpolates or models a
sub-minute price: when no real observation exists after the decision, the answer is None and the caller must not
fill (and must say why), rather than invent one.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceObservation:
    ts_ms: int            # exchange/wall-clock instant the price is valid for
    price: float
    source: str           # e.g. "bar_open", "bar_close", "l2_mid"
    modelled: bool = False  # always False for anything this project uses as a fill price


def bar_observations(open_time_ms: int, interval_ms: int, open_: float, close: float) -> list[PriceObservation]:
    """The two timestamped prices a confirmed OHLC bar provides (close time = open + interval - 1, the codebase's
    `candle_close_time` convention)."""
    return [PriceObservation(open_time_ms, float(open_), "bar_open"),
            PriceObservation(open_time_ms + interval_ms - 1, float(close), "bar_close")]


def first_observed_at_or_after(decision_ms: int, observations: list[PriceObservation]) -> PriceObservation | None:
    """Earliest REAL (non-modelled) observation with ts >= decision_ms, or None."""
    eligible = [o for o in observations if not o.modelled and o.ts_ms >= decision_ms and o.price > 0]
    return min(eligible, key=lambda o: o.ts_ms) if eligible else None
