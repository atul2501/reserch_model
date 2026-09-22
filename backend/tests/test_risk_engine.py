"""Deterministic risk engine checks (spec section 18/45)."""
from __future__ import annotations

import uuid
from datetime import date

from app.models.agent import Agent
from app.models.enums import RiskDecision, Side
from app.risk.risk_engine import RiskCheckInput, check_trade
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA


def _dna(**overrides) -> StrategyDNA:
    base = dict(
        strategy_family="momentum",
        indicators=[{"name": "rsi", "params": {"period": 14}}],
        entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=60)]),
        exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=50)]),
        risk_profile=RiskProfile(max_leverage=3.0, max_position_fraction=0.2, max_daily_loss_fraction=0.1, max_drawdown_fraction=0.3),
    )
    base.update(overrides)
    return StrategyDNA.model_validate(base)


def _agent(equity=100.0, peak_equity=100.0, starting_balance=100.0) -> Agent:
    return Agent(
        identifier="GEN01-AG0001",
        generation=1,
        strategy_version_id=uuid.uuid4(),
        starting_balance=starting_balance,
        balance=equity,
        equity=equity,
        peak_equity=peak_equity,
        day_start_equity=equity,
        day_start_date=date.today(),
    )


def _base_input(**overrides) -> RiskCheckInput:
    base = dict(
        agent=_agent(),
        dna=_dna(),
        side=Side.LONG,
        proposed_notional=10.0,
        proposed_leverage=1.0,
        current_price=100.0,
        atr=1.0,
        equity=100.0,
        daily_pnl=0.0,
        has_open_position=False,
        market_data_age_seconds=5.0,
    )
    base.update(overrides)
    return RiskCheckInput(**base)


def _check(inp: RiskCheckInput) -> RiskDecision:
    return check_trade(
        inp,
        global_max_leverage=5.0,
        global_max_position_size=0.5,
        global_max_drawdown=0.3,
        global_max_daily_loss=0.1,
    ).decision


def test_approves_a_reasonable_trade():
    result = check_trade(
        _base_input(), global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1
    )
    assert result.decision == RiskDecision.APPROVED


def test_rejects_stale_market_data():
    assert _check(_base_input(market_data_age_seconds=999.0)) == RiskDecision.REJECTED


def test_rejects_non_positive_equity():
    assert _check(_base_input(equity=0.0)) == RiskDecision.REJECTED


def test_rejects_when_drawdown_exceeds_limit():
    agent = _agent(equity=60.0, peak_equity=100.0)  # 40% drawdown
    assert _check(_base_input(agent=agent, equity=60.0)) == RiskDecision.REJECTED


def test_rejects_when_daily_loss_limit_exceeded():
    assert _check(_base_input(daily_pnl=-20.0)) == RiskDecision.REJECTED  # 20% > 10% dna limit


def test_rejects_duplicate_position():
    assert _check(_base_input(has_open_position=True)) == RiskDecision.REJECTED


def test_rejects_abnormal_volatility():
    assert _check(_base_input(atr=10.0, current_price=100.0)) == RiskDecision.REJECTED  # 10% ATR


def test_reduces_oversized_position():
    result = check_trade(
        _base_input(proposed_notional=1000.0),
        global_max_leverage=5.0,
        global_max_position_size=0.5,
        global_max_drawdown=0.3,
        global_max_daily_loss=0.1,
    )
    assert result.decision == RiskDecision.REDUCED
    assert result.approved_notional < 1000.0
    assert "position_size_reduced_to_limit" in result.reasons


def test_rejects_new_trade_when_council_incomplete():
    """Fail-closed contract: an INCOMPLETE council cycle (quorum not met)
    must block every NEW trade at the Risk Engine — the single actual
    enforcement point, never bypassed by an upstream caller that already
    "knows" the council failed."""
    result = check_trade(
        _base_input(council_trade_allowed=False),
        global_max_leverage=5.0, global_max_position_size=0.5, global_max_drawdown=0.3, global_max_daily_loss=0.1,
    )
    assert result.decision == RiskDecision.REJECTED
    assert result.reasons == ["council_incomplete_no_new_trades"]
    assert result.approved_notional == 0.0


def test_council_trade_allowed_true_is_unaffected():
    """Default (council healthy or not applicable) behaves exactly as
    before this fix — this flag must never introduce a false rejection."""
    assert _check(_base_input(council_trade_allowed=True)) == RiskDecision.APPROVED


def test_reduces_excessive_leverage():
    result = check_trade(
        _base_input(proposed_leverage=100.0),
        global_max_leverage=5.0,
        global_max_position_size=0.5,
        global_max_drawdown=0.3,
        global_max_daily_loss=0.1,
    )
    assert result.approved_leverage <= 5.0
    assert "leverage_reduced_to_limit" in result.reasons
