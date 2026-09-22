"""Council quorum, concurrency, and audit-trail regression tests — covers
the production bug investigation: 401s from bad-key rotation (see
test_ollama_client.py), a partial-response council silently treated as a
normal full result, non-concurrent analyst execution, the client.last_stats
race under concurrency, and council_decision_id never being captured."""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from app.council.service import run_council_cycle
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.enums import Bias
from app.schemas.council import ANALYST_NAMES
from app.schemas.market_context import (
    MarketContext, MomentumFeatures, PriceActionFeatures, RegimeState,
    StructureFeatures, TrendFeatures, VolatilityFeatures, VolumeFeatures,
)
from app.services.ollama_client import OllamaCallStats, OllamaError


def _context() -> MarketContext:
    return MarketContext(
        symbol="SOL", timeframe="1m", candle_open_time=1_700_000_000_000, close_price=100.0,
        trend=TrendFeatures(ema_fast=100, ema_slow=99, sma_fast=100, sma_slow=100, ema_slope=0.1, trend_strength=0.01),
        momentum=MomentumFeatures(rsi_14=55, macd=0.1, macd_signal=0.05, macd_hist=0.05, roc_10=1.0),
        volatility=VolatilityFeatures(atr_14=0.5, realized_vol=0.02, volatility_percentile=0.5, bb_upper=102, bb_middle=100, bb_lower=98, bb_width=0.02),
        structure=StructureFeatures(),
        volume=VolumeFeatures(volume_sma_20=1000, volume_ratio=1.0, volume_spike=False, vwap=100.0),
        price_action=PriceActionFeatures(body=0.1, wick_ratio=0.1, candle_range=1.0, gap=0.0, is_momentum_candle=False),
        regime=RegimeState(regime="RANGE", confidence=0.6),
    )


class ScriptedClient:
    """A single shared fake OllamaClient — every analyst call goes through
    this ONE instance (proving no analyst constructs its own client/auth
    logic), with per-analyst scripted outcomes and an optional artificial
    delay to prove concurrency."""

    last_stats = None

    def __init__(
        self, *, failing: set[str] = frozenset(), delay_seconds: float = 0.0, judge_fails: bool = False,
        votes: dict[str, Bias] | None = None,
    ):
        self._failing = failing
        self._delay = delay_seconds
        self._judge_fails = judge_fails
        self._votes = votes or {}
        self.call_count = 0
        self.analysts_called: list[str] = []

    async def generate_structured(self, *, system_prompt, user_prompt, response_model, temperature=0.2, max_retries_override=None):
        self.call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if response_model.__name__ != "AnalystResponse":
            if self._judge_fails:
                raise OllamaError("401 Unauthorized (judge)")
            from app.schemas.council import JudgeResponse
            return JudgeResponse(decision=Bias.NEUTRAL, confidence=0.5, reasoning="judged"), OllamaCallStats(
                request_id="judge-req", latency_ms=int(self._delay * 1000), prompt_tokens=1, completion_tokens=1, model="gpt-oss:20b", retries=0
            )
        analyst_name = next((n for n in ANALYST_NAMES if f"{n} analyst" in system_prompt), None)
        self.analysts_called.append(analyst_name)
        if analyst_name in self._failing:
            raise OllamaError("401 Unauthorized (simulated bad key)")
        from app.schemas.council import AnalystResponse
        stats = OllamaCallStats(
            request_id=f"req-{analyst_name}", latency_ms=int(self._delay * 1000), prompt_tokens=5, completion_tokens=5,
            model="gpt-oss:20b", retries=0,
        )
        self.last_stats = stats
        bias = self._votes.get(analyst_name, Bias.NEUTRAL)
        return AnalystResponse(analyst=analyst_name, bias=bias, confidence=0.7, reasoning="ok"), stats


@pytest.mark.asyncio
async def test_full_quorum_is_complete_and_allows_trading(db_session):
    client = ScriptedClient(failing=set())
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.council_status == "COMPLETE"
    assert consensus.quorum_met is True
    assert consensus.trade_allowed is True
    assert consensus.expected_analysts == 8
    assert consensus.successful_analysts == 8
    assert consensus.failed_analysts == []


@pytest.mark.asyncio
async def test_below_quorum_is_incomplete_forces_neutral_and_blocks_trading(db_session):
    """Reproduces the reported scenario: 3 of 8 analysts fail (401s), 5
    respond — below the default quorum of 6 — must be INCOMPLETE, not a
    normal full-strength result."""
    client = ScriptedClient(failing={"risk", "order_flow", "trend"})
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.council_status == "INCOMPLETE"
    assert consensus.quorum_met is False
    assert consensus.trade_allowed is False
    assert consensus.final_bias == Bias.NEUTRAL
    assert consensus.expected_analysts == 8
    assert consensus.successful_analysts == 5
    assert set(consensus.failed_analysts) == {"risk", "order_flow", "trend"}
    assert all("401" in reason for reason in consensus.failure_reasons.values())


