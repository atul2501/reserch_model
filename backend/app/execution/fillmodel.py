"""The ONE cost model shared by the paper adapter, shadow estimates and the
backtester — so the reality gap measures execution differences, never two
different hand-written formulas."""
from __future__ import annotations

from app.models.enums import Side


def slippage_bps(
    order_kind: str, notional: float, *, base_bps: float, impact_bps_per_10k: float = 0.0, stop_multiplier: float = 1.0
) -> float:
    """Adverse slippage in bps. Resting take-profit limit orders pay none;
    stops and liquidations execute into a moving market and slip more."""
    if order_kind == "take_profit":
        return 0.0
    bps = base_bps + impact_bps_per_10k * (notional / 10_000)
    if order_kind in ("stop", "liquidation"):
        bps *= stop_multiplier
    return bps


def slipped_price(reference: float, side: Side, *, reduce_only: bool, bps: float) -> float:
    """`side` is the ORDER's position side: entering LONG buys (pay up),
    entering SHORT sells (receive less); closing LONG sells, closing SHORT buys."""
    direction = 1 if side == Side.LONG else -1
    adverse = direction if not reduce_only else -direction
    return reference * (1 + adverse * bps / 10_000)


def fee_rate_for(order_kind: str, *, taker: float, maker: float) -> float:
    return maker if order_kind == "take_profit" else taker
