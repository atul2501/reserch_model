"""Agents that cannot reach the exchange minimum order at their capital are UNTESTABLE, not failed strategies.

Replay of the 500 real DNAs at $100 / $10 minimum: 195 agents sit below the minimum on >95% of bars and 87% of all
entry attempts are blocked. Those agents produce no trading evidence, so the fitness function (which scores a negative
trading record worse than inactivity) ranked them ABOVE active agents and selected them as parents by tie-break.

Design (Option D): nothing about the DNA, sizing, risk or agent status changes. Each blocked entry is annotated on its
Decision; an agent whose entry attempts are (almost) all blocked is reported as untestable and is excluded from
survivor RANKING instead of being penalised or rewarded.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.evolution.breeding import select_survivors
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.decision import Decision
from app.schemas.strategy_dna import PositionSizing
from tests.helpers_agents import cycle, make_agents, make_context, make_dna

GEN = 100


def _tiny():   # 5% x $100 = a $5 entry: below the $10 minimum on every bar
    return make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))


def _viable():  # 10% x $100 = exactly the $10 minimum
    return make_dna(position_sizing=PositionSizing(fraction_of_equity=0.1))


async def _run_bars(db, n, monkeypatch, *, min_blocked=3):
    s = get_settings()
    monkeypatch.setattr(s, "paper_min_order_notional", 10.0)
    monkeypatch.setattr(s, "untestable_min_blocked_entries", min_blocked, raising=False)
    eng = PaperExecutionAdapter()
    for i in range(1, n + 1):
        await cycle(db, eng, make_context(i, 100.0, rsi=65.0))


# --------------------------------------------------------------------------- #
# per-decision annotation
# --------------------------------------------------------------------------- #
async def test_blocked_entry_decision_records_the_minimum_it_missed(db_session, monkeypatch):
    await make_agents(db_session, [_tiny()])
    await _run_bars(db_session, 1, monkeypatch)
    (decision,) = (await db_session.execute(select(Decision))).scalars().all()
    assert "below_min_order_notional" in decision.risk_reasoning["reasons"]
    assert decision.risk_reasoning["min_order_notional"] == 10.0
    assert decision.risk_reasoning["approved_notional"] == pytest.approx(5.0)


# --------------------------------------------------------------------------- #
# classification (pure)
# --------------------------------------------------------------------------- #
def test_untestable_rule_thresholds():
    from app.agents.tradability import is_untestable

    assert is_untestable(blocked=500, executed=0, min_blocked=20, blocked_share=0.95) is True
    assert is_untestable(blocked=190, executed=10, min_blocked=20, blocked_share=0.95) is True     # exactly 95% blocked
    assert is_untestable(blocked=180, executed=20, min_blocked=20, blocked_share=0.95) is False    # 90%: it does get tested
    assert is_untestable(blocked=19, executed=0, min_blocked=20, blocked_share=0.95) is False      # too little evidence to say
    assert is_untestable(blocked=0, executed=0, min_blocked=20, blocked_share=0.95) is False       # never signalled: NOT untestable


# --------------------------------------------------------------------------- #
# classification from real decision-loop output
# --------------------------------------------------------------------------- #
async def test_only_the_agent_whose_entries_are_blocked_is_untestable(db_session, monkeypatch):
    from app.agents.tradability import untestable_agent_ids

    tiny, viable = await make_agents(db_session, [_tiny(), _viable()])
    await _run_bars(db_session, 5, monkeypatch, min_blocked=3)
    flagged = await untestable_agent_ids(db_session, [tiny, viable])
    assert flagged == {tiny.id}


async def test_too_few_blocked_entries_is_not_enough_to_call_an_agent_untestable(db_session, monkeypatch):
    from app.agents.tradability import untestable_agent_ids

    (tiny,) = await make_agents(db_session, [_tiny()])
    await _run_bars(db_session, 2, monkeypatch, min_blocked=3)
    assert await untestable_agent_ids(db_session, [tiny]) == set()


# --------------------------------------------------------------------------- #
# selection: excluded from RANKING, not penalised and not rewarded
# --------------------------------------------------------------------------- #
async def test_untestable_agent_is_never_selected_as_a_survivor_even_with_the_top_fitness(db_session, monkeypatch):
    tiny, viable = await make_agents(db_session, [_tiny(), _viable()])
    await _run_bars(db_session, 5, monkeypatch, min_blocked=3)
    tiny.fitness, viable.fitness = 0.5, -0.2          # inaction outranks a losing trader under the current fitness
    await db_session.commit()

    survivors = await select_survivors(db_session, generation_number=GEN, survivor_count=1)
    assert [a.id for a in survivors] == [viable.id]


async def test_exclusion_can_be_switched_off_to_reproduce_the_old_ranking(db_session, monkeypatch):
    tiny, viable = await make_agents(db_session, [_tiny(), _viable()])
    await _run_bars(db_session, 5, monkeypatch, min_blocked=3)
    tiny.fitness, viable.fitness = 0.5, -0.2
    await db_session.commit()

    survivors = await select_survivors(db_session, generation_number=GEN, survivor_count=1, exclude_untestable=False)
    assert [a.id for a in survivors] == [tiny.id]


async def test_agents_without_any_blocked_entries_rank_exactly_as_before(db_session, monkeypatch):
    a, b, c = await make_agents(db_session, [_viable(), _viable(), _viable()])
    a.fitness, b.fitness, c.fitness = 0.1, 0.9, 0.4
    await db_session.commit()
    survivors = await select_survivors(db_session, generation_number=GEN, survivor_count=3)
    assert [x.id for x in survivors] == [b.id, c.id, a.id]
