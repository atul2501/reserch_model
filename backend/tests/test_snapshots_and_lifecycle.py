"""Immutable snapshots (phase 32), death & generation rollover (phase 31)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.agents.lifecycle import retire_generation
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import AgentStatus
from app.models.strategy import AgentSnapshot, ImmutableRecordError, StrategyVersion
from app.models.trading import Position, Trade
from app.research.snapshots import create_agent_snapshot
from tests.helpers_agents import cycle, make_agents, make_context, make_dna
from tests.test_backtest_parity import ema_cross_dna

pytestmark = pytest.mark.usefixtures("immediate_fills")   # position mechanics; see conftest.immediate_fills

BACKEND = Path(__file__).resolve().parents[1]


async def _snapshot(db):
    (agent,) = await make_agents(db, [ema_cross_dna(5, 20)])
    version = await db.get(StrategyVersion, agent.strategy_version_id)
    agent.fitness = 0.42
    snap = await create_agent_snapshot(db, agent, version, experiment_id="EXP-TEST-1", dataset_fingerprint="ab" * 32)
    await db.commit()
    return agent, version, snap


async def test_snapshot_contains_everything_needed_to_reproduce_an_agent(db_session):
    agent, version, snap = await _snapshot(db_session)
    assert snap.agent_id == agent.id and snap.strategy_id == version.strategy_id and snap.strategy_version_number == 1
    assert snap.generation == 100 and snap.strategy_dna == version.dna and snap.fitness == 0.42
    assert {"risk_profile", "position_sizing", "stop_loss", "take_profit", "trailing_stop", "cooldown", "global"} <= set(snap.risk_config)
    assert snap.indicator_config["indicators"] and snap.indicator_config["engine_version"]
    assert "regime_preferences" in snap.regime_config and "ollama_model" in snap.model_config_snapshot
    assert snap.experiment_id == "EXP-TEST-1" and snap.dataset_fingerprint == "ab" * 32
    assert snap.software_version and snap.schema_version and snap.created_at is not None


async def test_snapshot_is_immutable_at_the_orm_level(db_session):
    _, _, snap = await _snapshot(db_session)
    snap.fitness = 9.99
    with pytest.raises(ImmutableRecordError):
        await db_session.flush()
    await db_session.rollback()
    with pytest.raises(ImmutableRecordError):
        await db_session.delete(snap)
        await db_session.flush()
    await db_session.rollback()


async def test_strategy_version_dna_cannot_be_edited(db_session):
    (agent,) = await make_agents(db_session, [ema_cross_dna(5, 20)])
    vid = agent.strategy_version_id
    version = await db_session.get(StrategyVersion, vid)
    version.dna = {**version.dna, "max_trades_per_day": 999}
    with pytest.raises(ImmutableRecordError):
        await db_session.flush()
    await db_session.rollback()
    # documented mutable fields (stage / champion status) still work
    version = await db_session.get(StrategyVersion, vid)
    await db_session.refresh(version)
    from app.models.enums import StrategyStage
    version.stage = StrategyStage.SHADOW
    await db_session.flush()


def _alembic(db, *args):
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db}")
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180)


def test_database_triggers_block_raw_updates_and_deletes_of_snapshots_and_dna(tmp_path):
    """Even a raw SQL UPDATE/DELETE cannot bypass immutability (migration triggers)."""
    db = tmp_path / "t.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    con = sqlite3.connect(db)
    now = "2026-01-01 00:00:00"
    con.execute("INSERT INTO strategies (id, code, family, name, description, created_at, updated_at) VALUES ('s1','C1','MOMENTUM','n','', ?, ?)", (now, now))
    con.execute("INSERT INTO strategy_versions (id, strategy_id, version, generation, dna, stage, hypothesis, proposed_by, created_at, updated_at) "
                "VALUES ('v1','s1',1,1,'{\"a\":1}','PAPER','','system',?,?)", (now, now))
    con.execute("INSERT INTO generations (id, number, population_target, population_created, starting_balance, total_capital_allocated, triggered_by, notes, created_at, updated_at) VALUES ('g1',1,1,1,100,100,'x','',?,?)", (now, now))
    con.execute("INSERT INTO agents (id, identifier, generation, strategy_version_id, status, starting_balance, balance, equity, realized_pnl, fees_paid, funding_paid, peak_equity, max_drawdown, day_start_equity, day_start_date, trade_count, daily_trade_count, is_professional, best_milestone_multiple, created_at, updated_at) "
                "VALUES ('a1','GEN01-AG0001',1,'v1','ACTIVE',100,100,100,0,0,0,100,0,100,'2026-01-01',0,0,0,1,?,?)", (now, now))
    con.execute("INSERT INTO agent_snapshots (id, agent_id, strategy_version_id, generation, strategy_dna, risk_config, indicator_config, model_config_snapshot, regime_config, performance_metrics, software_version, schema_version, created_at, updated_at) "
                "VALUES ('sn1','a1','v1',1,'{}','{}','{}','{}','{}','{}','x','y',?,?)", (now, now))
    con.commit()
    for sql in ("UPDATE agent_snapshots SET fitness = 5 WHERE id='sn1'", "DELETE FROM agent_snapshots WHERE id='sn1'",
                "UPDATE strategy_versions SET dna = '{\"a\":2}' WHERE id='v1'"):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            con.execute(sql)
    con.execute("UPDATE strategy_versions SET stage = 'SHADOW' WHERE id='v1'")   # non-DNA columns stay editable
    con.commit()
    con.close()


async def test_retire_generation_closes_positions_freezes_results_and_never_touches_the_dead(db_session, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "paper_latency_ms", 0)
    monkeypatch.setattr(get_settings(), "paper_latency_jitter_ms", 0)
    a1, a2, a3 = await make_agents(db_session, [make_dna(), make_dna(), make_dna()])
    a3.status, a3.death_reason, a3.equity = AgentStatus.DEAD, "equity_depleted", 0.0
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    open_before = (await db_session.execute(select(Position).where(Position.is_open.is_(True)))).scalars().all()
    assert len(open_before) == 2
    res = await retire_generation(db_session, 100, mark_price=103.0, at=datetime.now(timezone.utc), fee_rate=0.00045)
    await db_session.commit()
    assert res == {"retired": 2, "positions_closed": 2}
    for a in (a1, a2):
        await db_session.refresh(a)
        assert a.status == AgentStatus.RETIRED and a.final_equity == pytest.approx(a.equity) and a.final_pnl is not None
        assert a.final_pnl == pytest.approx(a.equity - a.starting_balance)
    await db_session.refresh(a3)
    assert a3.status == AgentStatus.DEAD and a3.death_reason == "equity_depleted"
    trades = (await db_session.execute(select(Trade))).scalars().all()
    assert {t.exit_reason for t in trades} == {"generation_rollover"} and all(t.net_pnl > 0 for t in trades)
    assert (await db_session.execute(select(Position).where(Position.is_open.is_(True)))).first() is None


async def test_dead_agent_death_record_is_complete_and_permanent(db_session):
    from app.agents.lifecycle import AgentAlreadyDeadError, mark_dead, update_equity
    (agent,) = await make_agents(db_session, [make_dna()])
    update_equity(agent, 0.0)
    assert agent.status == AgentStatus.DEAD and agent.death_reason == "equity_depleted"
    assert agent.death_timestamp is not None and agent.final_equity == 0.0 and agent.final_pnl == -100.0 and agent.generation == 100
    assert agent.strategy_version_id is not None       # -> generation / strategy version stay attributable
    with pytest.raises(AgentAlreadyDeadError):
        update_equity(agent, 500.0)                     # cannot be revived by an equity update
    mark_dead(agent, reason="other")                    # idempotent: reason is not overwritten
    assert agent.death_reason == "equity_depleted"


async def test_bankruptcy_threshold_is_configurable(db_session, monkeypatch):
    from app.agents.lifecycle import update_equity
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "agent_bankruptcy_equity_fraction", 0.05)
    (agent,) = await make_agents(db_session, [make_dna()])
    update_equity(agent, 6.0)
    assert agent.status == AgentStatus.ACTIVE
    update_equity(agent, 4.9)
    assert agent.status == AgentStatus.DEAD


async def test_every_new_generation_gets_fresh_100_dollars_and_old_agents_are_not_reset(db_session):
    from app.agents.lifecycle import create_generation
    (old,) = await make_agents(db_session, [make_dna()], generation=100)
    old.balance = old.equity = 250.0
    await db_session.commit()
    dna = make_dna()
    from app.models.strategy import Strategy
    from app.models.enums import StrategyFamily
    strat = Strategy(code="S-NEW", family=StrategyFamily.MOMENTUM, name="n")
    db_session.add(strat)
    await db_session.flush()
    v = StrategyVersion(strategy_id=strat.id, version=1, generation=101, dna=dna.model_dump(mode="json"))
    db_session.add(v)
    await db_session.flush()
    await create_generation(db_session, generation_number=101, strategy_version_ids=[v.id], starting_balance=100.0)
    new = (await db_session.execute(select(__import__("app.models.agent", fromlist=["Agent"]).Agent).where(
        __import__("app.models.agent", fromlist=["Agent"]).Agent.generation == 101))).scalar_one()
    assert new.balance == new.equity == new.starting_balance == 100.0 and new.identifier.startswith("GEN101-")
    await db_session.refresh(old)
    assert old.equity == 250.0 and old.identifier.startswith("GEN100-")
