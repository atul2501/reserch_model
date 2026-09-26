"""Event-driven backtesting engine (spec section 22; phase 22 "backtest parity").

Walks candles strictly in time order. Decisions at bar `i` use ONLY data up to
and including bar `i` (features are precomputed on the same trailing window the
live worker uses), and an entry signalled at bar i's close fills at bar i+1's
OPEN — the earliest a real system could act. There is no look-ahead.

It runs the SAME decision code as the live worker so that a backtest and a
paper run differ only by market data and execution noise (which is exactly what
the reality-gap engine is meant to measure):

  * the shared StrategyEngine (DNA-declared dynamic indicators, direction modes,
    family semantics) — `app.strategies.engine.evaluate_signal`
  * shared sizing (`app.execution.sizing`) — every DNA sizing method works
  * shared position management rules (`app.agents.position_manager`): stop /
    take-profit / trailing (with activation) / gap-aware fills / stop-wins on
    an ambiguous bar / cross-margin liquidation
  * shared cost model (`app.execution.fillmodel`): fees, size-aware slippage,
    stop slippage multiplier, maker fee for take-profit limits
  * cooldown (in bars) and max_trades_per_day
  * funding accrual from exchange settlements when supplied
  * mark-to-market equity curve (drawdown includes open-position losses)

Paper now uses the same model (a signal on bar N's close is a pending order filled at bar N+1's open), and the
cash accounting (funding, close settlement with recorded bad debt, cooldown, protective levels) is the shared
`app.execution.accounting`. Sizing and the risk check are priced at the signal bar's CLOSE - the only price known when
the decision is made - and the quantity is converted at the fill price. Documented deviations from live (kept small
and visible): no latency drift / random rejects / partial fills in a plain backtest (adversarial scenarios add them).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.agents.position_manager import (
    Bar,
    PositionLevels,
    advance_extremes,
    evaluate_bar,
)
from app.analytics.pnl_engine import compute_liquidation_price, compute_trade_pnl
from app.backtesting.data import BacktestData, prepare_backtest_data
from app.backtesting.risk_adapter import backtest_risk_check
from app.core.config import get_settings
from app.execution import accounting
from app.execution.fillmodel import fee_rate_for, slipped_price, slippage_bps as slippage_bps_for
from app.execution.margin import margin_state
from app.execution.sizing import approve_against_margin, below_min_order_notional, requested_notional, stop_distance_pct
from app.market.feature_engine import FEATURE_WINDOW, MIN_CANDLES_REQUIRED, InsufficientDataError
from app.market.hyperliquid_client import HyperliquidClient
from app.models.enums import Bias, Side
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import FeatureView, dna_indicator_specs, evaluate_signal



# Bumped whenever simulation semantics change (fill timing, sizing price, accounting, cooldown ...): part of every
# experiment's provenance, so results from different engine generations are never silently compared.
ENGINE_VERSION = "backtest-2.0"


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
    fee: float = 0.0
    slippage_cost: float = 0.0
    entry_regime: str | None = None
    exit_regime: str | None = None
    funding: float = 0.0
    bad_debt: float = 0.0


@dataclass
class BacktestResult:
    equity_curve: list[float]
    trades: list[BacktestTrade]
    final_equity: float
    starting_equity: float
    dead: bool = False
    total_funding: float = 0.0
    total_bad_debt: float = 0.0
    # The window this run actually simulated (reality-gap normalisation needs the observation length).
    first_bar_open_ms: int | None = None
    last_bar_open_ms: int | None = None
    bars_simulated: int = 0

    interval_ms: int = 60_000

    @property
    def observed_days(self) -> float | None:
        if self.first_bar_open_ms is None or self.last_bar_open_ms is None:
            return None
        return (self.last_bar_open_ms - self.first_bar_open_ms + self.interval_ms) / 86_400_000

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
        return sum(1 for t in self.trades if t.net_pnl > 0) / len(self.trades)

    @property
    def profit_factor(self) -> float | None:
        gross_win = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        if gross_loss == 0:
            return None if gross_win == 0 else float("inf")
        return gross_win / gross_loss

    @property
    def expectancy(self) -> float | None:
        return (sum(t.net_pnl for t in self.trades) / len(self.trades)) if self.trades else None


@dataclass
class _Pos:
    side: Side
    entry_index: int
    entry_price: float
    quantity: float
    entry_fee: float
    entry_slippage_cost: float
    entry_regime: str | None
    stop: float | None
    tp: float | None
    trail_distance: float | None
    trailing_active: bool
    peak: float
    trough: float
    last_funding_ms: int
    funding: float = 0.0


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
    enforce_risk_engine: bool = False,
    global_max_leverage: float = 5.0,
    global_max_position_size: float = 0.5,
    global_max_drawdown: float = 0.30,
    global_max_daily_loss: float = 0.10,
    data: BacktestData | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
    funding: list[tuple[int, float]] | None = None,
    execution_delay_bars: int = 0,
    fill_fraction: float = 1.0,
    entry_reject_probability: float = 0.0,
    rng=None,
) -> BacktestResult:
    """`candles` must be sorted ascending by open_time and contain at least
    MIN_CANDLES_REQUIRED + a few steps of history.

    `data` lets a caller share precomputed features across many agents/windows
    (see prepare_backtest_data); `start_index`/`end_index` restrict trading to a
    slice of it (walk-forward). `enforce_risk_engine=True` routes every entry
    through the real Risk Engine (adversarial testing and the research
    pipeline do). `funding` = [(settlement_ms, rate)] enables funding accrual.

    Execution stress knobs (adversarial testing): `execution_delay_bars` delays
    every fill by that many bars, `fill_fraction` < 1 models partial fills,
    `entry_reject_probability` models rejected / unknown-state entry orders."""
    if len(candles) < MIN_CANDLES_REQUIRED + 5:
        raise InsufficientDataError(f"backtest needs at least {MIN_CANDLES_REQUIRED + 5} candles, got {len(candles)}")
    settings = get_settings()
    specs = dna_indicator_specs(dna)
    if data is None:
        data = prepare_backtest_data(candles, symbol=symbol, timeframe=timeframe, specs=specs, funding=funding)
    else:
        from app.backtesting.data import extend_with_specs
        extend_with_specs(data, specs)

    n = len(data)
    first = max(MIN_CANDLES_REQUIRED, start_index if start_index is not None else 0)
    last = min(n, end_index if end_index is not None else n)
    interval_ms = HyperliquidClient.timeframe_to_ms(timeframe)
    maker_rate = settings.paper_maker_fee_rate * (fee_rate / settings.paper_fee_rate if settings.paper_fee_rate else 1.0)
    mmr = settings.maintenance_margin_rate
    from app.strategies.indicators import feature_keys_for
    dyn_keys = [k for spec in specs for k in feature_keys_for(spec) if k in data.dyn]

    balance = starting_equity
    peak_equity = starting_equity
    day_start_equity = starting_equity
    day_start_date = None
    daily_trades = 0
    cooldown_until_index = -1
    equity_curve: list[float] = []
    trades: list[BacktestTrade] = []
    pos: _Pos | None = None
    total_funding = 0.0
    total_bad_debt = 0.0
    dead = False
    fraction = position_fraction_override

    funding_events = data.funding or sorted(funding or [])

    def slip(kind: str, ref: float, side: Side, notional: float, reduce_only: bool) -> float:
        bps = slippage_bps_for(kind, notional, base_bps=slippage_bps,
                               impact_bps_per_10k=settings.paper_slippage_impact_bps_per_10k,
                               stop_multiplier=settings.paper_stop_slippage_multiplier)
        return slipped_price(ref, side, reduce_only=reduce_only, bps=bps)

    def close(position: _Pos, ref: float, kind: str, reason: str, at_index: int, regime: str | None) -> None:
        nonlocal balance, pos, cooldown_until_index, dead, total_bad_debt
        px = slip(kind, ref, position.side, ref * position.quantity, True)
        fee = px * position.quantity * fee_rate_for(kind, taker=fee_rate, maker=maker_rate)
        if kind == "liquidation":
            fee += accounting.liquidation_penalty(px, position.quantity, settings.liquidation_fee_rate)
        pnl = compute_trade_pnl(
            side=position.side, quantity=position.quantity, entry_price=position.entry_price, exit_price=px,
            entry_fee=position.entry_fee, exit_fee=fee, funding_paid=position.funding,
        )
        settlement = accounting.settle_close(balance, pnl.gross_pnl, fee)   # a shortfall is recorded, never hidden
        balance = settlement.new_balance
        total_bad_debt += settlement.bad_debt
        trades.append(BacktestTrade(
            side=position.side, entry_index=position.entry_index, exit_index=at_index, entry_price=position.entry_price,
            exit_price=px, quantity=position.quantity, net_pnl=pnl.net_pnl, exit_reason=reason,
            fee=position.entry_fee + fee, slippage_cost=position.entry_slippage_cost + abs(px - ref) * position.quantity,
            entry_regime=position.entry_regime, exit_regime=regime, funding=position.funding, bad_debt=settlement.bad_debt,
        ))
        bars = accounting.cooldown_bars_after(dna, pnl.net_pnl)
        if bars:
            # an exit in bar X blocks entry signals for bars X .. X+bars-1 (same rule as the live loop)
            cooldown_until_index = at_index + bars
        pos = None
        if reason == "liquidation" and settings.liquidation_is_fatal:
            dead = True
        if balance <= max(0.0, starting_equity * settings.agent_bankruptcy_equity_fraction):
            dead = True

    last_processed = first
    for i in range(first, last):
        last_processed = i
        ctx = data.contexts[i]
        if ctx is None:
            continue
        flat = data.flat[i] or {}
        bar_open, bar_high, bar_low, bar_close = data.open[i], data.high[i], data.low[i], data.close[i]
        bar = Bar(bar_open, bar_high, bar_low, bar_close)
        bar_dt = datetime.fromtimestamp(int(data.open_time[i]) / 1000, tz=timezone.utc)
        if day_start_date != bar_dt.date():
            day_start_equity = balance if pos is None else balance + _upnl(pos, bar_open)
            day_start_date = bar_dt.date()
            daily_trades = 0
        regime = ctx.regime.regime.value

        # ---- (a) manage the open position on THIS bar ------------------------- #
        exited_this_bar = False
        if pos is not None and pos.entry_index <= i:
            bar_close_ms = int(data.open_time[i]) + interval_ms - 1
            for settle_ms, rate in funding_events:
                if pos.last_funding_ms < settle_ms <= bar_close_ms:
                    payment = accounting.funding_payment(pos.side, pos.quantity, bar_close, rate)
                    balance -= payment
                    pos.funding += payment
                    total_funding += payment
                    pos.last_funding_ms = settle_ms
            liq = compute_liquidation_price(side=pos.side, entry_price=pos.entry_price, quantity=pos.quantity,
                                            balance=balance, maintenance_margin_rate=mmr)
            levels = PositionLevels(
                side=pos.side, entry_price=pos.entry_price, stop_loss_price=pos.stop, take_profit_price=pos.tp,
                trailing_distance=pos.trail_distance,
                trailing_activation_pct=dna.trailing_stop.activation_pct if dna.trailing_stop.enabled else 0.0,
                trailing_active=pos.trailing_active, peak_price=pos.peak, trough_price=pos.trough, liquidation_price=liq,
            )
            trig = evaluate_bar(levels, bar, same_bar_extreme=settings.trailing_stop_uses_same_bar_extreme)
            if trig is not None:
                close(pos, trig.reference_price, trig.order_kind, trig.exit_reason, i, regime)
                exited_this_bar = True
            else:
                pos.peak, pos.trough, pos.trailing_active = advance_extremes(levels, bar)
                st = margin_state(balance=balance, maintenance_margin_rate=mmr, side=pos.side, quantity=pos.quantity,
                                  entry_price=pos.entry_price, mark_price=bar_close)
                if st.liquidatable:
                    close(pos, bar_close, "liquidation", "liquidation", i, regime)
                    exited_this_bar = True

        if dead:
            equity_curve.append(max(0.0, balance))
            break

        # ---- (b) signal at this bar's close ---------------------------------- #
        prev_flat = data.flat[i - 1] if i > 0 else None
        current = dict(flat)
        previous = dict(prev_flat) if prev_flat else {}
        for key in dyn_keys:
            v = data.dyn[key][i]
            if not np.isnan(v):
                current[key] = float(v)
            if i > 0:
                pv = data.dyn[key][i - 1]
                if not np.isnan(pv):
                    previous[key] = float(pv)
        view = FeatureView(current, previous, ctx.regime.regime, ctx.regime.confidence)
        signal = evaluate_signal(dna, view, position_side=pos.side if pos is not None else None)

        fill_idx = min(i + 1 + execution_delay_bars, n - 1)
        next_open = float(data.open[fill_idx]) if i + 1 < n else bar_close

        # ---- (c) signal exit fills at the NEXT open --------------------------- #
        if pos is not None and not exited_this_bar and signal.matched_exit and pos.entry_index <= i:
            close(pos, next_open, "market", "signal", fill_idx, regime)

        # ---- (d) entry fills at the NEXT open --------------------------------- #
        elif pos is None and not exited_this_bar and signal.matched_entry and i + 1 < last and not dead:
            if i < cooldown_until_index or daily_trades >= dna.max_trades_per_day:
                pass
            else:
                side = Side.LONG if signal.bias == Bias.LONG else Side.SHORT
                atr = ctx.volatility.atr_14
                # Sizing/risk are priced at the signal bar's CLOSE (the only price known at decision time); the
                # quantity is converted at the fill price below.
                sl_pct = stop_distance_pct(dna, bar_close, atr, ctx.structure.swing_low, ctx.structure.swing_high,
                                           side == Side.LONG)
                eq_now = balance
                if fraction is not None:
                    from app.schemas.strategy_dna import PositionSizing
                    sizing_dna = dna.model_copy(update={"position_sizing": PositionSizing(
                        method=dna.position_sizing.method, fraction_of_equity=fraction, max_notional=dna.position_sizing.max_notional)})
                else:
                    sizing_dna = dna
                notional = requested_notional(sizing_dna, equity=eq_now, price=bar_close, atr=atr, stop_dist_pct=sl_pct)
                leverage = dna.leverage_limit
                if enforce_risk_engine:
                    notional = backtest_risk_check(
                        dna=dna, side=side, proposed_notional=notional, proposed_leverage=leverage, current_price=bar_close,
                        atr=atr, equity=eq_now, peak_equity=peak_equity, starting_equity=starting_equity,
                        day_start_equity=day_start_equity, global_max_leverage=global_max_leverage,
                        global_max_position_size=global_max_position_size, global_max_drawdown=global_max_drawdown,
                        global_max_daily_loss=global_max_daily_loss, stop_distance_pct=sl_pct if dna.stop_loss.enabled else None,
                    )
                    leverage = min(leverage, dna.risk_profile.max_leverage, global_max_leverage)
                notional = approve_against_margin(notional, leverage=max(leverage, 1e-9), available_margin=eq_now)
                qty = (notional * max(0.0, min(1.0, fill_fraction))) / next_open if next_open > 0 else 0.0
                if entry_reject_probability and rng is not None and rng.random() < entry_reject_probability:
                    qty = 0.0  # order rejected / lost in an unknown state: no position, no fee
                step = settings.paper_quantity_step
                if step > 0:
                    qty = int(qty / step + 1e-9) * step
                # Initiative 1 Phase 1.2 (LIVE_BACKTEST_PARITY_PLAN.md): was a hand-written
                # duplicate of this exact rule; now the same shared function the paper adapter's
                # decision-time check uses. `qty` is already lot-rounded (above), so this passes
                # its own already-rounded notional straight through - below_min_order_notional's
                # internal re-rounding is idempotent on an already-rounded quantity.
                if qty > 0 and not below_min_order_notional(qty * next_open, next_open):
                    fill = slip("market", next_open, side, qty * next_open, False)
                    entry_fee = fill * qty * fee_rate
                    slip_cost = abs(fill - next_open) * qty
                    lv = accounting.entry_levels(dna, side, fill, atr=atr, swing_low=ctx.structure.swing_low,
                                                 swing_high=ctx.structure.swing_high)
                    balance -= entry_fee
                    pos = _Pos(
                        side=side, entry_index=fill_idx, entry_price=fill, quantity=qty, entry_fee=entry_fee,
                        entry_slippage_cost=slip_cost, entry_regime=regime, stop=lv.stop_loss, tp=lv.take_profit,
                        trail_distance=lv.trailing_distance, trailing_active=lv.trailing_active, peak=fill, trough=fill,
                        last_funding_ms=int(data.open_time[i]) + interval_ms - 1,
                    )
                    daily_trades += 1

        # ---- (e) mark-to-market equity ---------------------------------------- #
        equity = balance + (_upnl(pos, bar_close) if pos is not None and pos.entry_index <= i else 0.0)
        equity_curve.append(equity)
        peak_equity = max(peak_equity, equity)
        if equity <= 0:
            dead = True
            break

    # Close anything still open at the last processed close (clean trade stats).
    if pos is not None and not dead:
        idx = min(last, n) - 1
        if idx >= 0:
            last_ctx = data.contexts[idx]
            close(pos, float(data.close[idx]), "market", "end_of_data", idx, last_ctx.regime.regime.value if last_ctx else None)
            if equity_curve:
                equity_curve[-1] = balance

    return BacktestResult(
        equity_curve=equity_curve, trades=trades, final_equity=balance, starting_equity=starting_equity,
        dead=dead, total_funding=total_funding, total_bad_debt=total_bad_debt,
        first_bar_open_ms=int(data.open_time[first]) if first < n else None,
        last_bar_open_ms=int(data.open_time[min(last_processed, n - 1)]) if first < n else None,
        bars_simulated=max(0, min(last_processed, n - 1) - first + 1), interval_ms=interval_ms,
    )


def _upnl(pos: _Pos, price: float) -> float:
    return (price - pos.entry_price) * pos.quantity * (1 if pos.side == Side.LONG else -1)
