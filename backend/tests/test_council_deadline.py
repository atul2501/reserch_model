"""Council latency & failure handling (spec phases 13, 16): concurrent
analysts, per-analyst timeout, whole-council deadline with cancellation,
quorum boundary, fast-fail on dead credentials, candle association."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.council import service as council_service
from app.council.service import run_council_cycle
from app.models.council import CouncilAnalysis, CouncilDecision
from app.schemas.council import ANALYST_NAMES
from app.services.ollama_client import OllamaClient, OllamaKeyHealth
from tests.helpers_agents import make_context


def _analyst_json(name, bias="LONG", conf=0.8):
    return {"message": {"content": json.dumps({"analyst": name, "bias": bias, "confidence": conf, "reasoning": "r",
                                               "key_factors": ["f"], "invalidators": ["i"]})}}


def make_client(handler, keys=("k",)):
    c = OllamaClient()
    c._api_keys = list(keys)
    c._key_health = [OllamaKeyHealth() for _ in keys]
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fake")
    c._max_retries = 1
    c._backoff_min, c._backoff_max = 0.0, 0.01
    c._semaphore = asyncio.Semaphore(16)
    return c


def analyst_from(req):
    body = json.loads(req.content)
    system = body["messages"][0]["content"]
    for n in ANALYST_NAMES:
        if f"You are the {n} analyst" in system:
            return n
    return "trend"


async def test_analysts_run_concurrently_not_sequentially(db_session):
    async def h(req):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=_analyst_json(analyst_from(req)))

    t0 = time.monotonic()
    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0))
    elapsed = time.monotonic() - t0
    assert consensus.council_status == "COMPLETE" and consensus.successful_analysts == 8
    assert elapsed < 0.2 * 4          # 8 x 0.2s sequential would be 1.6s


async def test_slow_analysts_are_cancelled_at_the_council_deadline_and_quorum_decides(db_session):
    slow = set(ANALYST_NAMES[:3])     # 3 of 8 never finish in time -> 5 succeed < quorum 6

    async def h(req):
        name = analyst_from(req)
        if name in slow:
            await asyncio.sleep(30)
        return httpx.Response(200, json=_analyst_json(name))

    t0 = time.monotonic()
    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0), deadline_seconds=0.5, analyst_timeout_seconds=10)
    assert time.monotonic() - t0 < 3                     # bounded by the deadline, not by the slow calls
    assert consensus.council_status == "INCOMPLETE" and consensus.trade_allowed is False and consensus.quorum_met is False
    assert consensus.successful_analysts == 5 and set(consensus.failed_analysts) == slow
    assert all(consensus.failure_reasons[a] == "council_deadline_exceeded" for a in slow)
    rows = (await db_session.execute(select(CouncilAnalysis))).scalars().all()
    assert len(rows) == 8 and sum(not r.was_valid for r in rows) == 3       # failures are audited too


async def test_per_analyst_timeout_marks_only_that_analyst_failed(db_session):
    async def h(req):
        name = analyst_from(req)
        if name == "trend":
            await asyncio.sleep(30)
        return httpx.Response(200, json=_analyst_json(name))

    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0), deadline_seconds=10, analyst_timeout_seconds=0.2)
    assert consensus.successful_analysts == 7 and consensus.failed_analysts == ["trend"]
    assert consensus.failure_reasons["trend"] in {"analyst_timeout", "call exceeded its 0.2s deadline"} or "deadline" in consensus.failure_reasons["trend"] or "timeout" in consensus.failure_reasons["trend"]
    assert consensus.council_status == "COMPLETE"      # 7 >= quorum 6


@pytest.mark.parametrize("failures,expected_status", [(0, "COMPLETE"), (2, "COMPLETE"), (3, "INCOMPLETE"), (8, "INCOMPLETE")])
async def test_quorum_boundary_is_six_of_eight(db_session, failures, expected_status):
    assert get_settings().council_min_successful_analysts == 6
    failing = set(ANALYST_NAMES[:failures])

    def h(req):
        name = analyst_from(req)
        return httpx.Response(500) if name in failing else httpx.Response(200, json=_analyst_json(name))

    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0))
    assert consensus.council_status == expected_status
    assert consensus.trade_allowed is (expected_status == "COMPLETE")
    if expected_status == "INCOMPLETE":
        assert consensus.final_bias.value == "NEUTRAL"        # never a normal consensus


async def test_dead_credentials_fail_the_council_immediately_without_any_request(db_session):
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(401)

    client = make_client(h)
    client._key_health[0].disabled = True          # already known-invalid
    t0 = time.monotonic()
    consensus = await run_council_cycle(db_session, client, make_context(1, 100.0))
    assert calls == [] and time.monotonic() - t0 < 0.5
    assert consensus.council_status == "INCOMPLETE" and consensus.trade_allowed is False
    assert set(consensus.failure_reasons.values()) == {"ollama_unavailable"}


async def test_all_429_makes_council_incomplete_and_fast(db_session):
    def h(req):
        return httpx.Response(429, headers={"retry-after": "60"})

    t0 = time.monotonic()
    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0))
    assert consensus.council_status == "INCOMPLETE" and time.monotonic() - t0 < 3


async def test_malformed_json_from_some_analysts_counts_as_failure(db_session):
    def h(req):
        name = analyst_from(req)
        if name in ("risk", "contrarian", "regime"):
            return httpx.Response(200, json={"message": {"content": "sorry, I cannot"}})
        return httpx.Response(200, json=_analyst_json(name))

    consensus = await run_council_cycle(db_session, make_client(h), make_context(1, 100.0))
    assert consensus.successful_analysts == 5 and consensus.council_status == "INCOMPLETE"


async def test_decision_is_bound_to_the_candle_it_was_computed_for(db_session):
    def h(req):
        return httpx.Response(200, json=_analyst_json(analyst_from(req)))

    ctx = make_context(7, 100.0)
    consensus = await run_council_cycle(db_session, make_client(h), ctx)
    row = (await db_session.execute(select(CouncilDecision).where(CouncilDecision.id == consensus.council_decision_id))).scalar_one()
    assert row.market_candle_open_time == ctx.candle_open_time
    assert row.total_council_latency_seconds is not None and row.expected_analysts == 8
