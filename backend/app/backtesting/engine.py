"""Event-driven backtesting engine (spec section 22).

Walks candles strictly in time order. At step `i`, the feature engine only
ever sees candles[0..i] — never candles[i+1:] — so there is no look-ahead
leakage. Fills happen at the NEXT candle's open after a signal is generated
at candle i's close, which is the earliest a real system could have acted.

This engine is intentionally single-threaded and pandas-based: it needs to
be correct and auditable far more than it needs to be fast, and 500 agents
are backtested independently (never sharing mutable state) so parallelism
happens at the "run many backtests" layer, not inside one run.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.analytics.pnl_engine import compute_trade_pnl
from app.market.feature_engine import MIN_CANDLES_REQUIRED, InsufficientDataError, compute_features
from app.models.enums import Bias, Side
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.rule_engine import evaluate

FEATURE_WINDOW = 250  # trailing candles fed to the feature engine at each step


@dataclass
class BacktestTrade:
    side: Side
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    quantity: float
    net_pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    equity_curve: list[float]
    trades: list[BacktestTrade]
    final_equity: float
    starting_equity: float

    @property
    def net_return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.final_equity - self.starting_equity) / self.starting_equity

    @property
    def max_drawdown_pct(self) -> float:
        peak = self.starting_equity
        max_dd = 0.0
        for equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

    @property
    def win_rate(self) -> float | None:
        if not self.trades:
            return None
        wins = sum(1 for t in self.trades if t.net_pnl > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float | None:
        gross_win = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        if gross_loss == 0:
            return None if gross_win == 0 else float("inf")
        return gross_win / gross_loss


def run_backtest(
    candles: pd.DataFrame,
    dna: StrategyDNA,
    *,
    symbol: str,
    timeframe: str,
    starting_equity: float,
    fee_rate: float,
    slippage_bps: float,
    position_fraction_override: float | None = None,
) -> BacktestResult:
    """`candles` must be sorted ascending by open_time and contain at least
    MIN_CANDLES_REQUIRED + a few steps of history."""
    if len(candles) < MIN_CANDLES_REQUIRED + 5:
        raise InsufficientDataError(
            f"backtest needs at least {MIN_CANDLES_REQUIRED + 5} candles, got {len(candles)}"
        )

    equity = starting_equity
    equity_curve: list[float] = []
    trades: list[BacktestTrade] = []

    open_position: dict | None = None
    prev_context: MarketContext | None = None

    fraction = position_fraction_override or dna.position_sizing.fraction_of_equity

    for i in range(MIN_CANDLES_REQUIRED, len(candles)):
        window = candles.iloc[max(0, i - FEATURE_WINDOW + 1) : i + 1]
        context = compute_features(window, symbol=symbol, timeframe=timeframe)

        signal = evaluate(dna, context, prev_context, has_open_position=open_position is not None)

        # Fill happens at the OPEN of the next candle (i+1), the earliest a
        # signal generated at candle i's close could realistically execute.
        if i + 1 < len(candles):
            next_open = float(candles["open"].iloc[i + 1])
        else:
            next_open = context.close_price

        if open_position is None and signal.matched_entry:
            quantity = (equity * fraction * dna.leverage_limit) / next_open
            entry_fee = next_open * quantity * fee_rate
            slippage_dir = 1 if signal.bias == Bias.LONG else -1
            fill_price = next_open * (1 + (slippage_bps / 10_000) * slippage_dir)
            open_position = {
                "side": Side.LONG if signal.bias == Bias.LONG else Side.SHORT,
                "entry_index": i + 1,
                "entry_price": fill_price,
                "quantity": quantity,
                "entry_fee": entry_fee,
                "stop_price": _stop_price(dna, fill_price, context.volatility.atr_14, signal.bias),
                "take_profit_price": _take_profit_price(dna, fill_price, context.volatility.atr_14, signal.bias),
            }
            equity -= entry_fee

        elif open_position is not None:
            exit_reason = None
            exit_price = next_open

            low = float(candles["low"].iloc[i])
            high = float(candles["high"].iloc[i])
            if open_position["side"] == Side.LONG:
                if open_position["stop_price"] and low <= open_position["stop_price"]:
                    exit_reason, exit_price = "stop_loss", open_position["stop_price"]
                elif open_position["take_profit_price"] and high >= open_position["take_profit_price"]:
                    exit_reason, exit_price = "take_profit", open_position["take_profit_price"]
            else:
                if open_position["stop_price"] and high >= open_position["stop_price"]:
                    exit_reason, exit_price = "stop_loss", open_position["stop_price"]
                elif open_position["take_profit_price"] and low <= open_position["take_profit_price"]:
                    exit_reason, exit_price = "take_profit", open_position["take_profit_price"]

            if exit_reason is None and signal.matched_exit:
                exit_reason = "signal"

            if exit_reason is not None:
                exit_fee = exit_price * open_position["quantity"] * fee_rate
                pnl = compute_trade_pnl(
                    side=open_position["side"],
                    quantity=open_position["quantity"],
                    entry_price=open_position["entry_price"],
                    exit_price=exit_price,
                    entry_fee=open_position["entry_fee"],
                    exit_fee=exit_fee,
                    funding_paid=0.0,
                    slippage_cost=0.0,
                )
                equity += pnl.gross_pnl - exit_fee
                trades.append(
                    BacktestTrade(
                        side=open_position["side"],
                        entry_index=open_position["entry_index"],
                        exit_index=i,
                        entry_price=open_position["entry_price"],
                        exit_price=exit_price,
                        quantity=open_position["quantity"],
                        net_pnl=pnl.net_pnl,
                        exit_reason=exit_reason,
                    )
                )
                open_position = None

        equity_curve.append(equity)
        prev_context = context

        if equity <= 0:
            break

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        final_equity=equity,
        starting_equity=starting_equity,
    )


def _stop_price(dna: StrategyDNA, entry_price: float, atr: float, bias: Bias) -> float | None:
    if not dna.stop_loss.enabled:
        return None
    distance = atr * dna.stop_loss.value if dna.stop_loss.method == "atr_multiple" else entry_price * (dna.stop_loss.value / 100)
    return entry_price - distance if bias == Bias.LONG else entry_price + distance


def _take_profit_price(dna: StrategyDNA, entry_price: float, atr: float, bias: Bias) -> float | None:
    if not dna.take_profit.enabled:
        return None
    if dna.take_profit.method == "atr_multiple":
        distance = atr * dna.take_profit.value
    elif dna.take_profit.method == "risk_reward_multiple" and dna.stop_loss.enabled:
        stop_distance = atr * dna.stop_loss.value if dna.stop_loss.method == "atr_multiple" else entry_price * (dna.stop_loss.value / 100)
        distance = stop_distance * dna.take_profit.value
    else:
        distance = entry_price * (dna.take_profit.value / 100)
    return entry_price + distance if bias == Bias.LONG else entry_price - distance
