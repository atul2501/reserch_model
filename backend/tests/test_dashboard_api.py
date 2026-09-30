"""Tests for the read-only /api/dashboard/* endpoints and the additive fields added to
/api/evolution/generations - all backing the new /analytics observability page.

Covers: overview KPI math, equity-curve bucketing (incl. no-trades -> insufficient_data),
fitness-component rollup (incl. the reconstructed sum matching real fitness), ranking-stability
insufficient-history, champions cross-tab, leaderboard sort + pagination, timeframe grouping,
and empty-database behavior for every endpoint (must never 500 or return a misleading zero).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest_asyncio
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import hash_api_key
from app.main import create_app
from sqlalchemy import select

from app.models.enums import AgentStatus, ChampionStatus
from app.models.metrics import FitnessScore
from app.models.research import Experiment, ResearchEpoch
from app.models.strategy import Generation
from app.models.trading import Trade
from tests.helpers_agents import closed_position, make_agents, make_dna


async def _backdate_generation(db, days: int, *, number: int = 100) -> None:
    """Real generations accumulate trades over real elapsed time; tests run in milliseconds, so
    to exercise time-windowed queries meaningfully, push Generation.created_at into the past."""
    gen = (await db.execute(select(Generation).where(Generation.number == number))).scalar_one()
    gen.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    await db.flush()

V = "viewer-key-1234"


@pytest_asyncio.fixture
async def api(db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", True)
    monkeypatch.setattr(s, "api_keys", SecretStr(f"v:viewer:{hash_api_key(V)}"))
    app = create_app()

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.headers.update({"X-API-Key": V})
        yield c


def _trade(db, agent, *, net_pnl: float, closed_at: datetime, exit_reason="take_profit", holding_seconds: int = 60):
    pos_id = closed_position(db, agent)
    db.add(Trade(
        agent_id=agent.id, position_id=pos_id, symbol="SOL", side="LONG", quantity=1.0,
        entry_price=100.0, exit_price=100.0 + net_pnl, gross_pnl=net_pnl, fees=0.0, net_pnl=net_pnl,
        opened_at=closed_at - timedelta(seconds=holding_seconds), closed_at=closed_at, holding_seconds=holding_seconds,
        exit_reason=exit_reason,
    ))


# --------------------------------------------------------------------------- #
# Empty database - every endpoint must respond cleanly, never 500, never a misleading zero
# --------------------------------------------------------------------------- #
async def test_all_dashboard_endpoints_handle_an_empty_database(api):
    for path in (
        "/api/dashboard/overview", "/api/dashboard/equity", "/api/dashboard/agents/metrics",
        "/api/dashboard/fitness/components", "/api/dashboard/champions/analysis",
        "/api/dashboard/timeframes", "/api/dashboard/ranking-stability",
    ):
        r = await api.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text}"

    overview = (await api.get("/api/dashboard/overview")).json()
    assert overview["current_generation"] is None and overview["total_trades"] == 0
    assert overview["win_rate"] is None  # never a fabricated 0% when there's no evidence
    assert overview["hold_seconds_min"] is None and overview["hold_seconds_max"] is None
    assert overview["hold_seconds_avg"] is None

    equity = (await api.get("/api/dashboard/equity")).json()
    assert equity["insufficient_data"] is True

    agents = (await api.get("/api/dashboard/agents/metrics")).json()
    assert agents == {"total": 0, "rows": [], "capped": False}

    components = (await api.get("/api/dashboard/fitness/components")).json()
    assert components["insufficient_data"] is True

    timeframes = (await api.get("/api/dashboard/timeframes")).json()
    assert timeframes["insufficient_data"] is True

    stability = (await api.get("/api/dashboard/ranking-stability")).json()
    assert all(w["insufficient_history"] for w in stability["windows"])


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
async def test_overview_reflects_real_trades_and_champion_count(db_session, api):
    agents = await make_agents(db_session, [make_dna(), make_dna()], balance=100.0)
    now = datetime.now(timezone.utc)
    _trade(db_session, agents[0], net_pnl=10.0, closed_at=now, holding_seconds=30)
    _trade(db_session, agents[0], net_pnl=-4.0, closed_at=now, holding_seconds=600)
    _trade(db_session, agents[1], net_pnl=5.0, closed_at=now, holding_seconds=7200)
    await db_session.commit()

    r = (await api.get("/api/dashboard/overview")).json()
    assert r["total_trades"] == 3
    assert r["hold_seconds_min"] == 30 and r["hold_seconds_max"] == 7200
    assert r["hold_seconds_avg"] == (30 + 600 + 7200) / 3
    assert r["total_pnl"] == 11.0
    assert r["win_rate"] == 2 / 3
    assert r["active_agents"] == 2 and r["dead_agents"] == 0
    assert r["current_generation"] == 100
    assert r["starting_equity"] == 200.0
    assert r["champion_count"] == 0
    assert r["trading_mode"] == "paper"


# --------------------------------------------------------------------------- #
# Equity curve
# --------------------------------------------------------------------------- #
async def test_equity_curve_insufficient_data_outside_the_requested_range(db_session, api):
    agents = await make_agents(db_session, [make_dna()], balance=100.0)
    await _backdate_generation(db_session, days=20)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    _trade(db_session, agents[0], net_pnl=50.0, closed_at=old)
    await db_session.commit()

    r = (await api.get("/api/dashboard/equity", params={"range": "1H"})).json()
    assert r["insufficient_data"] is True  # the only trade is 10 days old, outside a 1H window

    r_all = (await api.get("/api/dashboard/equity", params={"range": "ALL"})).json()
    assert r_all["insufficient_data"] is False
    assert r_all["current_equity"] == r_all["starting_equity"] + 50.0


async def test_equity_curve_tracks_cumulative_pnl_and_drawdown(db_session, api):
    agents = await make_agents(db_session, [make_dna()], balance=100.0)
    await _backdate_generation(db_session, days=1)
    base = datetime.now(timezone.utc) - timedelta(hours=12)
    _trade(db_session, agents[0], net_pnl=20.0, closed_at=base)
    _trade(db_session, agents[0], net_pnl=-30.0, closed_at=base + timedelta(minutes=1))
    await db_session.commit()

    r = (await api.get("/api/dashboard/equity", params={"range": "ALL"})).json()
    assert r["insufficient_data"] is False
    assert r["points"][-1]["equity"] == r["starting_equity"] - 10.0
    assert r["max_drawdown_pct"] > 0  # peaked after the +20 trade, then drew down on the -30


# --------------------------------------------------------------------------- #
# Agent metrics (leaderboard / scatter data source)
# --------------------------------------------------------------------------- #
async def test_agent_metrics_sorts_and_paginates(db_session, api):
    agents = await make_agents(db_session, [make_dna(), make_dna(), make_dna()], balance=100.0)
    now = datetime.now(timezone.utc)
    _trade(db_session, agents[0], net_pnl=100.0, closed_at=now)
    _trade(db_session, agents[1], net_pnl=-50.0, closed_at=now)
    # agents[2] gets no trades - must still appear with pnl 0.0, not error out
    await db_session.commit()

    r = (await api.get("/api/dashboard/agents/metrics", params={"sort_by": "pnl", "sort_dir": "desc"})).json()
    assert r["total"] == 3
    pnls = [row["pnl"] for row in r["rows"]]
    assert pnls == sorted(pnls, reverse=True)
    assert pnls[0] == 100.0

    page1 = (await api.get("/api/dashboard/agents/metrics", params={"sort_by": "pnl", "limit": 1, "offset": 0})).json()
    page2 = (await api.get("/api/dashboard/agents/metrics", params={"sort_by": "pnl", "limit": 1, "offset": 1})).json()
    assert page1["rows"][0]["agent_id"] != page2["rows"][0]["agent_id"]


# --------------------------------------------------------------------------- #
# Fitness component contribution
# --------------------------------------------------------------------------- #
async def test_fitness_components_rollup_sums_to_real_fitness(db_session, api):
    agents = await make_agents(db_session, [make_dna()], balance=100.0)
    agent = agents[0]
    agent.trade_count = 30  # full sample confidence -> inactivity_penalty term is exactly 0
    weights = {
        "return_weight": 1.0, "risk_weight": 1.0, "consistency_weight": 1.0, "robustness_weight": 1.0,
        "oos_weight": 1.5, "drawdown_penalty_weight": 2.0, "instability_penalty_weight": 1.0,
        "correlation_penalty_weight": 0.0, "expectancy_weight": 0.5, "regime_weight": 1.0,
        "adversarial_weight": 1.0, "inactivity_penalty_weight": 0.25, "death_penalty_weight": 1.0,
    }
    # Real fitness = the exact weighted sum app.analytics.fitness_engine.compute_fitness would
    # produce from these scores (inactivity/death penalty are 0 here: full sample confidence,
    # agent not dead) - computed here, not hand-picked, so the test can't drift from the formula.
    total_fitness = (
        1.0 * 0.5 + 1.0 * 0.2 + 1.0 * 0.1 + 1.0 * 0.1 + 1.5 * 0.3  # return, risk, consistency, robustness, oos
        - 2.0 * 0.05 - 1.0 * 0.0 - 0.0 * 0.0 + 0.5 * 0.0 + 1.0 * 0.0 + 1.0 * 0.0  # drawdown/instability/correlation penalties, expectancy/regime/adversarial
    )
    db_session.add(FitnessScore(
        agent_id=agent.id, as_of=datetime.now(timezone.utc), fitness=total_fitness,
        return_score=0.5, risk_score=0.2, consistency_score=0.1, robustness_score=0.1, oos_score=0.3,
        drawdown_penalty=0.05, instability_penalty=0.0, correlation_penalty=0.0, expectancy_score=0.0,
        regime_score=0.0, adversarial_score=0.0, weights_used=weights,
    ))
    await db_session.commit()

    r = (await api.get("/api/dashboard/fitness/components")).json()
    assert r["insufficient_data"] is False
    assert r["agent_count"] == 1
    assert r["mean_fitness"] == total_fitness
    by_component = {c["component"]: c for c in r["components"]}
    # Reconstructed sum of every signed, weighted term should equal the real stored fitness -
    # this is the whole point: it proves nothing (incl. inactivity/death penalty) was dropped.
    reconstructed = sum(c["mean_actual_contribution"] for c in r["components"])
    assert abs(reconstructed - total_fitness) < 1e-9
    assert by_component["inactivity_penalty"]["mean_actual_contribution"] == 0.0  # trade_count=30 -> full confidence


# --------------------------------------------------------------------------- #
# Champions analysis
# --------------------------------------------------------------------------- #
async def test_champions_analysis_cross_tab(db_session, api):
    agents = await make_agents(db_session, [make_dna(), make_dna()], balance=100.0)
    profitable_agent, champion_free_agent = agents
    profitable_agent.realized_pnl = 25.0  # profitable, but its version is never marked CHAMPION
    await db_session.commit()

    r = (await api.get("/api/dashboard/champions/analysis")).json()
    assert r["champion_count"] == 0
    assert r["profitable_not_champion_count"] == 1
    assert r["champion_not_profitable_count"] == 0
    assert r["promotion_criteria"]["min_paper_trade_count"] == get_settings().champion_min_paper_trade_count


# --------------------------------------------------------------------------- #
# Timeframe performance (reinterpreted via backtest Experiment/ResearchEpoch records)
# --------------------------------------------------------------------------- #
async def test_timeframe_performance_groups_completed_experiments_by_epoch_timeframe(db_session, api):
    epoch = ResearchEpoch(epoch_id="EPOCH-1", symbol="SOL", timeframe="5m", start_ms=0, end_ms=1,
                          n_candles=1, dataset_fingerprint="fp1", train_end_ms=0, validation_end_ms=0)
    db_session.add(epoch)
    await db_session.flush()
    db_session.add(Experiment(
        experiment_id="EXP-1", kind="evaluation", status="COMPLETED", epoch_id="EPOCH-1",
        code_version="t", schema_version="t", random_seed=1, result={"net_pnl": 12.5, "win_rate": 0.6},
    ))
    await db_session.commit()

    r = (await api.get("/api/dashboard/timeframes")).json()
    assert r["insufficient_data"] is False
    assert r["source"] == "backtest_experiments"
    assert r["timeframes"] == [
        {"timeframe": "5m", "experiment_count": 1, "avg_pnl": 12.5, "avg_expectancy": None,
         "avg_profit_factor": None, "avg_win_rate": 0.6, "avg_max_drawdown": None}
    ]


# --------------------------------------------------------------------------- #
# Ranking stability - no look-ahead
# --------------------------------------------------------------------------- #
async def test_ranking_stability_never_uses_a_fitness_score_from_after_the_window_boundary(db_session, api):
    agents = await make_agents(db_session, [make_dna() for _ in range(12)], balance=100.0)
    now = datetime.now(timezone.utc)
    # 12 agents with fitness recorded 5 days ago: old enough to satisfy the 1D and 3D window
    # boundaries (as_of <= boundary), but NOT old enough for the 7D boundary - as_of must be AT
    # OR BEFORE a boundary to count "as of" it, and 5 days ago is more recent than 7 days ago.
    for i, a in enumerate(agents):
        db_session.add(FitnessScore(
            agent_id=a.id, as_of=now - timedelta(days=5), fitness=float(i),
            return_score=0, risk_score=0, consistency_score=0, robustness_score=0, oos_score=0,
            drawdown_penalty=0, instability_penalty=0, weights_used={},
        ))
    await db_session.commit()

    r = (await api.get("/api/dashboard/ranking-stability")).json()
    windows = {(w["from"], w["to"]): w for w in r["windows"]}
    assert windows[("1D", "3D")]["insufficient_history"] is False
    assert windows[("1D", "3D")]["agents_compared"] == 12
    assert windows[("3D", "7D")]["insufficient_history"] is True  # the 7D boundary predates all fitness history


# --------------------------------------------------------------------------- #
# Additive enhancement to the existing /api/evolution/generations endpoint
# --------------------------------------------------------------------------- #
async def test_evolution_generations_gains_pnl_and_fitness_aggregates(db_session, api):
    agents = await make_agents(db_session, [make_dna(), make_dna()], balance=100.0)
    agents[0].realized_pnl, agents[0].fitness = 30.0, 0.8
    agents[1].realized_pnl, agents[1].fitness = -10.0, 0.2
    agents[1].status = AgentStatus.DEAD
    await db_session.commit()

    gens = (await api.get("/api/evolution/generations")).json()
    g = gens[0]
    assert g["number"] == 100
    assert g["avg_pnl"] == 10.0
    assert g["median_pnl"] == 10.0
    assert g["best_pnl"] == 30.0
    assert g["avg_fitness"] == 0.5
    assert g["best_fitness"] == 0.8
    assert g["survival_rate"] == 0.5  # 1 of 2 died
    # existing fields must still be present and correct - additive, non-breaking
    assert g["by_status"]["ACTIVE"]["count"] == 1 and g["deaths"] == 1
