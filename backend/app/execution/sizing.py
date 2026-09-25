"""Position sizing (spec phase 6): pure, deterministic, unit-tested.

Supported DNA methods (aliases accepted, see NORMALIZED):
  fraction_of_equity  margin = equity * fraction;   notional = margin * leverage
  fixed_notional      notional = max_notional (or equity*fraction*leverage if unset)
  risk_based          risk   = equity * fraction;   notional = risk / stop_distance_pct
  volatility_based    like fraction_of_equity, scaled by target_atr% / current_atr%

The DNA's `leverage_limit` is the sizing leverage; the Risk Engine then clamps
notional and leverage to the DNA/global limits, and `approve_against_margin`
caps the order by the agent's AVAILABLE margin. Every order records
requested_notional, approved_notional, margin, leverage, quantity, risk_amount.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.config import get_settings
from app.schemas.strategy_dna import StrategyDNA

NORMALIZED = {
    "fixed_fraction": "fraction_of_equity",
    "fraction_of_equity": "fraction_of_equity",
    "fixed_notional": "fixed_notional",
    "kelly_fraction": "risk_based",
    "risk_based": "risk_based",
    "volatility_scaled": "volatility_based",
    "volatility_based": "volatility_based",
}

MIN_STOP_DISTANCE_PCT = 0.0005  # 5 bps: floor so tiny stops cannot explode size


def normalize_method(method: str) -> str:
    return NORMALIZED[method]


@dataclass(frozen=True)
class SizingResult:
    method: str
    requested_notional: float
    approved_notional: float
    margin: float
    leverage: float
    quantity: float
    risk_amount: float


def stop_distance_pct(dna: StrategyDNA, price: float, atr: float, swing_low: float | None = None,
                      swing_high: float | None = None, side_is_long: bool = True) -> float:
    """Fractional distance from entry to the protective stop (matches the stop actually placed)."""
    if not dna.stop_loss.enabled or price <= 0:
        return 1.0  # no stop => the whole notional is at risk
    method = dna.stop_loss.method
    if method == "atr_multiple":
        return max(atr * dna.stop_loss.value / price, MIN_STOP_DISTANCE_PCT)
    if method == "structure_based":
        level = swing_low if side_is_long else swing_high
        if level is not None and level > 0:
            dist = (price - level) if side_is_long else (level - price)
            if dist > 0:
                return max(dist / price, MIN_STOP_DISTANCE_PCT)
        return max(atr * dna.stop_loss.value / price, MIN_STOP_DISTANCE_PCT)  # fallback: ATR multiple
    return max(dna.stop_loss.value / 100, MIN_STOP_DISTANCE_PCT)


def requested_notional(dna: StrategyDNA, *, equity: float, price: float, atr: float, stop_dist_pct: float) -> float:
    """What the DNA wants, before risk clamps. Never negative."""
    settings = get_settings()
    sizing = dna.position_sizing
    method = normalize_method(sizing.method)
    lev = dna.leverage_limit
    if equity <= 0 or price <= 0:
        return 0.0
    if method == "fixed_notional":
        return max(0.0, sizing.max_notional if sizing.max_notional else equity * sizing.fraction_of_equity * lev)
    if method == "risk_based":
        risk = equity * sizing.fraction_of_equity
        return max(0.0, min(risk / max(stop_dist_pct, MIN_STOP_DISTANCE_PCT), equity * lev))
    base = equity * sizing.fraction_of_equity * lev
    if method == "volatility_based":
        atr_pct = atr / price if price else 0.0
        scale = settings.sizing_vol_target_atr_pct / atr_pct if atr_pct > 0 else 1.0
        scale = max(settings.sizing_vol_scale_min, min(settings.sizing_vol_scale_max, scale))
        return max(0.0, base * scale)
    return max(0.0, base)  # fraction_of_equity


def approve_against_margin(approved_notional: float, *, leverage: float, available_margin: float) -> float:
    """Caps notional so required margin never exceeds AVAILABLE margin —
    equity being positive is not enough to justify unlimited exposure."""
    if leverage <= 0:
        return 0.0
    return max(0.0, min(approved_notional, available_margin * leverage))


def below_min_order_notional(notional: float, price: float) -> bool:
    """True when an ENTRY of `notional` at `price` would be refused by the exchange minimum. Mirrors the paper
    adapter exactly (quantity floored to the lot step, then quantity * price against `paper_min_order_notional`), so
    the decision and the later fill can never disagree and a doomed order is never persisted."""
    settings = get_settings()
    if not settings.paper_min_order_notional:
        return False
    if price <= 0:
        return True
    quantity = notional / price
    step = settings.paper_quantity_step
    if step > 0:
        quantity = math.floor(quantity / step + 1e-9) * step
    return quantity * price < settings.paper_min_order_notional


def build_sizing_result(
    *, method: str, requested: float, approved: float, leverage: float, price: float, stop_dist_pct: float
) -> SizingResult:
    quantity = approved / price if price > 0 else 0.0
    return SizingResult(
        method=normalize_method(method),
        requested_notional=requested,
        approved_notional=approved,
        margin=approved / leverage if leverage > 0 else 0.0,
        leverage=leverage,
        quantity=quantity,
        risk_amount=approved * min(stop_dist_pct, 1.0),
    )
