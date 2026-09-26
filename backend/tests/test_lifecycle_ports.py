"""Phase 2 dependency-boundary regression: app/agents/lifecycle.py must not
import app.execution (directly or deferred) - retire_generation() depends on
a PositionCloseSettler Protocol, supplied by the caller, not on
app.execution.accounting.settle_close reached into internally. See
REFACTOR_PLAN.md item 2 / REFACTOR_PROGRESS.md.
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agents.lifecycle import retire_generation
from app.agents.ports import PositionCloseSettler, SettlementResult
from app.execution import accounting
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import AgentStatus
from app.models.trading import Position, Trade
from tests.helpers_agents import cycle, make_agents, make_context, make_dna

# Position-mechanics tests need a fill within a single cycle() call; see
# conftest.immediate_fills (the production default, next_open, fills on the
# FOLLOWING bar - not what these tests are exercising).
pytestmark = pytest.mark.usefixtures("immediate_fills")


def test_lifecycle_module_does_not_import_execution_at_all():
    """The boundary is real: lifecycle.py contains no import of app.execution -
    module-level or deferred/function-local (a docstring may still reference
    the package name by way of explanation - only an actual import is
    disallowed)."""
    src = inspect.getsource(importlib.import_module("app.agents.lifecycle"))
    assert "from app.execution" not in src
    assert "import app.execution" not in src


def test_accounting_settle_close_satisfies_the_protocol_structurally():
    """app.execution.accounting.settle_close (the one production implementation)
    is UNCHANGED and still works as the real settler - it satisfies
    PositionCloseSettler by shape, with no inheritance/registration needed."""
    assert isinstance(accounting.settle_close, PositionCloseSettler)
    result = accounting.settle_close(100.0, -50.0, 1.0)
    assert isinstance(result, SettlementResult)


@dataclass(frozen=True)
class _FakeSettlement:
    new_balance: float
    bad_debt: float


class _AlwaysZeroBadDebtSettler:
    """Deliberately NOT app.execution.accounting - a substitute settler proving
    retire_generation truly depends on the injected callable, not on the
    concrete execution module. Ignores the loss entirely (returns the balance
    unchanged, zero bad debt) so its effect is observably different from the
    real settler when a close would go negative."""

    def __call__(self, balance: float, gross_pnl: float, exit_fee: float) -> _FakeSettlement:
        return _FakeSettlement(new_balance=balance, bad_debt=0.0)


async def test_retire_generation_uses_the_injected_settler_not_a_hardcoded_one(db_session, monkeypatch):
    """End-to-end proof: swapping the settler changes the settlement outcome,
    so retire_generation is really calling the injected callable, not
    silently still importing app.execution.accounting itself."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "paper_latency_ms", 0)
    monkeypatch.setattr(get_settings(), "paper_latency_jitter_ms", 0)
    (agent,) = await make_agents(db_session, [make_dna()])
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    agent.balance = 0.01   # force a close that would go negative -> would normally record bad debt

    res = await retire_generation(
        db_session, 100, mark_price=0.01, at=datetime.now(timezone.utc), fee_rate=0.00045,
        settle_close=_AlwaysZeroBadDebtSettler(),
    )
    await db_session.commit()
    assert res["retired"] == 1
    await db_session.refresh(agent)
    assert agent.bad_debt == 0.0   # the fake settler never records bad debt, proving it (not accounting) ran


async def test_retire_generation_behavior_is_unchanged_with_the_real_settler(db_session, monkeypatch):
    """Same scenario as test_snapshots_and_lifecycle.py's existing coverage,
    run through the explicit settle_close=accounting.settle_close call site -
    retirement/accounting behavior is exactly preserved through the new
    dependency boundary."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "paper_latency_ms", 0)
    monkeypatch.setattr(get_settings(), "paper_latency_jitter_ms", 0)
    a1, a2 = await make_agents(db_session, [make_dna(), make_dna()])
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    open_before = (await db_session.execute(select(Position).where(Position.is_open.is_(True)))).scalars().all()
    assert len(open_before) == 2

    res = await retire_generation(db_session, 100, mark_price=103.0, at=datetime.now(timezone.utc), fee_rate=0.00045,
                                   settle_close=accounting.settle_close)
    await db_session.commit()

    assert res == {"retired": 2, "positions_closed": 2}
    for a in (a1, a2):
        await db_session.refresh(a)
        assert a.status == AgentStatus.RETIRED
        assert a.final_equity == pytest.approx(a.equity)
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert {t.exit_reason for t in trades} == {"generation_rollover"} and all(t.net_pnl > 0 for t in trades)
