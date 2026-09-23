"""Deterministic fake exchange + candle factory shared by market/worker tests."""
from __future__ import annotations

import math

INTERVAL = 60_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % INTERVAL)  # aligned to a minute


def make_raw_candle(i: int, base: float = 100.0) -> dict:
    """i-th 1m candle after T0, Hyperliquid wire format."""
    t = T0 + i * INTERVAL
    px = base + 5 * math.sin(i / 17) + i * 0.01
    return {
        "t": t, "T": t + INTERVAL - 1,
        "o": str(px), "h": str(px + 0.6), "l": str(px - 0.6), "c": str(px + 0.1), "v": str(1000 + (i % 7) * 10), "n": 50,
    }


class FakeHyperliquid:
    """In-memory stand-in for HyperliquidClient (only the methods the service uses)."""

    def __init__(self, n_candles: int = 400) -> None:
        self.candles = [make_raw_candle(i) for i in range(n_candles)]
        self.hidden: set[int] = set()         # open_times the exchange "hasn't published yet / doesn't have"
        self.calls: list[tuple] = []
        self.funding = [{"coin": "SOL", "fundingRate": "0.0000125", "premium": "0.0001", "time": T0 + h * 3_600_000}
                        for h in range(1, 8)]
        self.fail_candles = False
        self.on_call = None  # optional hook(call_index)

    async def get_candles(self, coin, interval, start_ms, end_ms):
        self.calls.append(("candles", start_ms, end_ms))
        if self.on_call:
            self.on_call(len(self.calls))
        if self.fail_candles:
            raise RuntimeError("exchange down")
        return [c for c in self.candles if start_ms <= c["t"] <= end_ms and c["t"] not in self.hidden]

    async def get_meta_and_funding(self, coin):
        self.calls.append(("meta",))
        return {"funding": "0.00001", "openInterest": "12345"}

    async def get_funding_history(self, coin, start_ms, end_ms=None):
        self.calls.append(("funding_history", start_ms))
        return [f for f in self.funding if f["time"] >= start_ms]

    async def aclose(self):
        pass


def clock_after_bar(i: int, extra_ms: int = 1_600) -> int:
    """A clock value just after bar i has closed (past the 1.5s grace by default)."""
    return T0 + i * INTERVAL + INTERVAL - 1 + extra_ms
