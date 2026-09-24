"""Every important metric is actually EMITTED by the code path it describes (spec phase 28), and the exposition is
well-formed (TYPE lines, escaped labels, bounded cardinality)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core import metrics
from app.core.config import get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from tests.helpers_agents import cycle, make_agents, make_context, make_dna
from tests.helpers_market import INTERVAL, FakeHyperliquid, clock_after_bar


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset()
    yield
    metrics.reset()


def series(name: str) -> str:
    return metrics.render_prometheus()


# --- exposition format ------------------------------------------------------------------------------------------------


def test_exposition_has_type_lines_and_escapes_label_values():
    metrics.inc("thing", reason='bad "quote"\nnewline\\slash')
    metrics.observe("lat_seconds", 0.5, kind="x")
    text = metrics.render_prometheus()
    assert "# TYPE thing_total counter" in text and "# TYPE lat_seconds summary" in text
    assert 'reason="bad \\"quote\\"\\nnewline\\\\slash"' in text          # no raw quote/newline can break the format
    assert all(not line or line.startswith("#") or " " in line for line in text.splitlines())


def test_label_cardinality_is_bounded():
    for i in range(metrics.MAX_SERIES_PER_METRIC + 50):
        metrics.inc("order_rejections", reason=f"free-text-{i}")
    text = metrics.render_prometheus()
    lines = [l for l in text.splitlines() if l.startswith("order_rejections_total")]
    assert len(lines) == metrics.MAX_SERIES_PER_METRIC + 1                # the cap + one overflow bucket
    assert metrics.counter_value("order_rejections", overflow="other") == 50


def test_the_dead_gauge_api_is_gone():
    assert not hasattr(metrics, "set_gauge") and not hasattr(metrics, "gauge_value")


# --- trading-path metrics ------------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("immediate_fills")
async def test_orders_fills_latency_and_slippage_are_emitted_for_entries_and_exits(db_session):
    await make_agents(db_session, [make_dna()])
    eng = PaperExecutionAdapter()
    await cycle(db_session, eng, make_context(1, 100.0, rsi=65.0))
    await cycle(db_session, eng, make_context(2, 101.0, rsi=30.0))
    text = metrics.render_prometheus()
    assert metrics.counter_value("orders", kind="entry", status="FILLED") == 1
    assert metrics.counter_value("orders", kind="exit", status="FILLED") == 1
    for kind in ("entry", "exit"):
        assert f'fill_latency_ms_count{{kind="{kind}"}}' in text and f'fill_slippage_cost_count{{kind="{kind}"}}' in text


@pytest.mark.usefixtures("immediate_fills")
async def test_risk_vetoes_carry_a_reason_label(db_session):
    await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0), trading_halt_override="kill_switch")
    assert metrics.counter_value("risk_vetoes", reason="trading_halted") == 1


@pytest.mark.usefixtures("immediate_fills")
async def test_order_rejections_are_counted_by_reason(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_reject_probability", 1.0)
    await make_agents(db_session, [make_dna()])
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    assert metrics.counter_value("order_rejections", reason="simulated_exchange_reject") == 1
    assert metrics.counter_value("orders", kind="entry", status="FAILED") == 1


@pytest.mark.usefixtures("immediate_fills")
async def test_agent_deaths_are_counted_by_reason(db_session):
    from datetime import datetime, timezone
    from app.models.enums import Side
    from app.models.trading import Position
    from tests.test_position_protection import open_position

    (agent,) = await make_agents(db_session, [make_dna()], balance=100.0)
    await open_position(db_session, agent, entry=100.0, qty=10.0, stop=None, leverage=10.0)
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 50.0, open_=50.0, high=50.5, low=49.0, rsi=50.0))
    assert sum(v for (n, l), v in metrics._counters.items() if n == "agents_died") == 1


# --- market data ------------------------------------------------------------------------------------------------------------


async def test_market_data_latency_errors_and_backfill_latency(db_session):
    from app.market.market_data_service import MarketDataService

    fake = FakeHyperliquid(n_candles=300)
    svc = MarketDataService(fake, clock_ms=lambda: clock_after_bar(299))
    await svc.sync_recent_candles(db_session, lookback_candles=300)
    assert "market_data_latency_seconds_count" in metrics.render_prometheus()
    from tests.helpers_market import T0
    await svc.backfill_history(db_session, T0, T0 + 10 * INTERVAL, page_bars=5)
    assert "market_data_backfill_latency_seconds_count" in metrics.render_prometheus()
    fake.fail_candles = True
    with pytest.raises(RuntimeError):
        await svc.sync_recent_candles(db_session, lookback_candles=300)
    assert metrics.counter_value("market_data_errors", operation="sync_recent_candles") == 1
    assert "market_data_latency_seconds_count" in metrics.render_prometheus()          # latency is observed on FAILURE too


# --- council / ollama -----------------------------------------------------------------------------------------------------------


async def test_council_failures_are_counted_per_analyst_and_per_quorum(db_session):
    from app.council.service import run_council_cycle
    from tests.test_council_service import ScriptedClient, _context

    await run_council_cycle(db_session, ScriptedClient(failing={"risk", "order_flow", "trend"}), _context())
    assert metrics.counter_value("council_analyst_failures", analyst="risk", reason="auth") == 1
    assert metrics.counter_value("council_analyst_failures", analyst="trend", reason="auth") == 1
    assert metrics.counter_value("council_quorum_failures") == 1
    assert metrics.counter_value("council_cycles", status="INCOMPLETE") == 1


async def test_ollama_latency_and_outcomes(monkeypatch):
    import json
    from pydantic import BaseModel
    from app.services.ollama_client import OllamaClient, OllamaKeyHealth

    class Echo(BaseModel):
        value: str

    c = OllamaClient()
    c._api_keys, c._key_health = ["k"], [OllamaKeyHealth()]
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"message": {"content": json.dumps({"value": "ok"})}})), base_url="http://fake")
    await c.generate_structured(system_prompt="s", user_prompt="u", response_model=Echo)
    assert metrics.counter_value("ollama_requests", outcome="ok") == 1 and "ollama_latency_ms_count" in metrics.render_prometheus()


# --- worker / database ---------------------------------------------------------------------------------------------------------


def test_cycle_latency_and_status_are_emitted_by_the_shared_recorder():
    from app.worker.cycle import CycleOutcome, record_cycle_metrics

    record_cycle_metrics([CycleOutcome("c1", 1, "COMPLETED", latency_seconds=1.25), CycleOutcome("c2", 2, "FAILED")])
    text = metrics.render_prometheus()
    assert metrics.counter_value("worker_cycles", status="COMPLETED") == 1 and metrics.counter_value("worker_cycles", status="FAILED") == 1
    assert "cycle_latency_seconds_count 1.0" in text and "cycle_latency_seconds_sum 1.25" in text


async def test_database_errors_are_counted_when_a_cycle_fails_on_the_database(db_session, monkeypatch):
    from app.market.market_data_service import MarketDataService
    from app.worker import cycle as cycle_mod
    from tests.test_worker_cycle import _setup, no_council  # noqa: F401

    fake, market = await _setup(db_session)

    async def broken(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

    monkeypatch.setattr(cycle_mod, "run_decision_cycle", broken)
    monkeypatch.setattr(get_settings(), "council_enabled", False)
    out = await cycle_mod.run_pending_cycles(db_session, market, None, execution_engine=PaperExecutionAdapter())
    assert out[0].status == "FAILED"
    assert metrics.counter_value("db_errors", operation="cycle") == 1


def test_record_db_error_helper():
    metrics.record_db_error("lease")
    assert metrics.counter_value("db_errors", operation="lease") == 1


async def test_the_lease_heartbeat_reports_db_errors_and_lease_loss(db_engine):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.worker.lease import LeaseKeeper

    healthy = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    broken = {"on": False}

    def factory():
        if broken["on"]:
            raise ConnectionError("db down")
        return healthy()

    k = LeaseKeeper(factory, owner_id="A", ttl_seconds=0.15, heartbeat_seconds=0.03)
    assert await k.acquire()
    broken["on"] = True
    await asyncio.wait_for(k.lost.wait(), timeout=2)
    assert metrics.counter_value("db_errors", operation="lease_heartbeat") >= 1
    assert metrics.counter_value("lease_lost", reason="local_ttl_expired") == 1
    await k.close()


# --- websocket ----------------------------------------------------------------------------------------------------------------------


async def test_ws_reconnects_are_counted():
    import asyncio, json
    from tests.test_ws_client import FakeServer, make, _run_until

    async def script(ws, idx):
        if idx == 0:
            await ws.close()
        await asyncio.sleep(0.5)

    async with FakeServer(script) as srv:
        client = make(srv.url, [])
        await _run_until(client, lambda: client.stats.connects >= 2)
    assert metrics.counter_value("ws_reconnects") >= 1


# --- audit -------------------------------------------------------------------------------------------------------------------------


async def test_kill_switch_changes_are_written_to_an_append_only_audit_trail(db_session, monkeypatch):
    from pydantic import SecretStr
    from app.core.database import get_db
    from app.core.security import hash_api_key
    from app.main import create_app
    from app.models.system import SystemEvent

    key = "operator-key-for-audit"
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", True)
    monkeypatch.setattr(s, "api_keys", SecretStr(f"ops:operator:{hash_api_key(key)}"))
    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/system/kill-switch", json={"active": True, "reason": "drill"}, headers={"X-API-Key": key})).status_code == 200
        assert (await c.post("/api/system/kill-switch", json={"active": False}, headers={"X-API-Key": key})).status_code == 200
    events = (await db_session.execute(select(SystemEvent).order_by(SystemEvent.created_at))).scalars().all()
    assert len(events) == 2
    on, off = (e.detail for e in events)
    assert on["was_active"] is False and on["now_active"] is True and on["principal"] == "ops" and on["reason"] == "drill"
    assert off["was_active"] is True and off["now_active"] is False and "client" in off
    assert key not in str([e.detail for e in events]) and key not in events[0].message          # never the credential
