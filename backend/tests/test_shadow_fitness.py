"""Phase 0 SHADOW fitness: unit, isolation and acceptance tests.

The proposed fitness is evaluated NEXT TO the production fitness and must not influence anything: survivor selection,
breeding, mutation, champion selection, agent death or agent status.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
from sqlalchemy import func, select

from app.analytics import shadow_fitness as sf
from app.analytics.shadow_fitness import (
    PROVISIONAL, TESTED, UNTESTABLE, UNTESTED, ShadowAgentInput, TradeEvidence, champion_evidence_ok, compute_shadow,
    rank_correlation, ranked,
)
from tests.helpers_shadow import make_population, make_trades, scaled, with_extra_cost


def _agent(agent_id, trades, current=0.0, untestable=False, family=None):
    return ShadowAgentInput(agent_id=agent_id, trades=trades, current_fitness=current, untestable=untestable, family=family)


def _pop(rng, n_agents=40, days=14, lam=10.0):
    """A generation of ordinary traders (so the population prior is estimable)."""
    return [_agent(i, make_trades(rng, rng.choice([-0.3, -0.1, 0.0, 0.2]), lam, days)) for i in range(n_agents)]


# --------------------------------------------------------------------------- #
# evidence states
# --------------------------------------------------------------------------- #
def test_states_follow_the_specification():
    rng = np.random.default_rng(1)
    pop = _pop(rng)
    pop += [
        _agent("inert", []),
        _agent("few", make_trades(rng, 0.3, 1.0, 3)[:3]),                  # 3 trades: an estimate, but not a reliable one
        _agent("many", make_trades(rng, 0.0, 30.0, 14)),
        _agent("blocked", make_trades(rng, 0.0, 30.0, 14), untestable=True),
    ]
    by_id = {r.agent_id: r for r in compute_shadow(pop)}
    for unit in ("R", "bps"):
        assert by_id["inert"].unit(unit).state == UNTESTED
        assert by_id["few"].unit(unit).state == PROVISIONAL
        assert by_id["many"].unit(unit).state == TESTED
        assert by_id["blocked"].unit(unit).state == UNTESTABLE       # even though it has trades
        for aid in ("inert", "blocked"):
            assert by_id[aid].unit(unit).proposed_fitness is None    # no evidence: neither rewarded nor penalised
        # a provisional agent has a posterior (evidence is kept) but is not ranked unless the policy says so
        assert by_id["few"].unit(unit).proposed_fitness == by_id["few"].unit(unit).posterior_mean
        assert by_id["many"].unit(unit).proposed_fitness == by_id["many"].unit(unit).posterior_mean
    rows = list(by_id.values())
    assert "few" not in [r.agent_id for r in ranked(rows, "R")]
    assert "few" in [r.agent_id for r in ranked(rows, "R", include_provisional=True)]
    assert "inert" not in [r.agent_id for r in ranked(rows, "R", include_provisional=True)]


def test_row_carries_every_side_by_side_field():
    rows = compute_shadow(_pop(np.random.default_rng(2)))
    r = rows[0]
    for field in ("current_fitness", "trade_count", "net_pnl", "net_bps", "mean_r", "drawdown", "expectancy"):
        assert hasattr(r, field)
    for unit in (r.r, r.bps):
        for field in ("posterior_mean", "posterior_variance", "reliability", "state", "proposed_fitness"):
            assert hasattr(unit, field)


def test_units_are_kept_separate_and_no_primary_is_chosen():
    r = compute_shadow(_pop(np.random.default_rng(3)))[0]
    assert r.r.unit == "R" and r.bps.unit == "bps" and r.r is not r.bps
    assert not hasattr(r, "proposed_fitness")            # deliberately no single 'proposed' score


# --------------------------------------------------------------------------- #
# acceptance: inert / untestable
# --------------------------------------------------------------------------- #
def test_inert_agents_are_never_rewarded_even_when_the_traders_lose():
    rng = np.random.default_rng(4)
    # a generation whose traders all lose money: under the current fitness the inert agents would sit near the top
    traders = [_agent(i, make_trades(rng, -0.30, 12.0, 14)) for i in range(60)]
    inert = [_agent(f"inert{i}", []) for i in range(120)]
    rows = compute_shadow(traders + inert)
    for unit in ("R", "bps"):
        top = ranked(rows, unit, top=25)
        assert top and not any(str(r.agent_id).startswith("inert") for r in top)
        assert all(r.unit(unit).state == TESTED for r in top)
    assert all(r.r.proposed_fitness is None and r.bps.proposed_fitness is None for r in rows if r.trade_count == 0)


def test_untestable_agents_are_excluded_from_the_prior_and_from_ranking():
    rng = np.random.default_rng(5)
    good = [_agent(i, make_trades(rng, 0.0, 12.0, 14)) for i in range(40)]
    poison = [_agent(f"u{i}", make_trades(rng, 5.0, 12.0, 14), untestable=True) for i in range(40)]   # absurdly 'profitable'
    with_poison = compute_shadow(good + poison)
    without = compute_shadow(good)
    ids = {r.agent_id: r for r in with_poison}
    assert all(ids[f"u{i}"].r.state == UNTESTABLE and ids[f"u{i}"].r.proposed_fitness is None for i in range(40))
    # the untestable agents did not move the population prior: the testable agents' scores are identical
    for a, b in zip([ids[i] for i in range(40)], without):
        assert a.r.posterior_mean == pytest.approx(b.r.posterior_mean) and a.bps.posterior_mean == pytest.approx(b.bps.posterior_mean)


# --------------------------------------------------------------------------- #
# acceptance: exposure scaling
# --------------------------------------------------------------------------- #
def test_score_is_invariant_to_pure_exposure_scaling():
    rng = np.random.default_rng(6)
    trades = [make_trades(rng, rng.choice([-0.3, 0.0, 0.2]), 10.0, 14) for _ in range(50)]
    base = compute_shadow([_agent(i, t) for i, t in enumerate(trades)])
    for k in (0.25, 3.0, 10.0):
        big = compute_shadow([_agent(i, scaled(t, k)) for i, t in enumerate(trades)])
        for a, b in zip(base, big):
            for unit in ("R", "bps"):
                assert a.unit(unit).posterior_mean == pytest.approx(b.unit(unit).posterior_mean, rel=1e-9, abs=1e-12)
                assert a.unit(unit).reliability == pytest.approx(b.unit(unit).reliability, rel=1e-9)
                assert a.unit(unit).state == b.unit(unit).state
    # ... while raw P&L, the thing the current fitness leans on, obviously is NOT invariant
    assert not np.isclose(base[0].net_pnl, big[0].net_pnl) or base[0].trade_count == 0


# --------------------------------------------------------------------------- #
# acceptance: champion evidence cannot come from a lucky short streak
# --------------------------------------------------------------------------- #
def test_lucky_short_streak_cannot_trigger_champion_evidence():
    rng = np.random.default_rng(7)
    pop = _pop(rng, n_agents=60)
    lucky8 = _agent("lucky8", [TradeEvidence(net_pnl=0.10, notional=20.0, risk=0.05)] * 8)               # 8 wins in a row, +2R each
    lucky25 = _agent("lucky25", [TradeEvidence(net_pnl=0.05, notional=20.0, risk=0.05)] * 25)              # 25 x +1R
    genuine = _agent("genuine", make_trades(rng, 0.25, 30.0, 14))                                           # ~420 trades, real +0.25R
    rows = {r.agent_id: r for r in compute_shadow(pop + [lucky8, lucky25, genuine])}
    for unit in ("R", "bps"):
        assert not champion_evidence_ok(rows["lucky8"].unit(unit))
        assert not champion_evidence_ok(rows["lucky25"].unit(unit))
        assert rows["lucky8"].unit(unit).state == PROVISIONAL
    assert champion_evidence_ok(rows["genuine"].r)
    # an untestable / untested agent can never have champion evidence
    assert not champion_evidence_ok(compute_shadow([_agent("x", [])] + pop)[0].r)


# --------------------------------------------------------------------------- #
# acceptance: current vs proposed on identical data
# --------------------------------------------------------------------------- #
def test_current_and_proposed_are_comparable_on_identical_data_and_deterministic():
    pop = make_population(11, n_agents=120, days=14)
    a = compute_shadow(pop.agents)
    b = compute_shadow(pop.agents)
    assert [r.agent_id for r in a] == [r.agent_id for r in b] == [x.agent_id for x in pop.agents]
    assert [r.r.posterior_mean for r in a] == [r.r.posterior_mean for r in b]          # deterministic
    for r, src in zip(a, pop.agents):
        assert r.current_fitness == src.current_fitness                                 # the production score is carried untouched
    for unit in ("R", "bps"):
        rho, n = rank_correlation(a, "current", unit)
        assert n > 20 and rho is not None and -1.0 <= rho <= 1.0
    assert len(ranked(a, "current", top=10)) == 10


# --------------------------------------------------------------------------- #
# isolation: the shadow must not influence production
# --------------------------------------------------------------------------- #
PRODUCTION_MODULES = [
    "app.evolution.breeding", "app.evolution.champion", "app.evolution.promotion_service",
    "app.evolution.champion_challenger_service", "app.evolution.mutation", "app.evolution.crossover",
    "app.evolution.diversity", "app.analytics.fitness_engine", "app.analytics.fitness_service",
    "app.agents.lifecycle", "app.agents.decision_loop", "app.agents.position_manager", "app.research.pipeline",
    "app.worker.cycle", "app.execution.router",
]


@pytest.mark.parametrize("module", PRODUCTION_MODULES)
def test_production_modules_never_import_the_shadow(module):
    import importlib

    src = inspect.getsource(importlib.import_module(module))
    assert "shadow_fitness" not in src, f"{module} must not depend on the shadow evaluation"


def test_shadow_module_has_no_write_path():
    src = inspect.getsource(sf)
    for forbidden in (".add(", ".commit(", ".flush(", ".delete(", "update(", "insert(", "AgentStatus", "mark_dead"):
        assert forbidden not in src, f"shadow_fitness must stay read-only ({forbidden})"


async def _seed_agent_with_trades(db, dna, pnls, *, stop_offset=0.5):
    from app.models.enums import Side
    from app.models.trading import Position, Trade
    from tests.helpers_agents import make_agents

    (agent,) = await make_agents(db, [dna])
    now = datetime.now(timezone.utc)
    for p in pnls:
        pos = Position(id=uuid.uuid4(), agent_id=agent.id, symbol="SOL", side=Side.LONG, quantity=0.2, entry_price=100.0,
                       stop_loss_price=100.0 - stop_offset, is_open=False, opened_at=now, closed_at=now)
        db.add(pos)
        await db.flush()
        db.add(Trade(agent_id=agent.id, position_id=pos.id, symbol="SOL", side=Side.LONG, quantity=0.2, entry_price=100.0,
                     exit_price=100.0, gross_pnl=p, fees=0.0, net_pnl=p, opened_at=now, closed_at=now, holding_seconds=60,
                     exit_reason="take_profit"))
    await db.commit()
    return agent


async def test_db_service_derives_r_and_bps_and_writes_nothing(db_session):
    from app.models.agent import Agent
    from app.models.decision import Decision
    from app.models.trading import Order, Position, Trade
    from tests.helpers_agents import make_dna

    agent = await _seed_agent_with_trades(db_session, make_dna(), [0.05, -0.10, 0.20])
    agent.fitness = 0.123                                   # the production score, as written by fitness_service
    await db_session.commit()

    async def counts():
        return [(await db_session.execute(select(func.count()).select_from(m))).scalar_one() for m in (Agent, Trade, Position, Order, Decision)]

    before, status_before = await counts(), agent.status
    rows = await sf.shadow_rows_for_generation(db_session, agent.generation)
    (row,) = rows
    # R = pnl / (qty * |entry - stop|) = pnl / (0.2 * 0.5) ; bps = 1e4 * pnl / (qty * entry) = 1e4 * pnl / 20
    assert row.current_fitness == 0.123 and row.trade_count == 3
    assert row.mean_r == pytest.approx(np.mean([0.05, -0.10, 0.20]) / 0.1)
    assert row.net_bps == pytest.approx(1e4 * 0.15 / 60.0)
    assert row.r.n == row.bps.n == 3 and row.r.state == PROVISIONAL
    # read-only: nothing added, changed or deleted; production score and status untouched
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert await counts() == before
    await db_session.refresh(agent)
    assert agent.fitness == 0.123 and agent.status == status_before


async def test_db_service_flags_untestable_agents_from_option_d(db_session, monkeypatch):
    from app.core.config import get_settings
    from app.execution.paper_adapter import PaperExecutionAdapter
    from app.schemas.strategy_dna import PositionSizing
    from tests.helpers_agents import cycle, make_agents, make_context, make_dna

    s = get_settings()
    monkeypatch.setattr(s, "paper_min_order_notional", 10.0)
    monkeypatch.setattr(s, "untestable_min_blocked_entries", 3)
    (tiny,) = await make_agents(db_session, [make_dna(position_sizing=PositionSizing(fraction_of_equity=0.05))])
    for i in range(1, 6):
        await cycle(db_session, PaperExecutionAdapter(), make_context(i, 100.0, rsi=65.0))
    (row,) = await sf.shadow_rows_for_generation(db_session, tiny.generation)
    assert row.r.state == UNTESTABLE and row.bps.state == UNTESTABLE and row.r.proposed_fitness is None
