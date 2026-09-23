"""DB growth control: only actionable agent-candles leave a Decision row, no per-row
market snapshot copy, and the prune script never touches order/trade-linked rows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.models.enums import Bias, RiskDecision
from app.models.trading import Order, Trade
from scripts.prune_decisions import count_noop, prune_noop_decisions, strip_context
from tests.helpers_agents import cycle, make_agents, make_context, make_dna


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)


async def _count(db):
    return (await db.execute(select(func.count()).select_from(Decision))).scalar_one()


async def test_agents_with_no_signal_write_no_rows(db_session):
    await make_agents(db_session, [make_dna() for _ in range(20)])
    eng = PaperExecutionAdapter()
    prev = None
    for i in range(1, 6):                                   # 5 candles, rsi 50: no entry signal anywhere
        ctx = make_context(i, 100.0, rsi=50.0)
        assert await cycle(db_session, eng, ctx, prev) == 20
        prev = ctx
    assert await _count(db_session) == 0                    # 100 agent-candles -> 0 rows


async def test_holding_a_position_writes_no_row_but_entry_and_exit_do(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    c1 = make_context(1, 100.0, rsi=65.0)                   # entry
    await cycle(db_session, eng, c1)
    c2 = make_context(2, 100.5, rsi=55.0)                   # holding: neither exit (<40) nor entry
    await cycle(db_session, eng, c2, c1)
    c3 = make_context(3, 101.0, rsi=30.0)                   # exit signal
    await cycle(db_session, eng, c3, c2)
    rows = (await db_session.execute(select(Decision).order_by(Decision.market_candle_open_time))).scalars().all()
    assert [bool(r.order_id) for r in rows] == [True, True]  # exactly the entry and the exit
    assert rows[0].trade_id is None and rows[1].trade_id is not None
    assert all(r.market_context is None for r in rows)


async def test_risk_rejections_and_vetoes_are_still_audited(db_session):
    from app.core.system_flags import KILL_SWITCH, set_flag
    await make_agents(db_session, [make_dna()])
    await set_flag(db_session, KILL_SWITCH, True, reason="t")
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))   # signal, but halted
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.risk_decision == RiskDecision.REJECTED and "trading_halted:kill_switch" in d.risk_reasoning["reasons"]
    assert d.agent_signal == Bias.LONG


async def test_council_veto_and_cooldown_are_still_audited(db_session):
    from app.council.context import COMPLETE
    await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0),
                council_bias=Bias.SHORT, council_confidence=0.95, council_trade_allowed=True, council_status=COMPLETE)
    d = (await db_session.execute(select(Decision))).scalar_one()
    assert d.risk_reasoning["skipped"] == "council_directional_conflict"


async def _legacy_rows(db, agent, n, *, old, linked=False):
    """n legacy no-op rows (with the heavy context) - like the ones in the production backup."""
    for i in range(n):
        db.add(Decision(
            agent_id=agent.id, strategy_version_id=agent.strategy_version_id, market_candle_open_time=10_000 + i,
            market_timestamp=datetime.now(timezone.utc), market_context={"x": "y" * 1200}, agent_signal=Bias.NEUTRAL,
            agent_signal_confidence=0.0, risk_decision=RiskDecision.REJECTED,
            risk_reasoning={"skipped": "no_entry_signal_or_position_open"},
        ))
    await db.flush()
    if old:
        await db.execute(update(Decision).values(created_at=datetime.now(timezone.utc) - timedelta(days=30)))
    await db.commit()


async def test_prune_deletes_old_noop_rows_but_never_order_or_trade_linked_ones(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await _legacy_rows(db_session, agent, 25, old=True)
    # a real entry+exit that is ALSO old
    eng = PaperExecutionAdapter()
    c1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, c1)
    await cycle(db_session, eng, make_context(2, 101.0, rsi=30.0), c1)
    await db_session.execute(update(Decision).values(created_at=datetime.now(timezone.utc) - timedelta(days=30)))
    await db_session.commit()
    orders_before = (await db_session.execute(select(func.count()).select_from(Order))).scalar_one()
    trades_before = (await db_session.execute(select(func.count()).select_from(Trade))).scalar_one()

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    total, noop = await count_noop(db_session, cutoff)
    assert (total, noop) == (27, 25)
    deleted = await prune_noop_decisions(db_session, cutoff, batch_size=10)        # batched
    assert deleted == 25
    remaining = (await db_session.execute(select(Decision))).scalars().all()
    assert len(remaining) == 2 and all(r.order_id for r in remaining)
    assert (await db_session.execute(select(func.count()).select_from(Order))).scalar_one() == orders_before
    assert (await db_session.execute(select(func.count()).select_from(Trade))).scalar_one() == trades_before


async def test_prune_respects_retention_window(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await _legacy_rows(db_session, agent, 10, old=False)                              # fresh rows
    assert await prune_noop_decisions(db_session, datetime.now(timezone.utc) - timedelta(days=7)) == 0
    assert await _count(db_session) == 10


async def test_strip_context_nulls_the_duplicated_snapshot_on_kept_rows(db_session):
    (agent,) = await make_agents(db_session, [make_dna()])
    await _legacy_rows(db_session, agent, 12, old=False)
    assert await strip_context(db_session, batch_size=5) == 12
    rows = (await db_session.execute(select(Decision))).scalars().all()
    assert all(r.market_context is None for r in rows) and len(rows) == 12
    assert await strip_context(db_session) == 0                                       # idempotent


def test_row_size_regression_guard_the_snapshot_is_not_copied_per_decision():
    import inspect
    from app.agents import decision_loop
    src = inspect.getsource(decision_loop._process_agent)
    assert "market_context=None" in src and "model_dump(mode=\"json\")" not in src.split("Decision(")[1].split(")")[0]
