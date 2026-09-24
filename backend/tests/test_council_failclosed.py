"""Council fail-closed contract (spec phases 10-12).

If the council is REQUIRED for a cycle then insufficient quorum, a judge failure, a malformed response,
a timeout, an unexpected exception or a candle mismatch must ALL end in "no new entries" - and an
arbitrary plurality LONG/SHORT must never escape a failed council. Exercised through the real
`process_candle` path (not just the helper functions)."""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.agents.lifecycle import create_generation
from app.council.context import INCOMPLETE, NOT_RUN, CouncilContext, combine
from app.council.service import run_council_cycle
from app.core.config import COUNCIL_ANALYST_COUNT, get_settings
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.market_data_service import MarketDataService
from app.models.council import CouncilDecision
from app.models.enums import Bias, StrategyFamily
from app.models.strategy import Strategy, StrategyVersion
from app.models.system import WorkerCycle
from app.models.trading import Order, Position
from app.schemas.council import ANALYST_NAMES
from app.schemas.strategy_dna import Condition, RiskProfile, RuleSet, StrategyDNA
from app.services.ollama_client import OllamaClient, OllamaKeyHealth
from app.worker import cycle as cycle_mod
from tests.helpers_market import INTERVAL, T0, FakeHyperliquid, clock_after_bar
from tests.test_council_service import ScriptedClient, _context

MIXED = {"trend": Bias.LONG, "momentum": Bias.LONG, "structure": Bias.LONG,
         "volatility": Bias.SHORT, "regime": Bias.SHORT, "contrarian": Bias.SHORT}


def test_analyst_count_constant_matches_the_schema():
    assert COUNCIL_ANALYST_COUNT == len(ANALYST_NAMES)


# --- unit level -------------------------------------------------------------------------------------------


async def test_judge_failure_on_a_weak_consensus_fails_closed_and_emits_no_direction(db_session):
    client = ScriptedClient(failing={"risk", "order_flow"}, judge_fails=True, votes=MIXED)  # 6/8, 3-3 tie
    c = await run_council_cycle(db_session, client, _context())
    assert c.quorum_met and not c.is_strong_consensus and not c.judge_invoked
    assert c.trade_allowed is False and c.council_status == "INCOMPLETE"
    assert c.final_bias == Bias.NEUTRAL and c.final_confidence == 0.0     # never the arbitrary plurality
    assert c.failure_reasons["judge"] == "judge_failed_or_timed_out"
    row = await db_session.get(CouncilDecision, c.council_decision_id)
    assert row.trade_allowed is False and row.council_status == "INCOMPLETE" and row.final_bias == "NEUTRAL"


async def test_judge_skipped_for_lack_of_time_fails_closed(db_session):
    client = ScriptedClient(failing={"risk", "order_flow"}, votes=MIXED)
    c = await run_council_cycle(db_session, client, _context(), deadline_seconds=1.5)   # <= 2s left => judge skipped
    assert c.trade_allowed is False and c.failure_reasons["judge"] == "judge_skipped_no_time_left"
    assert c.final_bias == Bias.NEUTRAL


async def test_judge_disabled_by_operator_abstains_but_is_not_a_failure(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "judge_enabled", False)
    client = ScriptedClient(failing={"risk", "order_flow"}, votes=MIXED)
    c = await run_council_cycle(db_session, client, _context())
    assert c.council_status == "COMPLETE" and c.trade_allowed is True and "judge" not in c.failure_reasons
    assert c.final_bias == Bias.NEUTRAL and c.judge_invoked is False     # no arbitrary LONG on a 3-3 tie


async def test_judge_that_raises_a_non_ollama_exception_still_fails_closed(db_session):
    class Boom(ScriptedClient):
        async def generate_structured(self, **kw):
            if kw["response_model"].__name__ != "AnalystResponse":
                raise ValueError("Expecting value: line 1 column 1 (char 0)")   # what a non-JSON 200 used to raise
            return await super().generate_structured(**kw)

    c = await run_council_cycle(db_session, Boom(failing={"risk", "order_flow"}, votes=MIXED), _context())
    assert c.trade_allowed is False and c.final_bias == Bias.NEUTRAL


