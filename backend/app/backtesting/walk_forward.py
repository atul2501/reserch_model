"""Walk-forward testing (spec section 24). Rolls a train/test window
forward across the dataset and records every window's result — never just
the best or the most recent one — so consistency can be measured.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.backtesting.engine import BacktestResult, run_backtest
from app.schemas.strategy_dna import StrategyDNA


@dataclass
class WalkForwardWindow:
    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    result: BacktestResult


@dataclass
class WalkForwardReport:
    windows: list[WalkForwardWindow]

    @property
    def average_return_pct(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.result.net_return_pct for w in self.windows) / len(self.windows)

    @property
    def worst_window_return_pct(self) -> float:
        if not self.windows:
            return 0.0
        return min(w.result.net_return_pct for w in self.windows)

    @property
    def best_window_return_pct(self) -> float:
        if not self.windows:
            return 0.0
        return max(w.result.net_return_pct for w in self.windows)

    @property
    def consistency_score(self) -> float:
        """Fraction of windows that were profitable — a simple, auditable
        stand-in for "how repeatable is this strategy" (spec section 24)."""
        if not self.windows:
            return 0.0
        profitable = sum(1 for w in self.windows if w.result.net_return_pct > 0)
        return profitable / len(self.windows)

    @property
    def max_drawdown_across_windows(self) -> float:
        if not self.windows:
            return 0.0
        return max(w.result.max_drawdown_pct for w in self.windows)


def run_walk_forward(
    candles: pd.DataFrame,
    dna: StrategyDNA,
    *,
    symbol: str,
    timeframe: str,
    train_window: int,
    test_window: int,
    step: int,
    starting_equity: float,
    fee_rate: float,
    slippage_bps: float,
) -> WalkForwardReport:
    windows: list[WalkForwardWindow] = []
    n = len(candles)
    window_index = 0
    start = 0

    while start + train_window + test_window <= n:
        test_start = start + train_window
        test_end = test_start + test_window

        # The test slice needs `train_window` worth of history for the
        # feature engine's warmup, so we hand it candles[start:test_end]
        # and only score trades that occur within [test_start, test_end).
        test_slice = candles.iloc[start:test_end].reset_index(drop=True)
        result = run_backtest(
            test_slice,
            dna,
            symbol=symbol,
            timeframe=timeframe,
            starting_equity=starting_equity,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        windows.append(
            WalkForwardWindow(
                window_index=window_index,
                train_start=start,
                train_end=start + train_window,
                test_start=test_start,
                test_end=test_end,
                result=result,
            )
        )
        window_index += 1
        start += step

    return WalkForwardReport(windows=windows)
