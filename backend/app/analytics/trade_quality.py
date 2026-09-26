"""Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.

No database, no trading-engine imports (enforced by tests/test_analytics_isolation.py):
everything here is a deterministic function of the facts passed in. The DB half
lives in app/analytics/analytics_store.py.

REPLAY SEMANTICS (derived from the live loop's own bar management — see
app/agents/decision_loop.py::_manage_position_bar):

* A position fills at the OPEN of its entry bar (`positions.entry_candle_open_time`),
  with peak/trough initialised to the fill price.
* Every bar is then managed in order: if an exit triggers ON bar K the position
  closes at K's close and its persisted extremes cover [entry_bar .. K-1]; if it
  survives, advance_extremes folds K's high/low in.
* A signal exit decided on bar K's close fills at bar K+1's open, so the persisted
  extremes cover [entry_bar .. K] = [entry_bar .. exit_bar-1].

So for BOTH exit kinds: persisted peak/trough == replay over
[entry_bar, exit_bar) — that is the cross-check window. The ANALYTICAL excursion
window additionally INCLUDES the exit bar (the favourable extreme of the bar that
stopped you out is real movement that happened before/during the exit, and
left-on-table analysis needs it). Within the exit bar the engine's own
conservative rule applies: the adverse level is assumed reached BEFORE the
favourable one.

Only confirmed candles (is_final) may be passed in — the caller enforces it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Classification thresholds (versioned via TradeAnalytics.computation_version).
REVERSAL_MFE_R = 1.0          # a loss that had been >= +1R in profit
STOP_IMMEDIATE_MAE_R = 0.8    # ... before the trade ever reached +MFE_FLOOR_R
MFE_FLOOR_R = 0.25            # "the trade went somewhere"
MFE_BEFORE_MAE_R = 0.25       # threshold for the first-touch ordering flag
MAE_BEFORE_MFE_R = 0.8
POST_EXIT_BARS = 30
_PRICE_TOL = 1e-9

# trade_quality_class values (mutually exclusive; first match wins in classify())
TAKE_PROFIT_HIT = "TAKE_PROFIT_HIT"
TRAILING_CAPTURED = "TRAILING_CAPTURED"
ROLLOVER = "ROLLOVER"
LIQUIDATED = "LIQUIDATED"
COST_EATEN = "COST_EATEN"
STOP_IMMEDIATE = "STOP_IMMEDIATE"
REVERSAL_AFTER_PROFIT = "REVERSAL_AFTER_PROFIT"
STOP_LOSS_OTHER = "STOP_LOSS_OTHER"
SIGNAL_EXIT_WIN = "SIGNAL_EXIT_WIN"
SIGNAL_EXIT_LOSS = "SIGNAL_EXIT_LOSS"
OTHER = "OTHER"


@dataclass(frozen=True)
class Bar:
    open_time: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class TradeFacts:
    side: str                      # "LONG" | "SHORT"
    entry_price: float
    exit_price: float
    quantity: float
    opened_at_ms: int
    closed_at_ms: int
    stop_loss_price: float | None
    take_profit_price: float | None
    persisted_peak_price: float | None   # positions.peak_price (max high, side-agnostic)
    persisted_trough_price: float | None  # positions.trough_price (min low, side-agnostic)
    entry_bar_open_ms: int | None         # positions.entry_candle_open_time
    exit_reason: str


@dataclass(frozen=True)
class ExcursionResult:
    # side-adjusted excursion prices, floored at the entry price (a trade starts at 0 excursion)
    mfe_price: float
    mae_price: float
    mfe_time_ms: int                # first bar whose extreme reached the final MFE price
    mae_time_ms: int
    time_to_mfe_seconds: int
    time_to_mae_seconds: int
    mfe_r: float | None             # None when there is no stop => no R basis
    mae_r: float | None
    mfe_bps: float
    mae_bps: float
    max_unrealized_profit: float    # >= 0, account currency
    max_unrealized_loss: float      # <= 0, account currency
    mfe_before_mae: bool | None     # True/False once both thresholds are orderable; None otherwise
    post_exit_mfe_bps: float | None
    post_exit_mae_bps: float | None
    left_on_table_r: float | None   # favourable movement AFTER the exit, in R; >= 0
    replay_peak: float | None       # replay over [entry_bar, exit_bar) — the cross-check values
    replay_trough: float | None
    peak_crosscheck_ok: bool | None     # None = not computable (no candles / no persisted value)
    trough_crosscheck_ok: bool | None
    exit_bar_open_ms: int | None


def _is_long(side: str) -> bool:
    return str(side).upper() == "LONG"


def _risk(quantity: float, entry_price: float, stop: float | None) -> float | None:
    if stop is None:
        return None
    risk = quantity * abs(entry_price - stop)
    return risk if risk > 0 else None


def _pnl(side: str, quantity: float, from_price: float, to_price: float) -> float:
    """Signed PnL of a LONG/SHORT position between two prices (no costs)."""
    direction = 1.0 if _is_long(side) else -1.0
    return (to_price - from_price) * quantity * direction


def analyze_trade(facts: TradeFacts, bars: Sequence[Bar], bar_ms: int) -> ExcursionResult:
    """Replay one closed trade over its confirmed bars.

    `bars` must be the candles from the entry bar through the exit bar plus
    POST_EXIT_BARS after it, sorted by open_time (the caller slices; extra bars
    on either side are harmless — the window is derived from the facts).
    """
    long = _is_long(facts.side)
    quantity = facts.quantity
    entry = facts.entry_price
    opened = facts.opened_at_ms
    risk = _risk(quantity, entry, facts.stop_loss_price)

    # ---- window boundaries ------------------------------------------------- #
    entry_bar = facts.entry_bar_open_ms
    if entry_bar is None:  # defensive: fall back to the bar containing the fill
        entry_bar = next((b.open_time for b in bars if b.open_time <= opened < b.open_time + bar_ms), None)
    exit_bar = None
    for b in bars:
        if b.open_time <= facts.closed_at_ms:
            exit_bar = b.open_time
        else:
            break
    # candles through closed_at (largest open_time <= closed_at_ms)

    if entry_bar is None or exit_bar is None:
        # No candle coverage for this trade: excursions are the entry itself and
        # the cross-check is skipped (NULL, reported by the store as a finding).
        return ExcursionResult(
            mfe_price=entry, mae_price=entry, mfe_time_ms=opened, mae_time_ms=opened,
            time_to_mfe_seconds=0, time_to_mae_seconds=0,
            mfe_r=None, mae_r=None, mfe_bps=0.0, mae_bps=0.0,
            max_unrealized_profit=0.0, max_unrealized_loss=0.0, mfe_before_mae=None,
            post_exit_mfe_bps=None, post_exit_mae_bps=None, left_on_table_r=None,
            replay_peak=None, replay_trough=None, peak_crosscheck_ok=None, trough_crosscheck_ok=None,
            exit_bar_open_ms=exit_bar,
        )

    managed = [b for b in bars if entry_bar <= b.open_time < exit_bar]      # the persisted-extremes window
    full = [b for b in bars if entry_bar <= b.open_time <= exit_bar]        # the analytical window
    post = [b for b in bars if b.open_time > exit_bar][:POST_EXIT_BARS]     # after the exit fill

    # ---- side-adjusted excursion extremes (inclusive of the exit bar) ----- #
    highs = [b.high for b in full]
    lows = [b.low for b in full]
    if long:
        mfe_price = max([entry, *highs])       # favourable for a long = the highest price
        mae_price = min([entry, *lows])       # adverse for a long = the lowest price
    else:
        mfe_price = min([entry, *lows])       # favourable for a short = the lowest price
        mae_price = max([entry, *highs])      # adverse for a short = the highest price
    max_unrealized_profit = max(0.0, _pnl(facts.side, quantity, entry, mfe_price))
    max_unrealized_loss = min(0.0, _pnl(facts.side, quantity, entry, mae_price))
    notional = quantity * entry
    mfe_bps = (max_unrealized_profit / notional * 1e4) if notional > 0 else 0.0
    mae_bps = (max_unrealized_loss / notional * 1e4) if notional > 0 else 0.0
    mfe_r = (max_unrealized_profit / risk) if risk else None
    mae_r = (max_unrealized_loss / risk) if risk else None

    # ---- first touch of the FINAL extreme ----------------------------------- #
    mfe_time = opened
    mae_time = opened
    for b in full:
        if mfe_time == opened and mfe_price != entry and (b.high if long else b.low) == mfe_price:
            mfe_time = b.open_time
        if mae_time == opened and mae_price != entry and (b.low if long else b.high) == mae_price:
            mae_time = b.open_time
        if mfe_time != opened and mae_time != opened:
            break

    # ---- threshold ordering (conservative same-bar rule: adverse first) ----- #
    mfe_before_mae: bool | None = None
    if risk:
        fav_t = adv_t = None
        for b in full:
            fav_hit = (b.high - entry) if long else (entry - b.low)
            adv_hit = (entry - b.low) if long else (b.high - entry)
            fav = fav_hit * quantity / risk >= MFE_BEFORE_MAE_R
            adv = adv_hit * quantity / risk >= MAE_BEFORE_MFE_R
            if adv:
                adv_t = b.open_time
                if fav:            # same bar: the engine assumes the adverse level came first
                    fav_t = fav_t or b.open_time
                break
            if fav:
                fav_t = b.open_time
        if fav_t is not None or adv_t is not None:
            mfe_before_mae = adv_t is None or (fav_t is not None and fav_t < adv_t)

    # ---- post-exit window --------------------------------------------------- #
    # Side-aware: for a SHORT the favourable excursion is the LOWEST post-exit price,
    # the adverse one the highest (mirror of the during-trade windows).
    post_mfe_bps = post_mae_bps = None
    left_on_table = None
    if post:
        if long:
            fav_px = max([facts.exit_price, *(b.high for b in post)])
            adv_px = min([facts.exit_price, *(b.low for b in post)])
        else:
            fav_px = min([facts.exit_price, *(b.low for b in post)])
            adv_px = max([facts.exit_price, *(b.high for b in post)])
        fav_pnl = max(0.0, _pnl(facts.side, quantity, facts.exit_price, fav_px))
        adv_pnl = min(0.0, _pnl(facts.side, quantity, facts.exit_price, adv_px))
        post_notional = quantity * facts.exit_price
        post_mfe_bps = (fav_pnl / post_notional * 1e4) if post_notional > 0 else 0.0
        post_mae_bps = (adv_pnl / post_notional * 1e4) if post_notional > 0 else 0.0
        left_on_table = (fav_pnl / risk) if risk else None

    # ---- cross-check against the persisted extremes ------------------------- #
    replay_peak = max([entry, *(b.high for b in managed)]) if managed else entry
    replay_trough = min([entry, *(b.low for b in managed)]) if managed else entry
    tol = max(_PRICE_TOL, _PRICE_TOL * abs(entry))

    def _ok(persisted: float | None, replayed: float) -> bool | None:
        if persisted is None:
            return None
        return abs(persisted - replayed) <= max(tol, _PRICE_TOL * abs(replayed))

    return ExcursionResult(
        mfe_price=mfe_price, mae_price=mae_price, mfe_time_ms=mfe_time, mae_time_ms=mae_time,
        time_to_mfe_seconds=max(0, (mfe_time - opened) // 1000),
        time_to_mae_seconds=max(0, (mae_time - opened) // 1000),
        mfe_r=mfe_r, mae_r=mae_r, mfe_bps=mfe_bps, mae_bps=mae_bps,
        max_unrealized_profit=max_unrealized_profit, max_unrealized_loss=max_unrealized_loss,
        mfe_before_mae=mfe_before_mae, post_exit_mfe_bps=post_mfe_bps, post_exit_mae_bps=post_mae_bps,
        left_on_table_r=left_on_table, replay_peak=replay_peak, replay_trough=replay_trough,
        peak_crosscheck_ok=_ok(facts.persisted_peak_price, replay_peak),
        trough_crosscheck_ok=_ok(facts.persisted_trough_price, replay_trough),
        exit_bar_open_ms=exit_bar,
    )


def classify_trade(facts: TradeFacts, ex: ExcursionResult, *, gross_pnl: float, net_pnl: float) -> str:
    """BAD SIGNAL vs BAD TIMING vs BAD STOP vs BAD TP vs EXECUTION vs COSTS —
    as one mutually-exclusive label per trade (first match wins)."""
    reason = facts.exit_reason
    mfe_r = ex.mfe_r
    mae_r = ex.mae_r

    if reason == "generation_rollover":
        return ROLLOVER
    if reason == "liquidation" or reason.startswith("liquidation"):
        return LIQUIDATED
    if reason == "take_profit":
        return TAKE_PROFIT_HIT
    if reason == "trailing_stop":
        return TRAILING_CAPTURED
    if gross_pnl > 0 and net_pnl <= 0:
        return COST_EATEN
    if reason == "stop_loss" and mfe_r is not None and mae_r is not None:
        # never went anywhere before going bad (or went adverse first): a different failure
        # from a trade that reached >= +1R and then gave it all back.
        went_nowhere = ex.mfe_before_mae is False or mfe_r < MFE_FLOOR_R
        if mae_r <= -STOP_IMMEDIATE_MAE_R and went_nowhere:
            return STOP_IMMEDIATE
        if mfe_r >= REVERSAL_MFE_R and net_pnl < 0:
            return REVERSAL_AFTER_PROFIT
        return STOP_LOSS_OTHER
    if reason in ("exit_rules", "signal_reversal"):
        return SIGNAL_EXIT_WIN if net_pnl > 0 else SIGNAL_EXIT_LOSS
    return OTHER