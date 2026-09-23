"""Strategy-family definitions: genuinely different runtime behaviour.

A StrategyDNA's rules say WHEN a setup exists; the family says WHICH WAY to
trade it (when the DNA does not pin a direction) and HOW STRONG the setup is.
The same market snapshot therefore yields different decisions per family —
e.g. a stretched uptrend: trend-following goes LONG, mean-reversion goes SHORT.

Every function is pure, deterministic and reads only the flat feature dict
(static MarketContext features + the dynamic indicators the DNA declared).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.models.enums import Bias, StrategyFamily

Features = dict


def _g(f: Features, *keys: str, default: float = 0.0) -> float:
    """First available numeric feature among `keys` (dynamic keys first)."""
    for k in keys:
        v = f.get(k)
        if v is not None and not isinstance(v, str):
            return float(v)
    return default


def _find(f: Features, prefix: str) -> float | None:
    """Value of the first dynamic feature whose key starts with `prefix`
    (a DNA declares e.g. `rsi_7`; the family does not hard-code the period)."""
    for k in sorted(f):
        if k.startswith(prefix) and isinstance(f[k], (int, float)) and not isinstance(f[k], bool):
            return float(f[k])
    return None


def _sign(x: float, eps: float = 1e-12) -> int:
    return 1 if x > eps else (-1 if x < -eps else 0)


def _bias(s: int) -> Bias:
    return Bias.LONG if s > 0 else (Bias.SHORT if s < 0 else Bias.NEUTRAL)


@dataclass(frozen=True)
class FamilyDefinition:
    family: StrategyFamily
    description: str
    direction: Callable[[Features], Bias]
    strength: Callable[[Features, Bias], float]  # 0..1 setup strength


# --------------------------------------------------------------------------- #
# Direction resolvers
# --------------------------------------------------------------------------- #
def _dir_trend(f):
    return _bias(_sign(_g(f, "trend_strength")))


def _dir_momentum(f):
    roc = _find(f, "roc_") if _find(f, "roc_") is not None else _g(f, "roc_10")
    hist = _g(f, "macd_hist")
    votes = _sign(roc) + _sign(hist)
    return _bias(votes)  # both agree -> +-2 ; disagree -> 0 (no trade)


def _dir_breakout(f):
    close = _g(f, "close")
    hi = _find(f, "donchian_high_") or _g(f, "swing_high", default=float("inf"))
    lo = _find(f, "donchian_low_") or _g(f, "swing_low", default=float("-inf"))
    if close > hi:
        return Bias.LONG
    if close < lo:
        return Bias.SHORT
    return _dir_trend(f)


def _dir_mean_reversion(f):
    # Contrarian: fade the stretch relative to the Bollinger mid / z-score.
    z = _find(f, "zscore_")
    if z is not None:
        return _bias(-_sign(z, 0.25))
    upper, lower = _g(f, "bb_upper"), _g(f, "bb_lower")
    close = _g(f, "close")
    if upper > lower:
        pct_b = (close - lower) / (upper - lower)
        return _bias(-_sign(pct_b - 0.5, 0.05))
    return _bias(-_sign(_g(f, "rsi_14", default=50.0) - 50.0, 1.0))


def _dir_volatility(f):
    # Volatility-expansion play: trade in the direction of the expansion bar.
    body = _g(f, "body")
    return _bias(_sign(body)) if body else _dir_trend(f)


def _dir_structure(f):
    if f.get("higher_high") and f.get("higher_low"):
        return Bias.LONG
    if f.get("lower_high") and f.get("lower_low"):
        return Bias.SHORT
    if f.get("break_of_structure"):
        return _bias(_sign(_g(f, "close") - _g(f, "bb_middle", default=_g(f, "close"))))
    return _dir_trend(f)


def _dir_vwap(f):
    vwap = _find(f, "vwap_session") if _find(f, "vwap_session") is not None else _g(f, "vwap")
    close = _g(f, "close")
    if not vwap:
        return _dir_trend(f)
    dev = close / vwap - 1
    if abs(dev) > 0.002:
        return _bias(-_sign(dev))  # far from VWAP -> revert to it
    return _dir_trend(f)  # hugging VWAP -> follow the trend


def _dir_scalping(f):
    roc = _find(f, "roc_")
    if roc is not None and roc != 0:
        return _bias(_sign(roc))
    if f.get("is_momentum_candle"):
        return _bias(_sign(_g(f, "body")))
    return _bias(_sign(_g(f, "ema_slope")))


def _dir_order_flow(f):
    imb = _find(f, "flow_imbalance_")
    if imb is not None and abs(imb) > 0.05:
        return _bias(_sign(imb))
    # Fallback proxy: signed candle body on a volume spike.
    return _bias(_sign(_g(f, "body"))) if f.get("volume_spike") else Bias.NEUTRAL


def _dir_hybrid(f):
    votes = _sign(_g(f, "trend_strength")) + _sign(_g(f, "macd_hist")) + _sign(_g(f, "roc_10"))
    if f.get("higher_high") and f.get("higher_low"):
        votes += 1
    if f.get("lower_high") and f.get("lower_low"):
        votes -= 1
    return _bias(_sign(votes, 0.5)) if abs(votes) >= 2 else Bias.NEUTRAL


# --------------------------------------------------------------------------- #
# Setup strength (0..1)
# --------------------------------------------------------------------------- #
def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _str_trend(f, d):
    return _clip(abs(_g(f, "trend_strength")) * 100)


def _str_momentum(f, d):
    roc = _find(f, "roc_") if _find(f, "roc_") is not None else _g(f, "roc_10")
    return _clip(abs(roc) / 3)


def _str_breakout(f, d):
    return _clip((_g(f, "volume_ratio", default=1.0) - 1.0) / 2)


def _str_mean_reversion(f, d):
    z = _find(f, "zscore_")
    return _clip(abs(z) / 3) if z is not None else _clip(abs(_g(f, "rsi_14", default=50.0) - 50.0) / 30)


def _str_volatility(f, d):
    return _clip(_g(f, "volatility_percentile", default=0.5))


def _str_structure(f, d):
    return 0.8 if (f.get("break_of_structure") or (f.get("higher_high") and f.get("higher_low"))) else 0.4


def _str_vwap(f, d):
    vwap = _g(f, "vwap")
    return _clip(abs(_g(f, "close") / vwap - 1) * 100) if vwap else 0.3


def _str_scalping(f, d):
    return 0.7 if f.get("is_momentum_candle") else 0.4


def _str_order_flow(f, d):
    imb = _find(f, "flow_imbalance_")
    return _clip(abs(imb)) if imb is not None else _clip((_g(f, "volume_ratio", default=1.0) - 1.0) / 2)


def _str_hybrid(f, d):
    votes = abs(_sign(_g(f, "trend_strength")) + _sign(_g(f, "macd_hist")) + _sign(_g(f, "roc_10")))
    return _clip(votes / 3)


FAMILIES: dict[StrategyFamily, FamilyDefinition] = {
    StrategyFamily.MOMENTUM: FamilyDefinition(StrategyFamily.MOMENTUM, "trade in the direction of confirmed rate-of-change + MACD", _dir_momentum, _str_momentum),
    StrategyFamily.TREND_FOLLOWING: FamilyDefinition(StrategyFamily.TREND_FOLLOWING, "follow the fast/slow EMA trend", _dir_trend, _str_trend),
    StrategyFamily.BREAKOUT: FamilyDefinition(StrategyFamily.BREAKOUT, "trade range/channel breaks, weighted by volume", _dir_breakout, _str_breakout),
    StrategyFamily.MEAN_REVERSION: FamilyDefinition(StrategyFamily.MEAN_REVERSION, "fade stretches away from the mean", _dir_mean_reversion, _str_mean_reversion),
    StrategyFamily.VOLATILITY: FamilyDefinition(StrategyFamily.VOLATILITY, "trade volatility expansion in the expansion bar's direction", _dir_volatility, _str_volatility),
    StrategyFamily.MARKET_STRUCTURE: FamilyDefinition(StrategyFamily.MARKET_STRUCTURE, "trade swing structure (HH/HL vs LH/LL, breaks)", _dir_structure, _str_structure),
    StrategyFamily.VWAP: FamilyDefinition(StrategyFamily.VWAP, "revert to VWAP when stretched, else follow trend", _dir_vwap, _str_vwap),
    StrategyFamily.SCALPING: FamilyDefinition(StrategyFamily.SCALPING, "very short-horizon momentum scalps", _dir_scalping, _str_scalping),
    StrategyFamily.ORDER_FLOW: FamilyDefinition(StrategyFamily.ORDER_FLOW, "volume-weighted candle-flow imbalance (bar-based proxy)", _dir_order_flow, _str_order_flow),
    StrategyFamily.HYBRID: FamilyDefinition(StrategyFamily.HYBRID, "multi-signal vote (trend + momentum + structure)", _dir_hybrid, _str_hybrid),
}


def get_family(family: StrategyFamily) -> FamilyDefinition:
    return FAMILIES[family]
