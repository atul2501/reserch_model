"""Candle-boundary arithmetic for the worker (pure functions, no I/O).

Hyperliquid candles: `t` = open time (ms), `T` = t + interval - 1 (close). A bar
is *confirmed* once `T + grace <= now`. The worker targets exactly these
confirmation instants instead of "sleep(60) after the previous cycle", so a
slow cycle never drifts the schedule and a late-published bar is awaited, not
skipped.
"""
from __future__ import annotations


def last_confirmed_open_time(now_ms: int, interval_ms: int, grace_ms: int) -> int:
    """Open time of the most recent bar whose close+grace is already in the past."""
    latest_open = now_ms - grace_ms - interval_ms + 1
    return (latest_open // interval_ms) * interval_ms


def confirmation_time_ms(open_time_ms: int, interval_ms: int, grace_ms: int) -> int:
    """Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes confirmed."""
    return open_time_ms + interval_ms - 1 + grace_ms


def seconds_until_next_confirmation(now_ms: int, interval_ms: int, grace_ms: int) -> float:
    """Seconds to sleep until the next bar becomes confirmable (never negative)."""
    next_open = last_confirmed_open_time(now_ms, interval_ms, grace_ms) + interval_ms
    return max(0.0, (confirmation_time_ms(next_open, interval_ms, grace_ms) - now_ms) / 1000)


def council_due(open_time_ms: int, interval_ms: int, every_n_candles: int) -> bool:
    """Deterministic, restart-safe council cadence derived from the candle
    timestamp itself (no in-memory counter that resets on restart)."""
    if every_n_candles <= 1:
        return True
    return (open_time_ms // interval_ms) % every_n_candles == 0
