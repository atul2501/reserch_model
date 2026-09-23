"""Shared, precomputed backtest inputs (spec phase 5/39).

Feature computation dominates backtest cost and is agent-independent, so it
is done ONCE per dataset and shared by every agent's simulation:

  * `contexts[i]`/`flat[i]` — the static MarketContext at each bar, computed on
    the same trailing 250-bar window the live worker uses (no look-ahead);
  * `dyn[key]` — every distinct dynamic indicator series any DNA declares,
    computed once over the whole frame (vectorised; each value at bar i uses
    only bars <= i).

Contexts are memoised by a content hash of the candles, so walk-forward
windows, OOS runs and adversarial scenarios that reuse the same candles pay
for features only once.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.market.feature_engine import MIN_CANDLES_REQUIRED, InsufficientDataError, compute_features
from app.schemas.market_context import MarketContext
from app.strategies.indicators import IndicatorSpec, compute_indicator_series

FEATURE_WINDOW = 250  # trailing candles fed to the feature engine at each bar (same as live)

_CONTEXT_CACHE: dict[str, tuple[list, list]] = {}
_CONTEXT_CACHE_MAX = 24


def candles_fingerprint(candles: pd.DataFrame) -> str:
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    arr = np.ascontiguousarray(candles[cols].to_numpy(dtype="float64"))
    return hashlib.sha256(arr.tobytes()).hexdigest()


@dataclass
class BacktestData:
    candles: pd.DataFrame
    symbol: str
    timeframe: str
    contexts: list[MarketContext | None]
    flat: list[dict | None]
    dyn: dict[str, np.ndarray] = field(default_factory=dict)
    funding: list[tuple[int, float]] = field(default_factory=list)  # (settlement_ms, rate), sorted

    def __post_init__(self) -> None:
        c = self.candles
        self.open_time = c["open_time"].to_numpy(dtype="int64")
        self.open = c["open"].to_numpy(dtype="float64")
        self.high = c["high"].to_numpy(dtype="float64")
        self.low = c["low"].to_numpy(dtype="float64")
        self.close = c["close"].to_numpy(dtype="float64")

    def __len__(self) -> int:
        return len(self.candles)


def _compute_contexts(candles: pd.DataFrame, symbol: str, timeframe: str) -> tuple[list, list]:
    key = f"{symbol}:{timeframe}:{candles_fingerprint(candles)}"
    hit = _CONTEXT_CACHE.get(key)
    if hit is not None:
        return hit
    n = len(candles)
    contexts: list[MarketContext | None] = [None] * n
    flat: list[dict | None] = [None] * n
    for i in range(MIN_CANDLES_REQUIRED - 1, n):
        window = candles.iloc[max(0, i - FEATURE_WINDOW + 1): i + 1]
        try:
            ctx = compute_features(window, symbol=symbol, timeframe=timeframe)
        except InsufficientDataError:
            continue
        contexts[i] = ctx
        flat[i] = ctx.flat_features()
    if len(_CONTEXT_CACHE) >= _CONTEXT_CACHE_MAX:
        _CONTEXT_CACHE.pop(next(iter(_CONTEXT_CACHE)))
    _CONTEXT_CACHE[key] = (contexts, flat)
    return contexts, flat


def prepare_backtest_data(
    candles: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    specs: "set[IndicatorSpec] | list[IndicatorSpec] | tuple[IndicatorSpec, ...]" = (),
    funding: list[tuple[int, float]] | None = None,
) -> BacktestData:
    if len(candles) < MIN_CANDLES_REQUIRED + 5:
        raise InsufficientDataError(f"backtest needs at least {MIN_CANDLES_REQUIRED + 5} candles, got {len(candles)}")
    candles = candles.reset_index(drop=True)
    contexts, flat = _compute_contexts(candles, symbol, timeframe)
    dyn: dict[str, np.ndarray] = {}
    for spec in set(specs):
        for key, series in compute_indicator_series(candles, spec).items():
            dyn[key] = series.to_numpy(dtype="float64")
    return BacktestData(candles, symbol, timeframe, contexts, flat, dyn, sorted(funding or []))


def extend_with_specs(data: BacktestData, specs) -> BacktestData:
    """Adds any indicator series not yet present (idempotent)."""
    for spec in set(specs):
        for key, series in compute_indicator_series(data.candles, spec).items():
            data.dyn.setdefault(key, series.to_numpy(dtype="float64"))
    return data
