"""Council as shared context (spec phases 12-13, 16): deterministic, auditable,
never bypasses the Risk Engine, never applied to a different candle."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.council.context import COMPLETE, INCOMPLETE, NOT_RUN, CouncilContext, combine
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import Bias, RiskDecision
from app.models.trading import Order, Position
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


def ctx(bias, conf, status=COMPLETE, allowed=True, candle=1):
    return CouncilContext(status=status, bias=bias, confidence=conf, trade_allowed=allowed, candle_open_time=candle)


def test_combine_matrix():
    s = get_settings()
    aligned = combine(Bias.LONG, ctx(Bias.LONG, 0.8))
    assert aligned.final_signal == Bias.LONG and aligned.size_modifier == pytest.approx(1 + s.council_aligned_size_bonus * 0.8)
    veto = combine(Bias.LONG, ctx(Bias.SHORT, 0.9))
    assert veto.final_signal == Bias.NEUTRAL and veto.reason == "council_directional_conflict_veto"
    weak_opposed = combine(Bias.LONG, ctx(Bias.SHORT, 0.4))
    assert weak_opposed.final_signal == Bias.LONG and weak_opposed.size_modifier == pytest.approx(1 - s.council_opposed_size_penalty * 0.4)
    neutral = combine(Bias.SHORT, ctx(Bias.NEUTRAL, 0.7))
    assert neutral.final_signal == Bias.SHORT and neutral.size_modifier == s.council_neutral_size_modifier
    assert combine(Bias.LONG, ctx(Bias.NEUTRAL, 0.5, INCOMPLETE, False)).final_signal == Bias.NEUTRAL
    not_run = combine(Bias.LONG, CouncilContext())
    assert not_run.final_signal == Bias.LONG and not_run.size_modifier == 1.0 and not_run.council_status == NOT_RUN
    assert combine(Bias.NEUTRAL, ctx(Bias.LONG, 0.9)).final_signal == Bias.NEUTRAL


def test_council_never_creates_a_trade_by_itself():
    assert combine(Bias.NEUTRAL, ctx(Bias.LONG, 1.0)).final_signal == Bias.NEUTRAL


def test_council_result_is_bound_to_its_candle_and_never_reused():
    c = ctx(Bias.LONG, 0.9, candle=100)
    assert c.for_candle(100) is c
    stale = c.for_candle(101)
    assert stale.status == NOT_RUN and stale.bias is None and stale.trade_allowed


def test_audit_payload_has_the_four_required_fields():
    a = combine(Bias.LONG, ctx(Bias.LONG, 0.8)).audit()
    assert {"council_bias", "council_confidence", "agent_signal", "final_signal", "council_status"} <= set(a)


async def test_aligned_council_scales_size_up_and_records_audit_fields(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0),
                council_bias=Bias.LONG, council_confidence=0.8, council_trade_allowed=True, council_status=COMPLETE)
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.council_bias == Bias.LONG and d.council_confidence == 0.8
    assert d.agent_signal == Bias.LONG and d.final_signal == Bias.LONG
    assert d.risk_reasoning["council"]["reason"] == "council_aligned"


async def test_high_confidence_opposed_council_vetoes_but_agent_signal_is_still_recorded(db_session):
    await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0),
                council_bias=Bias.SHORT, council_confidence=0.9, council_trade_allowed=True, council_status=COMPLETE)
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.agent_signal == Bias.LONG and d.final_signal == Bias.NEUTRAL and d.council_bias == Bias.SHORT
    assert d.risk_reasoning["skipped"] == "council_directional_conflict"
    assert (await db_session.execute(select(Position))).first() is None


async def test_healthy_council_influences_size_but_agents_stay_independent(db_session):
    a1, a2 = await make_agents(db_session, [make_dna(), make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0),
                council_bias=Bias.NEUTRAL, council_confidence=0.6, council_trade_allowed=True, council_status=COMPLETE)
    orders = (await db_session.execute(select(Order))).scalars().all()
    assert len(orders) == 2 and all(o.requested_notional == pytest.approx(10.0 * get_settings().council_neutral_size_modifier) for o in orders)


async def test_incomplete_council_still_reaches_the_risk_engine_and_blocks_entry(db_session):
    await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0),
                council_trade_allowed=False, council_status=INCOMPLETE)
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.risk_decision == RiskDecision.REJECTED and "council_incomplete_no_new_trades" in d.risk_reasoning["reasons"]
    assert (await db_session.execute(select(Position))).first() is None


async def test_council_context_for_another_candle_is_not_applied(db_session):
    """A council decision id/bias handed in for candle N cannot influence candle N+1."""
    from app.agents.decision_loop import _council_context
    c1 = make_context(1, 100.0)
    c2 = make_context(2, 100.0)
    built = _council_context(c1, None, True, Bias.SHORT, 0.95, COMPLETE)
    assert built.for_candle(c2.candle_open_time).status == NOT_RUN
