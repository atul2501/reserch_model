"""Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md Phase 4).

Describes CURRENT behavior only - nothing here is a design opinion about what
decision_loop.py *should* do. This is the fixed, deterministic scenario Phase 4.1+
will re-run and diff against after each extraction step: it exercises next-open
fill mechanics (entry AND signal-exit), position management (survival, stop-loss),
the mandatory protection sweep (an agent from a DIFFERENT, never-cycled generation),
invalid-DNA pausing, and per-agent SAVEPOINT isolation, in one deterministic run
across four candles.

Comparison strategy: `capture_state()` returns a plain, JSON-serializable dict keyed
by the agents' deterministic `identifier` (e.g. "GEN100-AG0001", not the random
`Agent.id` UUID), with rows within each agent sorted by candle time. Excluded,
because they are legitimately nondeterministic across separate runs:
  - every table's `id` primary key (random uuid4 default - see app/models/base.py)
  - every row's `created_at`/`updated_at` (real wall-clock `utcnow()` default)
  - `Agent.death_timestamp` (real wall-clock `datetime.now()` in lifecycle.mark_dead)
  - `Order.client_order_id` / `Decision.id` (deterministic, but derived FROM the
    random `Agent.id`, so they differ across runs even though nothing behavioral
    changed - `Decision.market_candle_open_time` is used as the stable key instead)
  - `Order.latency_ms` / `raw_venue_response` (PaperExecutionAdapter's simulated
    latency; pinned to 0 by conftest.py's env defaults for all unit tests, but
    excluded anyway so this file does not silently depend on that pin)
Everything else - every price, quantity, fee, PnL, balance, status, exit reason,
risk decision and reasoning - is included and IS expected to be 100% stable across
runs and across Phase 4.1+'s extraction, because it derives only from the fixed
inputs below and the CANDLE clock (never the wall clock).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agents.lifecycle import format_agent_identifier
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import AgentStatus, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Position, Trade
from app.schemas.strategy_dna import StopLossConfig
from tests.helpers_agents import cycle, make_agents, make_context, make_dna
from tests.test_position_protection import open_position


async def _invalid_dna_agent(db, *, generation: int, index_in_generation: int) -> Agent:
    """One agent whose stored DNA no longer validates (schema drift), added into
    an ALREADY-EXISTING generation (must be the same generation the scenario
    cycles - invalid-DNA pausing is a per-agent-loop pre-filter, unlike the
    mandatory sweep, so it only ever runs for the generation actually cycled).
    DNA is immutable in the DB, so it is created invalid, mirroring
    test_position_protection.py's `_invalid_dna_agents`."""
    strat = Strategy(code=f"S-DRIFT-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="drifted")
    db.add(strat)
    await db.flush()
    v = StrategyVersion(strategy_id=strat.id, version=1, generation=generation, dna={"not": "a valid dna"})
    db.add(v)
    await db.flush()
    agent = Agent(
        identifier=format_agent_identifier(generation, index_in_generation), generation=generation,
        strategy_version_id=v.id, status=AgentStatus.ACTIVE, starting_balance=100.0, balance=100.0, equity=100.0,
        peak_equity=100.0, day_start_equity=100.0, day_start_date=datetime.now(timezone.utc).date(),
    )
    db.add(agent)
    await db.flush()
    return agent


def _round(x, nd=8):
    return round(x, nd) if isinstance(x, (int, float)) else x


async def capture_state(db) -> dict:
    """See module docstring for exactly what is/isn't included and why."""
    agents = (await db.execute(select(Agent))).scalars().all()
    out: dict = {}
    for a in sorted(agents, key=lambda a: a.identifier):
        positions = (
            await db.execute(select(Position).where(Position.agent_id == a.id).order_by(Position.opened_at))
        ).scalars().all()
        orders = (
            await db.execute(select(Order).where(Order.agent_id == a.id).order_by(Order.submitted_at))
        ).scalars().all()
        trades = (
            await db.execute(select(Trade).where(Trade.agent_id == a.id).order_by(Trade.closed_at))
        ).scalars().all()
        decisions = (
            await db.execute(
                select(Decision).where(Decision.agent_id == a.id).order_by(Decision.market_candle_open_time)
            )
        ).scalars().all()
        out[a.identifier] = {
            "agent": {
                "status": a.status.value, "generation": a.generation,
                "balance": _round(a.balance), "equity": _round(a.equity),
                "realized_pnl": _round(a.realized_pnl), "fees_paid": _round(a.fees_paid),
                "funding_paid": _round(a.funding_paid), "bad_debt": _round(a.bad_debt),
                "trade_count": a.trade_count, "daily_trade_count": a.daily_trade_count,
                "day_start_equity": _round(a.day_start_equity),
                "max_drawdown": _round(a.max_drawdown), "best_milestone_multiple": _round(a.best_milestone_multiple),
                "death_reason": a.death_reason, "died": a.death_timestamp is not None,
                "final_equity": _round(a.final_equity) if a.final_equity is not None else None,
                "final_pnl": _round(a.final_pnl) if a.final_pnl is not None else None,
            },
            "positions": [
                {
                    "side": p.side.value, "quantity": _round(p.quantity), "entry_price": _round(p.entry_price),
                    "entry_candle_open_time": p.entry_candle_open_time, "is_open": p.is_open,
                    "stop_loss_price": _round(p.stop_loss_price) if p.stop_loss_price is not None else None,
                    "take_profit_price": _round(p.take_profit_price) if p.take_profit_price is not None else None,
                    "trailing_active": p.trailing_active,
                    "last_processed_open_time": p.last_processed_open_time,
                    "unrealized_pnl": _round(p.unrealized_pnl),
                    "entry_fee": _round(p.entry_fee), "entry_slippage_cost": _round(p.entry_slippage_cost),
                }
                for p in positions
            ],
            "orders": [
                {
                    "side": o.side.value, "status": o.status.value, "reduce_only": o.reduce_only,
                    "order_kind": o.order_kind, "signal_candle_open_time": o.signal_candle_open_time,
                    "quantity": _round(o.quantity), "requested_notional": _round(o.requested_notional),
                    "approved_notional": _round(o.approved_notional),
                    "filled_price": _round(o.filled_price) if o.filled_price is not None else None,
                    "filled_quantity": _round(o.filled_quantity) if o.filled_quantity is not None else None,
                    "fee": _round(o.fee) if o.fee is not None else None,
                    "rejection_reason": o.rejection_reason,
                }
                for o in orders
            ],
            "trades": [
                {
                    "side": t.side.value, "quantity": _round(t.quantity), "entry_price": _round(t.entry_price),
                    "exit_price": _round(t.exit_price), "gross_pnl": _round(t.gross_pnl), "fees": _round(t.fees),
                    "funding": _round(t.funding), "slippage_cost": _round(t.slippage_cost),
                    "net_pnl": _round(t.net_pnl), "bad_debt": _round(t.bad_debt), "exit_reason": t.exit_reason,
                    "holding_seconds": t.holding_seconds, "stage": t.stage.value if t.stage else None,
                }
                for t in trades
            ],
            "decisions": [
                {
                    "market_candle_open_time": d.market_candle_open_time, "agent_signal": d.agent_signal.value,
                    "final_signal": d.final_signal.value, "risk_decision": d.risk_decision.value,
                    "risk_reasoning": d.risk_reasoning, "has_order": d.order_id is not None,
                    "has_trade": d.trade_id is not None,
                }
                for d in decisions
            ],
        }
    return out


STOP_LOOSE = StopLossConfig(method="atr_multiple", value=2.0)   # ~99.0 for a 100-entry, atr=0.5 (make_dna's default)
STOP_TIGHT = StopLossConfig(method="atr_multiple", value=0.5)   # ~99.75 for the same entry - breached by candle 3


async def _build_scenario(db):
    """4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,
    tight stop), D (invalid DNA, never trades), E (a DIFFERENT, never-cycled
    generation - only the mandatory sweep can touch it). Returns them by role."""
    a, b = await make_agents(db, [make_dna(stop_loss=STOP_LOOSE), make_dna(stop_loss=STOP_TIGHT)], generation=100)
    d = await _invalid_dna_agent(db, generation=100, index_in_generation=3)   # same generation - see docstring above
    (e,) = await make_agents(db, [make_dna(stop_loss=STOP_LOOSE)], generation=99)
    await open_position(db, e, entry=100.0, stop=99.0)   # pre-existing - the sweep is the ONLY thing that can reach it
    await db.commit()
    return a, b, d, e


async def _run_fixed_scenario(db) -> dict:
    engine = PaperExecutionAdapter()
    await cycle(db, engine, make_context(1, 100.0, rsi=65.0))                       # entries signalled; D paused
    await cycle(db, engine, make_context(2, 100.0, rsi=65.0))                       # A, B fill + manage (survive)
    await cycle(db, engine, make_context(3, 99.6, low=99.5, rsi=30.0))              # B stops out; A's exit pending
    await cycle(db, engine, make_context(4, 99.6, rsi=45.0))                        # A's pending exit fills
    return await capture_state(db)


@pytest.mark.asyncio
async def test_fixed_scenario_is_internally_consistent(db_session):
    """Sanity checks independent of the golden snapshot below - these describe
    the invariants the scenario is DESIGNED to exercise, so a failure here means
    the scenario itself broke, not necessarily that decision_loop.py changed."""
    await _build_scenario(db_session)
    state = await _run_fixed_scenario(db_session)

    assert state["GEN100-AG0001"]["agent"]["status"] == "ACTIVE"          # A: exited, still alive
    assert len(state["GEN100-AG0001"]["trades"]) == 1
    assert state["GEN100-AG0001"]["trades"][0]["exit_reason"] == "exit_rules"

    assert len(state["GEN100-AG0002"]["trades"]) == 1                     # B: stopped out
    assert state["GEN100-AG0002"]["trades"][0]["exit_reason"] == "stop_loss"

    assert state["GEN100-AG0003"]["agent"]["status"] == "PAUSED"          # D: invalid DNA, flat
    assert state["GEN100-AG0003"]["trades"] == [] and state["GEN100-AG0003"]["decisions"] == []

    assert state["GEN99-AG0001"]["positions"][0]["is_open"] is True       # E: swept, never cycled, never closed
    assert state["GEN99-AG0001"]["positions"][0]["last_processed_open_time"] == make_context(4, 0).candle_open_time
    assert state["GEN99-AG0001"]["decisions"] == []   # the sweep's protective Decision rows are only kept when actionable

    # Books reconcile for every agent that traded (balance == starting + realized_pnl + bad_debt).
    for identifier, agent_row in ((k, v) for k, v in state.items() if v["agent"]["generation"] in (99, 100)):
        ag = agent_row["agent"]
        assert ag["balance"] == pytest.approx(100.0 + ag["realized_pnl"] + ag["bad_debt"], abs=1e-6), identifier


@pytest.mark.asyncio
async def test_fixed_scenario_matches_the_captured_baseline(db_session):
    """THE regression test: byte-for-byte (modulo the documented exclusions in the
    module docstring) comparison against a snapshot captured from this exact
    scenario against the CURRENT, unextracted decision_loop.py. Phase 4.1+ re-runs
    this file unmodified after each extraction step - any difference fails here."""
    await _build_scenario(db_session)
    state = await _run_fixed_scenario(db_session)
    assert state == _GOLDEN_STATE


_GOLDEN_STATE = {'GEN100-AG0001': {'agent': {'bad_debt': 0.0,
                             'balance': 99.947025,
                             'best_milestone_multiple': 1.0,
                             'daily_trade_count': 1,
                             'day_start_equity': 100.0,
                             'death_reason': None,
                             'died': False,
                             'equity': 99.947025,
                             'fees_paid': 0.008982,
                             'final_equity': None,
                             'final_pnl': None,
                             'funding_paid': 0.0,
                             'generation': 100,
                             'max_drawdown': 0.00052975,
                             'realized_pnl': -0.052975,
                             'status': 'ACTIVE',
                             'trade_count': 1},
                   'decisions': [{'agent_signal': 'LONG',
                                  'final_signal': 'LONG',
                                  'has_order': True,
                                  'has_trade': False,
                                  'market_candle_open_time': 1700000100000,
                                  'risk_decision': 'APPROVED',
                                  'risk_reasoning': {'approved_notional': 10.0,
                                                     'council': {'agent_signal': 'LONG',
                                                                 'council_bias': None,
                                                                 'council_confidence': None,
                                                                 'council_status': 'NOT_RUN',
                                                                 'final_signal': 'LONG',
                                                                 'reason': 'council_not_required',
                                                                 'size_modifier': 1.0},
                                                     'leverage': 1.0,
                                                     'margin': 10.0,
                                                     'reasons': [],
                                                     'requested_notional': 10.0,
                                                     'risk_amount': 0.1,
                                                     'sizing_method': 'fraction_of_equity'}},
                                 {'agent_signal': 'NEUTRAL',
                                  'final_signal': 'NEUTRAL',
                                  'has_order': False,
                                  'has_trade': False,
                                  'market_candle_open_time': 1700000220000,
                                  'risk_decision': 'APPROVED',
                                  'risk_reasoning': {'action': 'exit_signal_pending_next_open',
                                                     'exit_reason': 'exit_rules'}},
                                 {'agent_signal': 'NEUTRAL',
                                  'final_signal': 'NEUTRAL',
                                  'has_order': True,
                                  'has_trade': True,
                                  'market_candle_open_time': 1700000280000,
                                  'risk_decision': 'APPROVED',
                                  'risk_reasoning': {'action': 'close_position',
                                                     'exit_reason': 'exit_rules'}}],
                   'orders': [{'approved_notional': 10.0,
                               'fee': 0.0045009,
                               'filled_price': 100.020005,
                               'filled_quantity': 0.1,
                               'order_kind': 'market',
                               'quantity': 0.1,
                               'reduce_only': False,
                               'rejection_reason': None,
                               'requested_notional': 10.0,
                               'side': 'LONG',
                               'signal_candle_open_time': 1700000100000,
                               'status': 'FILLED'},
                              {'approved_notional': None,
                               'fee': 0.0044811,
                               'filled_price': 99.58007504,
                               'filled_quantity': 0.1,
                               'order_kind': 'market',
                               'quantity': 0.1,
                               'reduce_only': True,
                               'rejection_reason': None,
                               'requested_notional': None,
                               'side': 'LONG',
                               'signal_candle_open_time': None,
                               'status': 'FILLED'}],
                   'positions': [{'entry_candle_open_time': 1700000160000,
                                  'entry_fee': 0.0045009,
                                  'entry_price': 100.020005,
                                  'entry_slippage_cost': 0.0020005,
                                  'is_open': False,
                                  'last_processed_open_time': 1700000220000,
                                  'quantity': 0.1,
                                  'side': 'LONG',
                                  'stop_loss_price': 99.020005,
                                  'take_profit_price': 102.020005,
                                  'trailing_active': False,
                                  'unrealized_pnl': 0.0}],
                   'trades': [{'bad_debt': 0.0,
                               'entry_price': 100.020005,
                               'exit_price': 99.58007504,
                               'exit_reason': 'exit_rules',
                               'fees': 0.008982,
                               'funding': 0.0,
                               'gross_pnl': -0.043993,
                               'holding_seconds': 179,
                               'net_pnl': -0.052975,
                               'quantity': 0.1,
                               'side': 'LONG',
                               'slippage_cost': 0.003993,
                               'stage': 'RESEARCH'}]},
 'GEN100-AG0002': {'agent': {'bad_debt': 0.0,
                             'balance': 99.9450334,
                             'best_milestone_multiple': 1.0,
                             'daily_trade_count': 1,
                             'day_start_equity': 100.0,
                             'death_reason': None,
                             'died': False,
                             'equity': 99.9450334,
                             'fees_paid': 0.00898111,
                             'final_equity': None,
                             'final_pnl': None,
                             'funding_paid': 0.0,
                             'generation': 100,
                             'max_drawdown': 0.00054967,
                             'realized_pnl': -0.0549666,
                             'status': 'ACTIVE',
                             'trade_count': 1},
                   'decisions': [{'agent_signal': 'LONG',
                                  'final_signal': 'LONG',
                                  'has_order': True,
                                  'has_trade': False,
                                  'market_candle_open_time': 1700000100000,
                                  'risk_decision': 'APPROVED',
                                  'risk_reasoning': {'approved_notional': 10.0,
                                                     'council': {'agent_signal': 'LONG',
                                                                 'council_bias': None,
                                                                 'council_confidence': None,
                                                                 'council_status': 'NOT_RUN',
                                                                 'final_signal': 'LONG',
                                                                 'reason': 'council_not_required',
                                                                 'size_modifier': 1.0},
                                                     'leverage': 1.0,
                                                     'margin': 10.0,
                                                     'reasons': [],
                                                     'requested_notional': 10.0,
                                                     'risk_amount': 0.025,
                                                     'sizing_method': 'fraction_of_equity'}},
                                 {'agent_signal': 'NEUTRAL',
                                  'final_signal': 'NEUTRAL',
                                  'has_order': True,
                                  'has_trade': True,
                                  'market_candle_open_time': 1700000220000,
                                  'risk_decision': 'APPROVED',
                                  'risk_reasoning': {'action': 'close_position',
                                                     'exit_reason': 'stop_loss'}}],
                   'orders': [{'approved_notional': 10.0,
                               'fee': 0.0045009,
                               'filled_price': 100.020005,
                               'filled_quantity': 0.1,
                               'order_kind': 'market',
                               'quantity': 0.1,
                               'reduce_only': False,
                               'rejection_reason': None,
                               'requested_notional': 10.0,
                               'side': 'LONG',
                               'signal_candle_open_time': 1700000100000,
                               'status': 'FILLED'},
                              {'approved_notional': None,
                               'fee': 0.00448021,
                               'filled_price': 99.56015008,
                               'filled_quantity': 0.1,
                               'order_kind': 'stop',
                               'quantity': 0.1,
                               'reduce_only': True,
                               'rejection_reason': None,
                               'requested_notional': None,
                               'side': 'LONG',
                               'signal_candle_open_time': None,
                               'status': 'FILLED'}],
                   'positions': [{'entry_candle_open_time': 1700000160000,
                                  'entry_fee': 0.0045009,
                                  'entry_price': 100.020005,
                                  'entry_slippage_cost': 0.0020005,
                                  'is_open': False,
                                  'last_processed_open_time': 1700000220000,
                                  'quantity': 0.1,
                                  'side': 'LONG',
                                  'stop_loss_price': 99.770005,
                                  'take_profit_price': 100.520005,
                                  'trailing_active': False,
                                  'unrealized_pnl': 0.0}],
                   'trades': [{'bad_debt': 0.0,
                               'entry_price': 100.020005,
                               'exit_price': 99.56015008,
                               'exit_reason': 'stop_loss',
                               'fees': 0.00898111,
                               'funding': 0.0,
                               'gross_pnl': -0.04598549,
                               'holding_seconds': 119,
                               'net_pnl': -0.0549666,
                               'quantity': 0.1,
                               'side': 'LONG',
                               'slippage_cost': 0.00598549,
                               'stage': 'RESEARCH'}]},
 'GEN100-AG0003': {'agent': {'bad_debt': 0.0,
                             'balance': 100.0,
                             'best_milestone_multiple': 1.0,
                             'daily_trade_count': 0,
                             'day_start_equity': 100.0,
                             'death_reason': None,
                             'died': False,
                             'equity': 100.0,
                             'fees_paid': 0.0,
                             'final_equity': None,
                             'final_pnl': None,
                             'funding_paid': 0.0,
                             'generation': 100,
                             'max_drawdown': 0.0,
                             'realized_pnl': 0.0,
                             'status': 'PAUSED',
                             'trade_count': 0},
                   'decisions': [],
                   'orders': [],
                   'positions': [],
                   'trades': []},
 'GEN99-AG0001': {'agent': {'bad_debt': 0.0,
                            'balance': 100.0,
                            'best_milestone_multiple': 1.0,
                            'daily_trade_count': 0,
                            'day_start_equity': 100.0,
                            'death_reason': None,
                            'died': False,
                            'equity': 99.6,
                            'fees_paid': 0.0,
                            'final_equity': None,
                            'final_pnl': None,
                            'funding_paid': 0.0,
                            'generation': 99,
                            'max_drawdown': 0.004,
                            'realized_pnl': 0.0,
                            'status': 'ACTIVE',
                            'trade_count': 0},
                  'decisions': [],
                  'orders': [],
                  'positions': [{'entry_candle_open_time': None,
                                 'entry_fee': 0.0,
                                 'entry_price': 100.0,
                                 'entry_slippage_cost': 0.0,
                                 'is_open': True,
                                 'last_processed_open_time': 1700000280000,
                                 'quantity': 1.0,
                                 'side': 'LONG',
                                 'stop_loss_price': 99.0,
                                 'take_profit_price': None,
                                 'trailing_active': False,
                                 'unrealized_pnl': -0.4}],
                  'trades': []}}