async def test_strong_consensus_needs_no_judge_and_allows_trading(db_session):
    votes = {n: Bias.LONG for n in ANALYST_NAMES}
    c = await run_council_cycle(db_session, ScriptedClient(votes=votes), _context())
    assert c.trade_allowed and c.final_bias == Bias.LONG and not c.judge_invoked


async def test_audit_fields_completion_time_failed_count_and_candle_binding(db_session):
    client = ScriptedClient(failing={"risk"}, delay_seconds=0.01)
    c = await run_council_cycle(db_session, client, _context())
    assert c.candle_open_time == _context().candle_open_time
    row = await db_session.get(CouncilDecision, c.council_decision_id)
    assert row.failed_count == 1 and row.successful_analysts == 7
    assert row.council_completed_at >= row.council_start
    assert 0 < row.consensus_time_seconds <= row.total_council_latency_seconds


def test_not_run_means_approved_only_when_the_council_was_not_required():
    assert combine(Bias.LONG, CouncilContext(status=NOT_RUN, required=False)).final_signal == Bias.LONG
    out = combine(Bias.LONG, CouncilContext(status=NOT_RUN, required=True))
    assert out.final_signal == Bias.NEUTRAL and out.size_modifier == 0.0 and out.reason == "council_required_but_not_run"


def test_config_rejects_a_council_that_cannot_reach_quorum_or_outlives_its_candle():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(council_min_successful_analysts=0)
    with pytest.raises(ValueError):
        Settings(council_min_successful_analysts=COUNCIL_ANALYST_COUNT + 1)
    with pytest.raises(ValueError, match="candle interval"):
        Settings(council_deadline_seconds=58.0, council_outer_grace_seconds=5.0)   # 63s >= 60s candle
    assert Settings(council_enabled=False, council_deadline_seconds=300.0)          # not enforced when disabled


# --- end to end through the real cycle path ---------------------------------------------------------------


async def _seed_always_long_population(db, n=3):
    ids = []
    for _ in range(n):
        strat = Strategy(code=f"S-{uuid.uuid4().hex[:8]}", family=StrategyFamily.MOMENTUM, name="t")
        db.add(strat)
        await db.flush()
        dna = StrategyDNA(
            strategy_family=StrategyFamily.MOMENTUM,
            indicators=[{"name": "rsi", "params": {"period": 14}}],
            entry_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="gt", value=0)]),   # always enters
            exit_rules=RuleSet(conditions=[Condition(feature="rsi_14", operator="lt", value=-1)]),   # never signal-exits
            risk_profile=RiskProfile(max_leverage=1.0, max_position_fraction=0.5),
            direction_mode="long_only",     # otherwise the family decides direction (none in a downtrend)
        )
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=1, strategy_version_ids=ids, starting_balance=100.0)


@pytest.fixture
def council_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "council_enabled", True)
    monkeypatch.setattr(s, "council_interval_candles", 1)      # the council is due (=> REQUIRED) on every candle
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    return s


async def _run(db, client, *, last_bar=399):
    fake = FakeHyperliquid(n_candles=400)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(last_bar))
    await _seed_always_long_population(db)
    await market.sync_recent_candles(db, lookback_candles=400)
    outcomes = await cycle_mod.run_pending_cycles(db, market, client, execution_engine=PaperExecutionAdapter())
    orders = (await db.execute(select(Order))).scalars().all()
    cyc = (await db.execute(select(WorkerCycle))).scalars().all()
    return outcomes, orders, cyc


async def test_control_healthy_council_lets_agents_enter(db_session, council_on):
    outcomes, orders, cyc = await _run(db_session, ScriptedClient(votes={n: Bias.LONG for n in ANALYST_NAMES}))
    assert [o.status for o in outcomes] == ["COMPLETED"] and outcomes[0].council_status == "COMPLETE"
    assert len(orders) == 3 and cyc[0].council_required is True


async def test_quorum_failure_blocks_all_entries_but_the_cycle_completes(db_session, council_on):
    outcomes, orders, cyc = await _run(db_session, ScriptedClient(failing={"risk", "order_flow", "trend"}))
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE"
    assert orders == [] and cyc[0].council_required is True and cyc[0].council_status == "INCOMPLETE"


