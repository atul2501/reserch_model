"""Nested DNA fields that define behaviour, each proven by changing ONLY that value and observing the runtime change
(spec phase 4). The mapping lives in tests/test_dna_runtime_coverage.py."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.position_manager import stop_price, take_profit_price
from app.execution import accounting
from app.execution.paper_adapter import PaperExecutionAdapter
from app.execution.sizing import requested_notional
from app.models.decision import Decision
from app.models.enums import RiskDecision, Side
from app.models.trading import Order, Position, Trade
from app.schemas.strategy_dna import (
    CooldownConfig, PositionSizing, RiskProfile, StopLossConfig, TakeProfitConfig, TrailingStopConfig,
)
from tests.helpers_agents import MINUTE, T0, cycle, make_agents, make_context, make_dna
from tests.test_risk_engine import _agent, _base_input, _check, _dna as risk_dna

pytestmark = pytest.mark.usefixtures("immediate_fills")


def test_dna_daily_loss_and_drawdown_limits_are_enforced():
    tight_loss = risk_dna(risk_profile=RiskProfile(max_leverage=3.0, max_position_fraction=0.2, max_daily_loss_fraction=0.02,
                                                   max_drawdown_fraction=0.3))
    loose_loss = risk_dna(risk_profile=RiskProfile(max_leverage=3.0, max_position_fraction=0.2, max_daily_loss_fraction=0.09,
                                                   max_drawdown_fraction=0.3))
    # a 5% intraday loss: over the tight DNA limit (2%), under the loose one (9%) - and under the global 10%
    assert _check(_base_input(dna=tight_loss, daily_pnl=-5.0)) == RiskDecision.REJECTED
    assert _check(_base_input(dna=loose_loss, daily_pnl=-5.0)) != RiskDecision.REJECTED
    # a 12% drawdown: over the tight DNA drawdown limit (10%), under the loose one (25%)
    tight_dd = risk_dna(risk_profile=RiskProfile(max_leverage=3.0, max_position_fraction=0.2, max_daily_loss_fraction=0.1,
                                                 max_drawdown_fraction=0.10))
    loose_dd = risk_dna(risk_profile=RiskProfile(max_leverage=3.0, max_position_fraction=0.2, max_daily_loss_fraction=0.1,
                                                 max_drawdown_fraction=0.25))
    drawn = _agent(equity=88.0, peak_equity=100.0)
    assert _check(_base_input(dna=tight_dd, agent=drawn, equity=88.0)) == RiskDecision.REJECTED
    assert _check(_base_input(dna=loose_dd, agent=drawn, equity=88.0)) != RiskDecision.REJECTED


def test_position_sizing_max_notional_caps_the_order():
    uncapped = make_dna(position_sizing=PositionSizing(method="fixed_notional", fraction_of_equity=0.5, max_notional=40.0))
    other = make_dna(position_sizing=PositionSizing(method="fixed_notional", fraction_of_equity=0.5, max_notional=15.0))
    a = requested_notional(uncapped, equity=100, price=100, atr=1, stop_dist_pct=0.02)
    b = requested_notional(other, equity=100, price=100, atr=1, stop_dist_pct=0.02)
    assert a == pytest.approx(40.0) and b == pytest.approx(15.0)
    # ... and as a hard risk cap on top of any sizing method
    capped = make_dna(position_sizing=PositionSizing(method="fraction_of_equity", fraction_of_equity=0.5, max_notional=12.0))
    from app.risk.risk_engine import RiskCheckInput, check_trade
    res = check_trade(_base_input(dna=capped, proposed_notional=50.0), global_max_leverage=5.0, global_max_position_size=0.5,
                      global_max_drawdown=0.3, global_max_daily_loss=0.1)
    assert res.approved_notional <= 12.0 + 1e-9


def test_stop_and_take_profit_can_be_disabled():
    on = accounting.entry_levels(make_dna(), Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    off = accounting.entry_levels(make_dna(stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(enabled=False)),
                                  Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    assert on.stop_loss is not None and on.take_profit is not None
    assert off.stop_loss is None and off.take_profit is None


def test_every_stop_loss_method_places_a_different_stop():
    kw = dict(atr=0.5, swing_low=97.0, swing_high=103.0)
    atr = stop_price(100.0, Side.LONG, method="atr_multiple", value=2.0, **kw)
    pct = stop_price(100.0, Side.LONG, method="fixed_pct", value=2.0, **kw)
    struct = stop_price(100.0, Side.LONG, method="structure_based", value=2.0, **kw)
    assert atr == pytest.approx(99.0) and pct == pytest.approx(98.0) and struct == pytest.approx(97.0)
    assert len({atr, pct, struct}) == 3
    assert stop_price(100.0, Side.SHORT, method="structure_based", value=2.0, **kw) == pytest.approx(103.0)


def test_every_take_profit_method_places_a_different_target():
    rr = take_profit_price(100.0, Side.LONG, method="risk_reward_multiple", value=2.0, atr=0.5, stop=99.0)
    pct = take_profit_price(100.0, Side.LONG, method="fixed_pct", value=3.0, atr=0.5, stop=99.0)
    atr = take_profit_price(100.0, Side.LONG, method="atr_multiple", value=4.0, atr=0.5, stop=99.0)
    assert rr == pytest.approx(102.0) and pct == pytest.approx(103.0) and atr == pytest.approx(102.0)
    assert take_profit_price(100.0, Side.SHORT, method="fixed_pct", value=3.0, atr=0.5, stop=101.0) == pytest.approx(97.0)


def test_trailing_distance_comes_from_trail_pct():
    wide = accounting.entry_levels(make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.0, trail_pct=2.0)),
                                   Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    narrow = accounting.entry_levels(make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.0, trail_pct=0.5)),
                                     Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    assert wide.trailing_distance == pytest.approx(2.0) and narrow.trailing_distance == pytest.approx(0.5)
    assert wide.trailing_active and narrow.trailing_active
    delayed = accounting.entry_levels(make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=1.0, trail_pct=1.0)),
                                      Side.LONG, 100.0, atr=0.5, swing_low=None, swing_high=None)
    assert delayed.trailing_active is False                                   # armed only after activation_pct in favour


async def _round_trip(db, dna, exit_close):
    (agent,) = await make_agents(db, [dna])
    eng = PaperExecutionAdapter()
    await cycle(db, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db, eng, make_context(2, exit_close, rsi=30.0))
    await db.refresh(agent)
    return agent


async def test_cooldown_after_a_win_uses_bars_after_win(db_session):
    win = await _round_trip(db_session, make_dna(cooldown=CooldownConfig(bars_after_win=4, bars_after_loss=0)), exit_close=101.0)
    assert win.cooldown_until is not None
    assert win.cooldown_until.timestamp() * 1000 == pytest.approx(T0 + 2 * MINUTE + 4 * MINUTE)      # exit bar + 4 bars


async def test_a_zero_cooldown_for_wins_sets_none(db_session):
    win = await _round_trip(db_session, make_dna(cooldown=CooldownConfig(bars_after_win=0, bars_after_loss=9)), exit_close=101.0)
    assert win.cooldown_until is None


def test_behavioural_problems_flag_silent_do_nothing_combinations():
    ok = make_dna()
    assert ok.behavioural_problems() == []
    dead_trail = make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.5, trail_pct=0.0))
    assert any("trail_pct=0" in p for p in dead_trail.behavioural_problems())
    orphan_short_exit = make_dna(short_exit_rules=ok.exit_rules, direction_mode="long_only")
    assert any("short_exit_rules" in p for p in orphan_short_exit.behavioural_problems())
    no_stop_rr = make_dna(stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(method="risk_reward_multiple", value=2.0))
    assert any("risk_reward_multiple" in p for p in no_stop_rr.behavioural_problems())
    fixed_tp_no_stop = make_dna(stop_loss=StopLossConfig(enabled=False), take_profit=TakeProfitConfig(method="fixed_pct", value=2.0))
    assert fixed_tp_no_stop.behavioural_problems() == []


def test_the_creation_gate_rejects_them_but_persisted_dna_still_loads():
    from app.evolution.breeding import check_candidate_schema
    from app.schemas.strategy_dna import StrategyDNA

    bad = make_dna(trailing_stop=TrailingStopConfig(enabled=True, activation_pct=0.5, trail_pct=0.0))
    assert any(p.startswith("behaviour:") for p in check_candidate_schema(bad))
    StrategyDNA.model_validate(bad.model_dump(mode="json"))          # legacy rows keep validating (protected, not orphaned)
