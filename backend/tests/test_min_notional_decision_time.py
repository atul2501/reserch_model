"""Minimum order notional is enforced at DECISION time, not discovered a bar later at the fill.

Observed in production paper mode: 3,469 of ~4,900 entry orders (~70%) were approved by the Risk Engine, persisted as
PENDING, then FAILED at the next bar's open with `below_min_order_notional` (approved notional avg $6.35 vs the $10
exchange minimum on $100 agents). Each left a FAILED order row plus a Decision row mislabelled REJECTED with no reason.

The doomed order must never be created; the Decision must say why. P&L is unchanged (those orders never filled).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import OrderStatus, RiskDecision
from app.models.trading import Order
from app.schemas.strategy_dna import PositionSizing
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


async def _orders(db):
    return (await db.execute(select(Order))).scalars().all()


async def _decisions(db):
    return (await db.execute(select(Decision))).scalars().all()


async def test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 10.0)
    (agent,) = await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))   # 5% x $100 = a $5 order

    assert await _orders(db_session) == []                      # no PENDING (and later FAILED) order is ever created
    (decision,) = await _decisions(db_session)
    assert decision.risk_decision == RiskDecision.REJECTED
    assert decision.order_id is None
    assert "below_min_order_notional" in decision.risk_reasoning["reasons"]
    await db_session.refresh(agent)
    assert agent.balance == 100.0 and agent.trade_count == 0 and agent.daily_trade_count == 0


async def test_entry_at_the_minimum_still_creates_a_pending_order(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 10.0)
    await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.1))])   # exactly $10
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.PENDING


async def test_the_minimum_can_be_disabled_like_at_the_adapter(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_min_order_notional", 0.0)
    await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    (order,) = await _orders(db_session)
    assert order.status == OrderStatus.PENDING


def test_check_mirrors_the_adapter_lot_rounding(monkeypatch):
    from app.execution.sizing import below_min_order_notional

    s = get_settings()
    monkeypatch.setattr(s, "paper_min_order_notional", 10.0)
    monkeypatch.setattr(s, "paper_quantity_step", 0.01)
    assert below_min_order_notional(9.99, 100.0) is True
    assert below_min_order_notional(10.0, 100.0) is False
    assert below_min_order_notional(10.009, 100.0) is False      # floors to 0.10 lots -> $10.00
    assert below_min_order_notional(10.5, 107.0) is True         # 0.098 -> floors to 0.09 lots -> $9.63
    assert below_min_order_notional(0.0, 100.0) is True
    monkeypatch.setattr(s, "paper_min_order_notional", 0.0)
    assert below_min_order_notional(0.01, 100.0) is False
