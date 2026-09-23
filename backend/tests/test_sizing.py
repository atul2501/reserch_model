"""Position sizing (spec phase 6): mathematically explicit, all methods work,
margin/notional never silently exceed limits."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.execution.sizing import (
    approve_against_margin, build_sizing_result, normalize_method, requested_notional, stop_distance_pct,
)
from tests.helpers_agents import make_dna
from app.schemas.strategy_dna import PositionSizing, StopLossConfig


def _dna(method, frac=0.1, lev=2.0, max_notional=None, **kw):
    from app.schemas.strategy_dna import RiskProfile
    return make_dna(position_sizing=PositionSizing(method=method, fraction_of_equity=frac, max_notional=max_notional),
                    leverage_limit=lev, risk_profile=RiskProfile(max_leverage=max(lev, 1.0), max_position_fraction=0.5), **kw)


def test_aliases_normalise():
    assert normalize_method("fixed_fraction") == normalize_method("fraction_of_equity") == "fraction_of_equity"
    assert normalize_method("kelly_fraction") == normalize_method("risk_based") == "risk_based"
    assert normalize_method("volatility_scaled") == normalize_method("volatility_based") == "volatility_based"


def test_fraction_of_equity_is_margin_times_leverage():
    assert requested_notional(_dna("fraction_of_equity", 0.1, 3.0), equity=100, price=100, atr=0.1, stop_dist_pct=0.01) == pytest.approx(30.0)


def test_fixed_notional_uses_max_notional_else_falls_back():
    assert requested_notional(_dna("fixed_notional", max_notional=25.0), equity=100, price=100, atr=0.1, stop_dist_pct=0.01) == 25.0
    assert requested_notional(_dna("fixed_notional", 0.2, 2.0), equity=100, price=100, atr=0.1, stop_dist_pct=0.01) == pytest.approx(40.0)


def test_risk_based_notional_is_risk_over_stop_distance_capped_by_leverage():
    dna = _dna("risk_based", frac=0.01, lev=5.0)          # risk 1% of $100 = $1
    assert requested_notional(dna, equity=100, price=100, atr=0.1, stop_dist_pct=0.02) == pytest.approx(50.0)   # $1 / 2%
    assert requested_notional(dna, equity=100, price=100, atr=0.1, stop_dist_pct=0.0005) == pytest.approx(500.0)  # capped: equity*lev
    res = build_sizing_result(method="risk_based", requested=50.0, approved=50.0, leverage=5.0, price=100.0, stop_dist_pct=0.02)
    assert res.risk_amount == pytest.approx(1.0) and res.margin == pytest.approx(10.0) and res.quantity == pytest.approx(0.5)


def test_volatility_based_scales_inversely_with_atr_and_is_clamped():
    s = get_settings()
    dna = _dna("volatility_based", 0.1, 2.0)
    calm = requested_notional(dna, equity=100, price=100, atr=100 * s.sizing_vol_target_atr_pct / 2, stop_dist_pct=0.01)
    target = requested_notional(dna, equity=100, price=100, atr=100 * s.sizing_vol_target_atr_pct, stop_dist_pct=0.01)
    wild = requested_notional(dna, equity=100, price=100, atr=100 * s.sizing_vol_target_atr_pct * 10, stop_dist_pct=0.01)
    assert calm > target > wild
    assert target == pytest.approx(20.0)                       # 100 * 0.1 * 2 * scale(1)
    assert wild == pytest.approx(20.0 * s.sizing_vol_scale_min)
    assert calm == pytest.approx(20.0 * min(2.0, s.sizing_vol_scale_max))


def test_zero_or_negative_equity_sizes_to_zero():
    assert requested_notional(_dna("fraction_of_equity"), equity=0, price=100, atr=1, stop_dist_pct=0.01) == 0.0


def test_approval_is_capped_by_available_margin():
    assert approve_against_margin(500.0, leverage=5.0, available_margin=20.0) == pytest.approx(100.0)   # 20 margin * 5x
    assert approve_against_margin(50.0, leverage=5.0, available_margin=20.0) == 50.0
    assert approve_against_margin(50.0, leverage=0.0, available_margin=20.0) == 0.0


def test_stop_distance_variants():
    atr_dna = make_dna(stop_loss=StopLossConfig(method="atr_multiple", value=2.0))
    pct_dna = make_dna(stop_loss=StopLossConfig(method="fixed_pct", value=1.5))
    struct = make_dna(stop_loss=StopLossConfig(method="structure_based", value=2.0))
    off = make_dna(stop_loss=StopLossConfig(enabled=False))
    assert stop_distance_pct(atr_dna, 100, 0.5) == pytest.approx(0.01)
    assert stop_distance_pct(pct_dna, 100, 0.5) == pytest.approx(0.015)
    assert stop_distance_pct(struct, 100, 0.5, swing_low=98.0, side_is_long=True) == pytest.approx(0.02)
    assert stop_distance_pct(struct, 100, 0.5, swing_low=None) == pytest.approx(0.01)   # ATR fallback
    assert stop_distance_pct(off, 100, 0.5) == 1.0
