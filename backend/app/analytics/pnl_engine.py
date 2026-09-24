"""PnL engine (spec section 20). Profitability is never computed from raw
price difference alone — fees, funding, and slippage are always accounted.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Side


@dataclass
class TradePnL:
    gross_pnl: float
    fees: float
    funding: float
    slippage_cost: float
    net_pnl: float


def compute_trade_pnl(
    *,
    side: Side,
    quantity: float,
    entry_price: float,
    exit_price: float,
    entry_fee: float,
    exit_fee: float,
    funding_paid: float,
    slippage_cost: float = 0.0,
) -> TradePnL:
    direction = 1 if side == Side.LONG else -1
    gross_pnl = (exit_price - entry_price) * quantity * direction
    fees = entry_fee + exit_fee
    # `slippage_cost` is INFORMATIONAL: fills already happen at slipped prices,
    # so gross_pnl already contains it. Subtracting it again (as an earlier
    # version did) double-counts and makes trade-level PnL disagree with agent
    # equity. Net = gross - fees - funding, always.
    net_pnl = gross_pnl - fees - funding_paid
    return TradePnL(
        gross_pnl=gross_pnl,
        fees=fees,
        funding=funding_paid,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
    )


def compute_unrealized_pnl(*, side: Side, quantity: float, entry_price: float, current_price: float) -> float:
    direction = 1 if side == Side.LONG else -1
    return (current_price - entry_price) * quantity * direction


def compute_liquidation_price(
    *, side: Side, entry_price: float, quantity: float, balance: float, maintenance_margin_rate: float
) -> float | None:
    """Cross-margin (single position) liquidation price: the mark at which
    `balance + unrealized PnL == maintenance_margin_rate * mark * quantity`.

        LONG : P = (q*E - balance) / (q * (1 - mmr))
        SHORT: P = (balance + q*E) / (q * (1 + mmr))

    Returns None when the position can never be liquidated (e.g. a fully
    collateralised long: P <= 0)."""
    if quantity <= 0:
        return None
    if side == Side.LONG:
        price = (quantity * entry_price - balance) / (quantity * (1 - maintenance_margin_rate))
        return price if price > 0 else None
    return (balance + quantity * entry_price) / (quantity * (1 + maintenance_margin_rate))
