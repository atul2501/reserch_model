"""Dashboard/API surface (spec phases 35-37): confirmed-candle market view,
population, agent detail, council, evolution, shadow, status/health, SSE, metrics."""
from __future__ import annotations

import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio

from app.core import metrics
from app.core.config import get_settings
from app.core.database import get_db
from app.core.runtime_status import WORKER, publish_status
from app.core.security import hash_api_key
from app.main import create_app
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.enums import ExecutionVenue, OrderStatus, Side
from app.models.market import MarketCandle
from app.models.system import WorkerCycle
from app.models.trading import Order
from app.worker.lease import try_acquire
from tests.helpers_agents import cycle, make_agents, make_context, make_dna

V, O = "viewer-key-1234", "operator-key-1234"


@pytest_asyncio.fixture
async def api(db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", True)
    monkeypatch.setattr(s, "api_keys", f"v:viewer:{hash_api_key(V)},o:operator:{hash_api_key(O)}")
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)
    app = create_app()

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.headers.update({"X-API-Key": V})
        yield c


def candle(i, final=True, close=100.0, age_s=None):
    t = int(time.time() * 1000) - (age_s or 0) * 1000 if age_s is not None else 1_700_000_040_000 + i * 60_000
    open_time = (t // 60_000) * 60_000
    return MarketCandle(symbol="SOL", timeframe="1m", open_time=open_time, close_time=open_time + 59_999, open=close, high=close, low=close,
                        close=close, volume=1.0, is_final=final)


async def test_market_endpoint_reports_the_confirmed_candle_and_keeps_the_forming_one_separate(db_session, api):
    now_ms = int(time.time() * 1000)
    last_closed = (now_ms // 60_000 - 1) * 60_000
    db_session.add_all([
        MarketCandle(symbol="SOL", timeframe="1m", open_time=last_closed, close_time=last_closed + 59_999, open=150, high=151, low=149,
                     close=150.5, volume=10, is_final=True),
        MarketCandle(symbol="SOL", timeframe="1m", open_time=last_closed + 60_000, close_time=last_closed + 119_999, open=150.5,
                     high=152, low=150, close=151.9, volume=3, is_final=False),
    ])
    await db_session.commit()
    r = (await api.get("/api/market")).json()
    assert r["close_price"] == 150.5 and r["candle_open_time"] == last_closed          # NOT the forming candle
    assert r["live_price"] == 151.9 and r["live_candle_open_time"] == last_closed + 60_000
    assert r["data_freshness_seconds"] is not None and r["market_data_stale"] is False
    hist = (await api.get("/api/market/history")).json()
    assert [h["close"] for h in hist] == [150.5]                                        # history excludes open bars


async def test_population_and_agent_detail_endpoints(db_session, api):
    agents = await make_agents(db_session, [make_dna(), make_dna(), make_dna()])
    from app.models.enums import AgentStatus
    agents[2].status, agents[2].equity = AgentStatus.DEAD, 0.0
    await db_session.commit()
    await cycle(db_session, __import__("app.execution.paper_adapter", fromlist=["x"]).PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    pop = (await api.get("/api/population")).json()
    assert pop["active_count"] == 2 and pop["dead_count"] == 1 and pop["total_count"] == 3 and pop["generations_total"] == 1
    assert pop["best_equity"] is not None and pop["worst_equity"] == 0.0

    aid = str(agents[0].id)
    dna = (await api.get(f"/api/agents/{aid}/dna")).json()
    assert dna["family"] == "momentum" and dna["dna"]["entry_rules"] and dna["strategy_version"] == 1 and dna["generation"] == 100
    curve = (await api.get(f"/api/agents/{aid}/equity-curve")).json()
    assert curve["points"][0]["equity"] == 100.0 and "current_equity" in curve
    assert (await api.get(f"/api/agents/{aid}/regime-performance")).status_code == 200
    assert (await api.get(f"/api/agents/{aid}/fitness")).status_code == 200
    assert (await api.get(f"/api/agents/{uuid.uuid4()}/dna")).status_code == 404


async def test_council_endpoints_expose_analysts_failures_latency_and_judge(db_session, api):
    d = CouncilDecision(market_candle_open_time=1, market_timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                        consensus_bias="LONG", consensus_confidence=0.7, vote_tally={"LONG": 5, "SHORT": 1, "NEUTRAL": 0}, judge_invoked=True,
                        judge_response={"decision": "LONG"}, final_bias="LONG", final_confidence=0.7, key_risks=[], invalidators=[],
                        council_status="INCOMPLETE", expected_analysts=8, successful_analysts=6, failed_analysts=["risk", "regime"],
                        failure_reasons={"risk": "analyst_timeout", "regime": "ollama_unavailable"}, quorum_met=False, trade_allowed=False,
                        council_start=1.0, total_council_latency_seconds=12.5)
    db_session.add(d)
    await db_session.flush()
    db_session.add(CouncilAnalysis(council_decision_id=d.id, analyst="trend", bias="LONG", confidence=0.8, reasoning="r", key_factors=[],
                                   invalidators=[], request_id="rid", latency_ms=900, model="m", was_valid=True,
                                   started_at=d.market_timestamp, completed_at=d.market_timestamp))
    await db_session.commit()
    latest = (await api.get("/api/council/latest")).json()
    assert latest["status"] == "INCOMPLETE" and latest["trade_allowed"] is False and latest["failure_reasons"]["risk"] == "analyst_timeout"
    assert latest["latency_seconds"] == 12.5 and latest["judge"] == {"decision": "LONG"} and latest["analysts"][0]["analyst"] == "trend"
    assert len((await api.get("/api/council/history")).json()) == 1


async def test_evolution_endpoints(db_session, api):
    from app.models.enums import EvolutionEventType
    from app.models.evolution import EvolutionEvent
    await make_agents(db_session, [make_dna()])
    db_session.add(EvolutionEvent(event_type=EvolutionEventType.CROSSOVER, generation=101, accepted=True, validation_result={}))
    await db_session.commit()
    gens = (await api.get("/api/evolution/generations")).json()
    assert gens[0]["number"] == 100 and gens[0]["by_status"]["ACTIVE"]["count"] == 1
    ev = (await api.get("/api/evolution/events")).json()
    assert ev[0]["type"] == "CROSSOVER"
    summ = (await api.get("/api/evolution/summary")).json()
    assert summ["births"] == 1 and summ["event_counts"]["CROSSOVER"] == 1
    assert (await api.get("/api/evolution/experiments")).status_code == 200


async def test_shadow_summary_reports_expected_vs_actual_and_zero_real_orders(db_session, api):
    (agent,) = await make_agents(db_session, [make_dna()])
    for i, slip in enumerate((1.0, 3.0)):
        db_session.add(Order(agent_id=agent.id, client_order_id=f"sh-{i}", symbol="SOL", side=Side.LONG, quantity=1, venue=ExecutionVenue.SHADOW,
                             status=OrderStatus.FILLED, latency_ms=300, raw_venue_response={"sent_to_exchange": False, "slippage_bps": slip,
                                                                                            "drift_after_latency_bps": 2.0}))
    await db_session.commit()
    r = (await api.get("/api/shadow/summary")).json()
    assert r["orders"] == 2 and r["fill_rate"] == 1.0 and r["avg_slippage_bps"] == pytest.approx(2.0)
    assert r["avg_drift_after_latency_bps"] == pytest.approx(2.0) and r["avg_latency_ms"] == 300 and r["sent_to_exchange"] == 0


# ------------------------------------------------------------- health / status -------------- #
async def test_status_says_worker_down_when_no_heartbeat_and_ok_when_fresh(db_session, api):
    db_session.add(candle(0, age_s=20))
    await db_session.commit()
    s = (await api.get("/api/system/status")).json()
    assert s["worker"]["status"] == "unknown" and s["overall"] != "ok"        # nothing has ever run

    await try_acquire(db_session, "w1", ttl_seconds=90)                        # fresh heartbeat
    db_session.add(WorkerCycle(cycle_id="c1", candle_timestamp=1, cycle_started_at=time.time() - 5, cycle_completed_at=time.time() - 1,
                               cycle_latency_seconds=4.0, completed=True, status="COMPLETED", council_status="COMPLETE", agents_processed=500))
    await db_session.commit()
    s = (await api.get("/api/system/status")).json()
    assert s["worker"]["status"] == "ok" and s["worker"]["last_cycle"]["latency_seconds"] == 4.0
    assert s["worker"]["last_cycle"]["agents_processed"] == 500 and s["market_data"]["status"] == "ok" and s["overall"] == "ok"

    await try_acquire(db_session, "w1", ttl_seconds=90, now=time.time() - 1000)   # heartbeat long ago -> lease expired
    s = (await api.get("/api/system/status")).json()
    assert s["worker"]["status"] == "down" and s["overall"] == "down"        # the dashboard must show this loudly


async def test_status_reports_stale_market_data_and_data_gap_halt(db_session, api):
    from app.core.system_flags import DATA_GAP_HALT, set_flag
    db_session.add(candle(0, age_s=900))
    await db_session.commit()
    s = (await api.get("/api/system/status")).json()
    assert s["market_data"]["status"] == "down" and s["market_data"]["freshness_seconds"] > 800
    await set_flag(db_session, DATA_GAP_HALT, True, reason="gap")
    await db_session.commit()
    assert (await api.get("/api/system/status")).json()["market_data"]["data_gap_halt"] is True


async def test_status_surfaces_ollama_key_health_and_websocket_state_from_the_worker(db_session, api):
    await publish_status(db_session, WORKER, {
        "ollama_keys": [{"key_index": 0, "status": "unhealthy", "last_error_status": 401}, {"key_index": 1, "status": "healthy"}],
        "websocket": {"connected": False, "stale": True}, "last_council": {"status": "INCOMPLETE"}})
    s = (await api.get("/api/system/status")).json()
    assert s["ollama"]["status"] == "degraded" and s["ollama"]["keys"][0]["last_error_status"] == 401
    assert s["hyperliquid"]["status"] in ("degraded", "down") and s["council"]["status"] == "INCOMPLETE"
    await publish_status(db_session, WORKER, {"ollama_keys": [{"key_index": 0, "status": "unhealthy"}], "websocket": None})
    assert (await api.get("/api/system/status")).json()["ollama"]["status"] == "down"


async def test_health_returns_503_when_the_database_is_down(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", False)
    app = create_app()

    class Broken:
        def get_bind(self):
            raise RuntimeError("db down")
        async def execute(self, *a, **k):
            raise RuntimeError("db down")

    async def _db():
        yield Broken()

    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/system/health")
    assert r.status_code == 503 and r.json()["database_ok"] is False


# ---------------------------------------------------------------- SSE + metrics ------------ #
async def test_sse_stream_emits_status_and_cycle_events(db_session, api):
    db_session.add(WorkerCycle(cycle_id="sse-1", candle_timestamp=5, cycle_started_at=time.time() - 3, cycle_completed_at=time.time() - 1,
                               cycle_latency_seconds=2.0, completed=True, status="COMPLETED"))
    await db_session.commit()
    events = []
    async with api.stream("GET", "/api/stream?max_events=2&interval=0.5") as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    assert "status" in events and "cycle" in events


async def test_sse_requires_authentication(api):
    r = await api.get("/api/stream?max_events=1", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


async def test_metrics_endpoint_is_operator_only_and_exposes_the_required_series(db_session, api):
    metrics.reset()
    metrics.inc("ollama_requests", outcome="401")
    metrics.inc("ollama_requests", outcome="429")
    metrics.inc("council_quorum_failures")
    assert (await api.get("/metrics")).status_code == 403                    # viewer key
    await make_agents(db_session, [make_dna()])
    await publish_status(db_session, WORKER, {"metrics_text": 'orders_total{kind="entry",status="FILLED"} 7'})
    r = await api.get("/metrics", headers={"X-API-Key": O})
    assert r.status_code == 200
    body = r.text
    for series in ('ollama_requests_total{outcome="401"} 1.0', 'ollama_requests_total{outcome="429"} 1.0', "council_quorum_failures_total 1.0",
                   'agents{status="ACTIVE"} 1', "population_equity", 'component_up{component="database"} 1',
                   'orders_total{kind="entry",status="FILLED"} 7'):
        assert series in body, series


async def test_ollama_health_endpoint_needs_operator_and_never_leaks_key_values(db_session, api):
    await publish_status(db_session, WORKER, {"ollama_keys": [{"key_index": 0, "status": "healthy", "failure_count": 0}]})
    assert (await api.get("/api/system/ollama")).status_code == 403
    r = await api.get("/api/system/ollama", headers={"X-API-Key": O})
    assert r.status_code == 200 and r.json()["keys"][0]["key_index"] == 0
    assert "key_value" not in r.text and "Bearer" not in r.text


async def test_population_reports_trade_counts_open_positions_and_win_rate(db_session, api):
    from app.execution.paper_adapter import PaperExecutionAdapter
    agents = await make_agents(db_session, [make_dna(), make_dna()])
    eng = PaperExecutionAdapter()
    c1 = make_context(1, 100.0, rsi=65.0)
    await cycle(db_session, eng, c1)                                           # both enter
    empty = (await api.get("/api/population")).json()
    assert empty["total_trades"] == 0 and empty["open_positions"] == 2 and empty["win_rate"] is None
    await cycle(db_session, eng, make_context(2, 103.0, rsi=30.0), c1)         # both exit in profit
    pop = (await api.get("/api/population")).json()
    assert pop["total_trades"] == 2 and pop["generation_trades"] == 2
    assert pop["open_positions"] == 0 and pop["win_rate"] == 1.0
