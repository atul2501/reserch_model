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
    slippage_cost: float,
) -> TradePnL:
    direction = 1 if side == Side.LONG else -1
    gross_pnl = (exit_price - entry_price) * quantity * direction
    fees = entry_fee + exit_fee
    net_pnl = gross_pnl - fees - funding_paid - slippage_cost
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


def compute_liquidation_price(*, side: Side, entry_price: float, leverage: float, maintenance_margin_fraction: float = 0.005) -> float:
    """Approximate isolated-margin liquidation price. This is a simplified
    model for paper trading; live trading must query Hyperliquid's actual
    margin/liquidation calculation rather than rely on this approximation."""
    direction = 1 if side == Side.LONG else -1
    margin_fraction = (1 / leverage) - maintenance_margin_fraction
    return entry_price * (1 - direction * margin_fraction)
