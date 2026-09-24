"""The ONE implementation of position accounting (paper, shadow, backtest, walk-forward, rollover).

Before this module the decision loop, the backtest engine and `retire_generation` each carried their own copy of
funding accrual, close settlement, cooldown and entry-level setup - and each hid bad debt behind `max(0, ...)`.
They could (and did) diverge; now they all call the functions below.

Cash model (one cross-margin position per agent; `balance` is cash, margin is NOT deducted):

    entry:    balance -= entry_fee
    funding:  balance -= payment                      (payment > 0: the trader pays, < 0: the trader receives)
    close:    balance += gross_pnl - exit_fee         (exit_fee includes any liquidation penalty)

so for an agent with no open position

    balance == starting_balance + realized_pnl + bad_debt

where `realized_pnl` accumulates each trade's `net_pnl = gross - fees - funding` and `bad_debt` is the (non-negative)
amount by which a close would have pushed the balance BELOW zero - the exchange/insurance fund's loss. An account
can never owe more than it holds, so the balance is floored at 0, but the write-off is RECORDED (never silently
discarded), which keeps equity/PnL mathematically reconcilable even through a gap past the liquidation price.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.position_manager import stop_price, take_profit_price
from app.models.enums import Side
from app.schemas.strategy_dna import StrategyDNA

RECONCILIATION_TOLERANCE = 1e-6


def funding_payment(side: Side, quantity: float, mark_price: float, rate: float) -> float:
    """One funding settlement. Positive = the trader PAYS. A positive rate makes longs pay and shorts receive;
    a negative rate reverses it. Notional is marked at the settlement's bar close."""
    return quantity * mark_price * rate * (1 if side == Side.LONG else -1)


@dataclass(frozen=True)
class Settlement:
    new_balance: float
    bad_debt: float          # >= 0: the part of the loss the account could not cover


def settle_close(balance: float, gross_pnl: float, exit_fee: float) -> Settlement:
    """Applies a close to the cash balance without hiding a shortfall."""
    raw = balance + gross_pnl - exit_fee
    if raw >= 0:
        return Settlement(raw, 0.0)
    return Settlement(0.0, -raw)


def liquidation_penalty(exit_price: float, quantity: float, liquidation_fee_rate: float) -> float:
    return exit_price * quantity * liquidation_fee_rate


@dataclass(frozen=True)
class EntryLevels:
    stop_loss: float | None
    take_profit: float | None
    trailing_distance: float | None
    trailing_active: bool


def entry_levels(
    dna: StrategyDNA, side: Side, fill_price: float, *, atr: float, swing_low: float | None, swing_high: float | None
) -> EntryLevels:
    """Protective levels for a freshly opened position - the same numbers in paper, shadow and backtest."""
    sl = stop_price(fill_price, side, method=dna.stop_loss.method, value=dna.stop_loss.value, atr=atr,
                    swing_low=swing_low, swing_high=swing_high) if dna.stop_loss.enabled else None
    tp = take_profit_price(fill_price, side, method=dna.take_profit.method, value=dna.take_profit.value, atr=atr,
                           stop=sl) if dna.take_profit.enabled else None
    trail = (fill_price * dna.trailing_stop.trail_pct / 100
             if dna.trailing_stop.enabled and dna.trailing_stop.trail_pct > 0 else None)
    return EntryLevels(sl, tp, trail, bool(trail and dna.trailing_stop.activation_pct <= 0))


def cooldown_bars_after(dna: StrategyDNA | None, net_pnl: float) -> int:
    """Bars the agent must sit out after a close (0 with no DNA: e.g. an orphan being force-closed)."""
    if dna is None:
        return 0
    return dna.cooldown.bars_after_win if net_pnl >= 0 else dna.cooldown.bars_after_loss


def cooldown_expiry_ms(exit_bar_open_ms: int, bars: int, interval_ms: int) -> int | None:
    """An exit that executes in bar X blocks new entry SIGNALS for bars X .. X+bars-1; bar X+bars may signal again.
    Measured on the candle clock so paper, shadow and backtest agree on the exact bar."""
    if bars <= 0:
        return None
    return exit_bar_open_ms + bars * interval_ms


def reconcile(
    *, starting_balance: float, balance: float, realized_pnl: float, bad_debt: float,
    open_entry_fee: float = 0.0, open_funding: float = 0.0,
) -> float:
    """Residual of the cash identity (0.0 when the books balance).

        balance == starting + realized_pnl + bad_debt - (entry fee and funding already paid on the OPEN position)

    An open position's entry fee and funding have left the balance but only reach `realized_pnl` when it closes."""
    return balance - (starting_balance + realized_pnl + bad_debt - open_entry_fee - open_funding)
