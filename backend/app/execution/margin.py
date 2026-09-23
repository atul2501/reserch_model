"""Explicit margin model (spec phase 9): cross margin, one position per agent.

    equity            = balance + unrealized PnL
    used margin       = position initial margin (notional / leverage)
    maintenance margin= maintenance_margin_rate * mark notional
    available margin  = max(0, equity - used margin)
    liquidation       = equity <= maintenance margin

`balance` is cash (realized PnL and fees applied, margin NOT deducted), so
`equity` is the whole account. The paper engine liquidates an agent the
moment its simulated account meets the liquidation condition.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.pnl_engine import compute_liquidation_price, compute_unrealized_pnl
from app.models.enums import Side


@dataclass(frozen=True)
class MarginState:
    balance: float
    unrealized_pnl: float
    equity: float
    used_margin: float
    maintenance_margin: float
    available_margin: float
    liquidation_price: float | None
    liquidatable: bool


def margin_state(
    *,
    balance: float,
    maintenance_margin_rate: float,
    side: Side | None = None,
    quantity: float = 0.0,
    entry_price: float = 0.0,
    mark_price: float = 0.0,
    initial_margin: float = 0.0,
) -> MarginState:
    if side is None or quantity <= 0:
        return MarginState(balance, 0.0, balance, 0.0, 0.0, max(0.0, balance), None, False)
    upnl = compute_unrealized_pnl(side=side, quantity=quantity, entry_price=entry_price, current_price=mark_price)
    equity = balance + upnl
    maintenance = maintenance_margin_rate * mark_price * quantity
    liq_price = compute_liquidation_price(
        side=side, entry_price=entry_price, quantity=quantity, balance=balance,
        maintenance_margin_rate=maintenance_margin_rate,
    )
    return MarginState(
        balance=balance,
        unrealized_pnl=upnl,
        equity=equity,
        used_margin=initial_margin,
        maintenance_margin=maintenance,
        available_margin=max(0.0, equity - initial_margin),
        liquidation_price=liq_price,
        liquidatable=equity <= maintenance,
    )