async def test_judge_failure_blocks_entries_through_the_real_cycle(db_session, council_on):
    client = ScriptedClient(failing={"risk", "order_flow"}, judge_fails=True, votes=MIXED)
    outcomes, orders, _ = await _run(db_session, client)
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE"
    assert orders == []
    assert (await db_session.execute(select(Position))).first() is None


async def test_non_json_200_from_ollama_does_not_crash_the_cycle_and_blocks_entries(db_session, council_on):
    real = OllamaClient()
    real._api_keys = ["k"]
    real._key_health = [OllamaKeyHealth()]
    real._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>gateway</html>")),
                                     base_url="http://fake")
    real._backoff_min, real._backoff_max = 0.0, 0.01
    outcomes, orders, _ = await _run(db_session, real)
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE"
    assert orders == []


async def test_malformed_model_json_from_ollama_blocks_entries(db_session, council_on):
    body = {"message": {"content": json.dumps({"bias": "MOON", "confidence": 9})}}
    real = OllamaClient()
    real._api_keys = ["k"]
    real._key_health = [OllamaKeyHealth()]
    real._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), base_url="http://fake")
    real._backoff_min, real._backoff_max = 0.0, 0.01
    outcomes, orders, _ = await _run(db_session, real)
    assert outcomes[0].status == "COMPLETED" and orders == []


async def test_all_keys_unauthorized_blocks_entries(db_session, council_on):
    real = OllamaClient()
    real._api_keys = ["k1", "k2"]
    real._key_health = [OllamaKeyHealth(), OllamaKeyHealth()]
    real._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)), base_url="http://fake")
    real._backoff_min, real._backoff_max = 0.0, 0.01
    outcomes, orders, _ = await _run(db_session, real)
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE" and orders == []


async def test_council_outer_deadline_timeout_blocks_entries(db_session, council_on, monkeypatch):
    monkeypatch.setattr(council_on, "council_deadline_seconds", 0.05)
    monkeypatch.setattr(council_on, "council_outer_grace_seconds", 0.05)

    async def hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(cycle_mod, "run_council_cycle", hang)
    outcomes, orders, _ = await _run(db_session, None)
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE" and orders == []


async def test_unexpected_council_exception_blocks_entries_instead_of_failing_the_cycle(db_session, council_on, monkeypatch):
    async def boom(*a, **k):
        raise ValueError("cannot compute consensus with zero analyst responses")

    monkeypatch.setattr(cycle_mod, "run_council_cycle", boom)
    outcomes, orders, cyc = await _run(db_session, None)
    assert outcomes[0].status == "COMPLETED"          # exits/stops for this candle still ran
    assert orders == [] and cyc[0].council_status == "INCOMPLETE"


async def test_a_verdict_for_another_candle_is_never_applied(db_session, council_on, monkeypatch):
    real = cycle_mod.run_council_cycle

    async def wrong_candle(db, client, context, **kw):
        c = await real(db, client, context, **kw)
        return c.model_copy(update={"candle_open_time": context.candle_open_time - INTERVAL})

    monkeypatch.setattr(cycle_mod, "run_council_cycle", wrong_candle)
    outcomes, orders, _ = await _run(db_session, ScriptedClient(votes={n: Bias.LONG for n in ANALYST_NAMES}))
    assert outcomes[0].council_status == "INCOMPLETE" and orders == []


async def test_council_not_due_is_not_required_and_does_not_block(db_session, council_on, monkeypatch):
    from app.worker.scheduler import council_due
    n = next(n for n in range(2, 12) if not council_due(T0 + 399 * INTERVAL, INTERVAL, n))   # a cadence that skips this bar
    monkeypatch.setattr(council_on, "council_interval_candles", n)
    outcomes, orders, cyc = await _run(db_session, ScriptedClient(failing=set(ANALYST_NAMES)))   # would fail if it ran
    assert outcomes[0].council_status == "NOT_RUN" and cyc[0].council_required is False
    assert len(orders) == 3                              # explicitly "not required" => agents trade on their own DNA


async def test_council_disabled_is_not_required(db_session, council_on, monkeypatch):
    monkeypatch.setattr(council_on, "council_enabled", False)
    outcomes, orders, cyc = await _run(db_session, None)
    assert cyc[0].council_required is False and len(orders) == 3
