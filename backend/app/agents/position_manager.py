"""Open-position management on every confirmed bar (spec phases 8-11).

Order of operations per bar for an agent with an open position:

    funding accrual -> protective evaluation (liquidation / stop / trailing /
    take-profit, on the bar's OHLC) -> exit through the ExecutionEngine ->
    PnL -> mark-to-market (only if the position survived)

OHLC-ambiguity assumptions (deliberately CONSERVATIVE; documented in
docs/architecture.md, tested in tests/test_stops_trailing.py):

  1. The intrabar path is unknown, so ADVERSE levels are assumed reachable
     before FAVORABLE ones: if a bar touches both the stop and the take-profit,
     the STOP is taken.
  2. Among adverse levels (liquidation, stop, trailing) the one reached first
     going against the position (nearest to the open) wins.
  3. GAPS: if the bar OPENS beyond an adverse level, the exit fills at the
     OPEN (worse than the level), never at the level. A take-profit limit
     fills at its level (no price improvement is credited on a gap up).
  4. Trailing stops trail the peak/trough. With `same_bar_extreme=True` (the
     research default, settings.trailing_stop_uses_same_bar_extreme) the
     current bar's own extreme counts: a bar that both extends the peak and
     trades back through the resulting stop is assumed to have rallied FIRST
     (the worst case for the trade, consistent with rule 1). With False only
     PRIOR bars' peak counts (optimistic: a stop can never tighten within the
     bar that produced the rally). Trailing only arms once price has moved
     `activation_pct` in favour.
  5. Exits are reduce-only orders: stops/liquidations slip more than markets,
     take-profit limits pay no slippage and the maker fee.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.enums import Side


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PositionLevels:
    side: Side
    entry_price: float
    stop_loss_price: float | None
    take_profit_price: float | None
    trailing_distance: float | None        # absolute price distance
    trailing_activation_pct: float         # 0 => armed from entry
    trailing_active: bool
    peak_price: float | None               # prior bars only
    trough_price: float | None
    liquidation_price: float | None


@dataclass(frozen=True)
class ProtectiveTrigger:
    exit_reason: str      # liquidation | stop_loss | trailing_stop | take_profit
    order_kind: str       # liquidation | stop | take_profit
    trigger_price: float
    reference_price: float  # where the fill starts, before slippage (gap-aware)


_PRIORITY = {"liquidation": 0, "stop_loss": 1, "trailing_stop": 2}


def trailing_is_active(levels: PositionLevels) -> bool:
    if levels.trailing_distance is None or levels.trailing_distance <= 0:
        return False
    if levels.trailing_active or levels.trailing_activation_pct <= 0:
        return True
    if levels.side == Side.LONG:
        return levels.peak_price is not None and levels.peak_price >= levels.entry_price * (1 + levels.trailing_activation_pct / 100)
    return levels.trough_price is not None and levels.trough_price <= levels.entry_price * (1 - levels.trailing_activation_pct / 100)


def evaluate_bar(levels: PositionLevels, bar: Bar, *, same_bar_extreme: bool = False) -> ProtectiveTrigger | None:
    long = levels.side == Side.LONG
    adverse: list[tuple[str, float]] = []
    if same_bar_extreme:
        # Conservative path assumption: the bar's favourable extreme happened before its adverse one.
        levels = PositionLevels(**{**levels.__dict__,
                                   "peak_price": max(levels.peak_price if levels.peak_price is not None else levels.entry_price, bar.high),
                                   "trough_price": min(levels.trough_price if levels.trough_price is not None else levels.entry_price, bar.low)})

    def hit(level: float) -> bool:
        return bar.low <= level if long else bar.high >= level

    if levels.liquidation_price is not None and hit(levels.liquidation_price):
        adverse.append(("liquidation", levels.liquidation_price))
    if levels.stop_loss_price is not None and hit(levels.stop_loss_price):
        adverse.append(("stop_loss", levels.stop_loss_price))
    if trailing_is_active(levels):
        anchor = levels.peak_price if long else levels.trough_price
        distance = levels.trailing_distance
        if anchor is not None and distance is not None:
            trig = anchor - distance if long else anchor + distance
            if hit(trig):
                adverse.append(("trailing_stop", trig))

    if adverse:
        # First reached going against the position: highest level for a long, lowest for a short.
        adverse.sort(key=lambda t: ((-t[1] if long else t[1]), _PRIORITY[t[0]]))
        reason, level = adverse[0]
        gapped = bar.open <= level if long else bar.open >= level
        reference = bar.open if gapped else level
        return ProtectiveTrigger(reason, "liquidation" if reason == "liquidation" else "stop", level, reference)

    tp = levels.take_profit_price
    if tp is not None and ((bar.high >= tp) if long else (bar.low <= tp)):
        return ProtectiveTrigger("take_profit", "take_profit", tp, tp)
    return None


def advance_extremes(levels: PositionLevels, bar: Bar) -> tuple[float, float, bool]:
    """Peak/trough AFTER this bar, and whether trailing is now armed."""
    peak = max(levels.peak_price if levels.peak_price is not None else levels.entry_price, bar.high)
    trough = min(levels.trough_price if levels.trough_price is not None else levels.entry_price, bar.low)
    updated = PositionLevels(**{**levels.__dict__, "peak_price": peak, "trough_price": trough})
    return peak, trough, trailing_is_active(updated)


def stop_price(entry: float, side: Side, *, method: str, value: float, atr: float, swing_low: float | None,
               swing_high: float | None) -> float | None:
    long = side == Side.LONG
    if method == "atr_multiple":
        dist = atr * value
    elif method == "structure_based":
        level = swing_low if long else swing_high
        if level is not None and ((level < entry) if long else (level > entry)):
            return level
        dist = atr * value  # no valid structure level -> ATR fallback
    else:
        dist = entry * value / 100
    return entry - dist if long else entry + dist


def take_profit_price(entry: float, side: Side, *, method: str, value: float, atr: float, stop: float | None) -> float:
    if method == "atr_multiple":
        dist = atr * value
    elif method == "risk_reward_multiple" and stop is not None:
        dist = abs(entry - stop) * value
    else:
        dist = entry * value / 100
    return entry + dist if side == Side.LONG else entry - dist


def bar_time(open_time_ms: int) -> datetime:
    return datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
