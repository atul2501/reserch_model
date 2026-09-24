"""Impossible states cannot be written (spec phase 26): the DATABASE rejects them, not only Python validation."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.constraints import CHECKS
from app.models.decision import Decision
from app.models.enums import Bias, ExecutionVenue, OrderStatus, RiskDecision, Side
from app.models.market import MarketCandle
from app.models.system import WorkerCycle, WorkerLease
from app.models.trading import Order, Position, Trade
from tests.helpers_agents import closed_position, make_agents, make_dna

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


_generation = iter(range(200, 10_000))


class _Ref:
    """Plain ids of an agent - usable after a rollback has expired the ORM object."""

    def __init__(self, a):
        self.id, self.strategy_version_id = a.id, a.strategy_version_id


async def _agent(db):
    (a,) = await make_agents(db, [make_dna()], generation=next(_generation))     # unique generation per agent
    return _Ref(a)


async def _rejects(db, *objs, match: str):
    for o in objs:
        db.add(o)
    with pytest.raises(IntegrityError, match=match):
        await db.flush()
    await db.rollback()


def _order(agent, **kw):
    base = dict(agent_id=agent.id, client_order_id=f"c-{uuid.uuid4().hex}", symbol="SOL", side=Side.LONG, quantity=1.0,
                venue=ExecutionVenue.PAPER, status=OrderStatus.FAILED)
    base.update(kw)
    return Order(**base)


def _position(agent, **kw):
    base = dict(agent_id=agent.id, symbol="SOL", side=Side.LONG, quantity=1.0, entry_price=100.0, is_open=True, opened_at=NOW)
    base.update(kw)
    return Position(**base)


# --- accounts -------------------------------------------------------------------------------------------------------------


async def test_an_account_cannot_have_a_negative_balance_or_bad_debt(db_session):
    a = await _agent(db_session)
    from app.models.agent import Agent
    obj = await db_session.get(Agent, a.id)
    obj.balance = -0.01
    with pytest.raises(IntegrityError, match="ck_agents_balance_nonneg"):
        await db_session.flush()
    await db_session.rollback()
    await _agent(db_session)   # a fresh, valid agent for the raw UPDATEs below
    from sqlalchemy import update
    from app.models.agent import Agent
    for col, val, name in (("bad_debt", -1.0, "ck_agents_bad_debt_nonneg"), ("starting_balance", 0.0, "ck_agents_starting_positive"),
                           ("fees_paid", -0.5, "ck_agents_fees_nonneg"), ("trade_count", -1, "ck_agents_counters_nonneg")):
        with pytest.raises(IntegrityError, match=name):
            await db_session.execute(update(Agent).values(**{col: val}))
        await db_session.rollback()


# --- positions --------------------------------------------------------------------------------------------------------------------


async def test_impossible_positions_are_rejected(db_session):
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, quantity=0), match="ck_positions_quantity_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, entry_price=0), match="ck_positions_entry_price_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, leverage=0), match="ck_positions_leverage_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, initial_margin=-1), match="ck_positions_margin_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, is_open=True, closed_at=NOW), match="ck_positions_open_closed_consistent")
    a = await _agent(db_session)
    await _rejects(db_session, _position(a, is_open=False, closed_at=None), match="ck_positions_open_closed_consistent")


async def test_valid_open_and_closed_positions_are_accepted(db_session):
    a = await _agent(db_session)
    db_session.add(_position(a))
    db_session.add(_position(a, is_open=False, closed_at=NOW))
    await db_session.commit()


async def test_a_second_open_position_for_one_agent_is_rejected(db_session):
    a = await _agent(db_session)
    db_session.add(_position(a))
    await db_session.commit()
    await _rejects(db_session, _position(a), match="uq_position_one_open_per_agent|UNIQUE")


# --- orders: quantities, notionals and the state machine ------------------------------------------------------------------------------


async def test_impossible_order_quantities_and_notionals_are_rejected(db_session):
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, quantity=-1), match="ck_orders_quantity_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, approved_notional=-5.0), match="ck_orders_notional_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, requested_notional=-5.0), match="ck_orders_notional_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, leverage=0), match="ck_orders_leverage_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, filled_quantity=-1), match="ck_orders_fill_fields_nonneg")


async def test_an_order_cannot_be_filled_without_a_fill(db_session):
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, status=OrderStatus.FILLED), match="ck_orders_filled_has_a_fill")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, status=OrderStatus.FILLED, filled_price=100.0, filled_quantity=0.0), match="ck_orders_filled_has_a_fill")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, status=OrderStatus.PARTIALLY_FILLED, filled_quantity=0.5), match="ck_orders_filled_has_a_fill")
    a = await _agent(db_session)
    db_session.add(_order(a, status=OrderStatus.FILLED, filled_price=100.0, filled_quantity=1.0))
    db_session.add(_order(a, status=OrderStatus.FAILED))               # a failed order has no fill and that is fine
    db_session.add(_order(a, status=OrderStatus.CANCELLED))
    await db_session.commit()


async def test_a_pending_order_is_by_definition_unfilled(db_session):
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, status=OrderStatus.PENDING, filled_price=100.0), match="ck_orders_pending_is_unfilled")
    a = await _agent(db_session)
    await _rejects(db_session, _order(a, status=OrderStatus.PENDING, filled_at=NOW), match="ck_orders_pending_is_unfilled")


async def test_an_agent_can_have_only_one_pending_entry_order(db_session):
    a = await _agent(db_session)
    db_session.add(_order(a, status=OrderStatus.PENDING))
    await db_session.commit()
    await _rejects(db_session, _order(a, status=OrderStatus.PENDING), match="uq_order_one_pending_entry_per_agent|UNIQUE")
    # a PENDING *exit* (reduce-only) or a settled order does not count against the limit
    db_session.add(_order(a, status=OrderStatus.PENDING, reduce_only=True))
    db_session.add(_order(a, status=OrderStatus.CANCELLED))
    await db_session.commit()


async def test_duplicate_decisions_and_client_order_ids_are_rejected(db_session):
    a = await _agent(db_session)
    dup = _order(a)
    db_session.add(dup)
    await db_session.commit()
    await _rejects(db_session, _order(a, client_order_id=dup.client_order_id), match="client_order_id|UNIQUE")

    def decision():
        return Decision(id=uuid.uuid4(), agent_id=a.id, strategy_version_id=a.strategy_version_id, market_candle_open_time=42,
                        market_timestamp=NOW, agent_signal=Bias.LONG, agent_signal_confidence=0.5, agent_signal_reasoning={},
                        final_signal=Bias.LONG, risk_decision=RiskDecision.APPROVED, risk_reasoning={})

    db_session.add(decision())
    await db_session.commit()
    await _rejects(db_session, decision(), match="uq_decision_agent_candle|UNIQUE")


# --- trades / market data / worker ------------------------------------------------------------------------------------------------------


def _trade(agent, db, **kw):
    base = dict(agent_id=agent.id, position_id=closed_position(db, agent), symbol="SOL", side=Side.LONG, quantity=1.0,
                entry_price=100.0, exit_price=101.0, gross_pnl=1.0, fees=0.1, net_pnl=0.9, opened_at=NOW, closed_at=NOW,
                holding_seconds=60, exit_reason="signal")
    base.update(kw)
    return Trade(**base)


async def test_impossible_trades_are_rejected(db_session):
    a = await _agent(db_session)
    await _rejects(db_session, _trade(a, db_session, quantity=0), match="ck_trades_quantity_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _trade(a, db_session, exit_price=0), match="ck_trades_prices_positive")
    a = await _agent(db_session)
    await _rejects(db_session, _trade(a, db_session, fees=-0.1), match="ck_trades_fees_and_bad_debt_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _trade(a, db_session, bad_debt=-1.0), match="ck_trades_fees_and_bad_debt_nonneg")
    a = await _agent(db_session)
    await _rejects(db_session, _trade(a, db_session, holding_seconds=-5), match="ck_trades_holding_nonneg")
    a = await _agent(db_session)
    db_session.add(_trade(a, db_session, funding=-0.3))                   # RECEIVING funding is legitimate
    await db_session.commit()


def _candle(**kw):
    base = dict(symbol="SOL", timeframe="1m", open_time=1, close_time=60_000, open=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)
    base.update(kw)
    return MarketCandle(**base)


async def test_impossible_candles_are_rejected(db_session):
    await _rejects(db_session, _candle(high=98.0), match="ck_candles_ohlcv_sane")
    await _rejects(db_session, _candle(volume=-1.0), match="ck_candles_ohlcv_sane")
    await _rejects(db_session, _candle(low=0.0, high=1.0, open=0.5, close=0.5), match="ck_candles_ohlcv_sane")
    db_session.add(_candle())
    await db_session.commit()


async def test_worker_cycle_status_and_lease_epoch_are_constrained(db_session):
    await _rejects(db_session, WorkerCycle(cycle_id="x1", candle_timestamp=1, cycle_started_at=1.0, status="BOGUS"),
                   match="ck_worker_cycles_status")
    await _rejects(db_session, WorkerCycle(cycle_id="x2", candle_timestamp=1, cycle_started_at=1.0, status="STARTED", attempts=0),
                   match="ck_worker_cycles_attempts_positive")
    await _rejects(db_session, WorkerLease(name="n", owner_id="o", expires_at=1.0, epoch=-1), match="ck_worker_leases_epoch_nonneg")
    for status in ("STARTED", "COMPLETED", "FAILED", "FAILED_PERMANENT", "SKIPPED_CATCHUP"):
        db_session.add(WorkerCycle(cycle_id=f"ok-{status}", candle_timestamp=2, cycle_started_at=1.0, status=status))
    await db_session.commit()


# --- the model list and the migration cannot drift apart ---------------------------------------------------------------------------------


def _migration_module():
    path = BACKEND / "alembic" / "versions" / "b7d1f3a9c5e2_db_check_constraints.py"
    spec = importlib.util.spec_from_file_location("mig_b7d1", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_migration_carries_exactly_the_models_constraints():
    assert _migration_module().CHECKS == CHECKS


# --- the migration's pre-flight -----------------------------------------------------------------------------------------------------------


def _alembic(db: Path, *args):
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db}")
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=240)


def _insert(con, table, **values):
    cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(values)
    for _cid, name, ctype, notnull, default, _pk in cols:
        if name in row or not notnull or default is not None:
            continue
        t = (ctype or "").upper()
        row[name] = 0 if any(k in t for k in ("INT", "FLOAT", "REAL", "NUMERIC", "BOOL")) else ("{}" if "JSON" in t else
                    (datetime.now(timezone.utc).isoformat() if "DATE" in t else ""))
    con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))


def test_migration_refuses_when_existing_rows_violate_a_constraint_and_changes_nothing(tmp_path):
    db = tmp_path / "legacy.db"
    assert _alembic(db, "upgrade", "a6c2e8f4b0d7").returncode == 0          # the schema BEFORE the constraints
    con = sqlite3.connect(db)
    _insert(con, "strategies", id="s1", code="C1", family="MOMENTUM", name="n")
    _insert(con, "strategy_versions", id="v1", strategy_id="s1", version=1, generation=1, dna="{}", stage="PAPER")
    _insert(con, "agents", id="a1", identifier="GEN01-AG0001", generation=1, strategy_version_id="v1", status="ACTIVE",
            starting_balance=100.0, balance=-5.0, equity=-5.0, peak_equity=100.0, day_start_equity=100.0)   # legacy bad row
    con.commit()
    con.close()

    r = _alembic(db, "upgrade", "head")
    assert r.returncode != 0
    assert "ck_agents_balance_nonneg" in r.stderr and "refusing to add database constraints" in r.stderr
    con = sqlite3.connect(db)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "a6c2e8f4b0d7"   # nothing was applied
    assert con.execute("SELECT balance FROM agents").fetchone()[0] == -5.0                            # and no data was touched
    con.execute("UPDATE agents SET balance = 5.0")                                                    # the operator repairs the row ...
    con.commit()
    con.close()
    assert _alembic(db, "upgrade", "head").returncode == 0                                            # ... and the retry succeeds


def test_migration_downgrade_removes_the_constraints(tmp_path):
    db = tmp_path / "d.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert _alembic(db, "downgrade", "-1").returncode == 0
    con = sqlite3.connect(db)
    _insert(con, "strategies", id="s1", code="C1", family="MOMENTUM", name="n")
    _insert(con, "strategy_versions", id="v1", strategy_id="s1", version=1, generation=1, dna="{}", stage="PAPER")
    _insert(con, "agents", id="a1", identifier="GEN01-AG0001", generation=1, strategy_version_id="v1", status="ACTIVE",
            starting_balance=100.0, balance=-5.0, equity=-5.0, peak_equity=100.0, day_start_equity=100.0)
    con.commit()                                                                                       # allowed again: constraints gone
    con.close()