@pytest.mark.asyncio
async def test_exactly_at_quorum_threshold_is_complete(db_session):
    """6 successful (the configured minimum) must count as COMPLETE, not
    INCOMPLETE — the boundary must be inclusive (>=), not exclusive."""
    client = ScriptedClient(failing={"risk", "order_flow"})  # 6 of 8 succeed
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.successful_analysts == 6
    assert consensus.council_status == "COMPLETE"
    assert consensus.quorum_met is True


@pytest.mark.asyncio
async def test_every_analyst_uses_the_single_shared_client(db_session):
    """No analyst-specific auth/client logic exists — all 8 calls must go
    through the one ScriptedClient instance passed into run_council_cycle."""
    client = ScriptedClient()
    await run_council_cycle(db_session, client, _context())

    assert client.call_count == 8  # 8 analysts, no judge needed (strong NEUTRAL consensus)
    assert set(client.analysts_called) == set(ANALYST_NAMES)


@pytest.mark.asyncio
async def test_analysts_run_concurrently_not_sequentially(db_session):
    """8 analysts each taking ~0.2s must complete in close to 0.2s total
    (asyncio.gather), not ~1.6s (sequential 8x0.2s)."""
    client = ScriptedClient(delay_seconds=0.2)
    start = time.monotonic()
    await run_council_cycle(db_session, client, _context())
    elapsed = time.monotonic() - start

    assert elapsed < 0.6, f"took {elapsed:.2f}s — analysts do not appear to be running concurrently"


@pytest.mark.asyncio
async def test_council_decision_id_is_populated_and_matches_the_persisted_row(db_session):
    """Regression guard: run_council_cycle previously returned a
    ConsensusResult with no id at all, so the caller (scripts/run_cycle.py)
    could never actually link Decision rows back to the CouncilDecision
    that informed them — council_decision_id was always None downstream."""
    client = ScriptedClient()
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.council_decision_id is not None
    row = await db_session.get(CouncilDecision, consensus.council_decision_id)
    assert row is not None
    assert row.final_bias == consensus.final_bias.value


@pytest.mark.asyncio
async def test_council_analysis_rows_persisted_for_both_successful_and_failed_analysts(db_session):
    """Failed analysts must be part of the permanent audit trail (was_valid
    distinguishes them), and each row's request_id/latency_ms/model must
    come from that analyst's OWN call — not a shared, racy
    OllamaClient.last_stats that a later-finishing concurrent call could
    have overwritten by the time this is read."""
    client = ScriptedClient(failing={"risk"}, delay_seconds=0.01)
    consensus = await run_council_cycle(db_session, client, _context())

    rows = (
        await db_session.execute(select(CouncilAnalysis).where(CouncilAnalysis.council_decision_id == consensus.council_decision_id))
    ).scalars().all()
    assert len(rows) == 8

    by_analyst = {r.analyst: r for r in rows}
    assert by_analyst["risk"].was_valid is False
    assert "401" in by_analyst["risk"].reasoning
    assert by_analyst["risk"].request_id == ""  # no successful call, no request_id

    for name in ANALYST_NAMES:
        if name == "risk":
            continue
        assert by_analyst[name].was_valid is True
        assert by_analyst[name].request_id == f"req-{name}"  # each row has ITS OWN analyst's request_id
        assert by_analyst[name].started_at is not None
        assert by_analyst[name].completed_at is not None


@pytest.mark.asyncio
async def test_timing_audit_fields_are_populated(db_session):
    client = ScriptedClient(delay_seconds=0.05)
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.council_start is not None
    assert consensus.consensus_time is not None and consensus.consensus_time > 0
    assert consensus.total_council_latency is not None and consensus.total_council_latency >= 0.05

    row = await db_session.get(CouncilDecision, consensus.council_decision_id)
    assert row.council_start == pytest.approx(consensus.council_start)
    assert row.total_council_latency_seconds is not None


@pytest.mark.asyncio
async def test_judge_failure_during_weak_consensus_does_not_crash_and_reports_no_judge_invoked(db_session):
    """Reproduces the reported final_bias=NEUTRAL/confidence=0.625/
    judge_invoked=false pattern: enough analysts succeed for quorum, but
    votes are mixed (weak consensus) AND the judge call also fails — the
    cycle must still complete cleanly, falling back to the pre-judge
    consensus rather than raising."""
    mixed_votes = {
        "trend": Bias.LONG, "momentum": Bias.LONG, "structure": Bias.LONG,
        "volatility": Bias.SHORT, "regime": Bias.SHORT, "contrarian": Bias.SHORT,
    }
    client = ScriptedClient(failing={"risk", "order_flow"}, judge_fails=True, votes=mixed_votes)  # 6/8 succeed, meets quorum, 3-3 tie -> weak
    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.quorum_met is True
    assert consensus.is_strong_consensus is False  # confirms the judge SHOULD have been consulted
    assert consensus.judge_invoked is False  # judge attempted and failed, never applied
