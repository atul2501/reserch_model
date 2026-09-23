"""Regression tests for EXISTING infrastructure-fault fallback behavior —
Ollama timeout/rate-limit/outage — using fault-injecting fakes in place of
OllamaClient. These validate resilience code that already exists
(retry/backoff lives in OllamaClient itself, already covered by
test_ollama_client.py; this file covers the downstream fallback wiring:
propose_candidate returning None, and the council falling back to HOLD)
rather than adding new production robustness code, per the adversarial
testing engine's scoping decision — infra faults are a test surface, not a
new contributor to the numeric adversarial robustness_score.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.council.service import run_council_cycle
from app.evolution.ollama_researcher import propose_candidate
from app.models.council import CouncilDecision
from app.models.enums import Bias
from app.schemas.market_context import (
    MarketContext,
    MomentumFeatures,
    PriceActionFeatures,
    RegimeState,
    StructureFeatures,
    TrendFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)
from app.services.ollama_client import OllamaRateLimitError, OllamaTimeoutError


class _AlwaysFailsClient:
    """Duck-typed stand-in for OllamaClient — raises immediately rather
    than going through real retry/backoff delays, since OllamaClient's own
    retry behavior is already covered by test_ollama_client.py. This file
    is about what happens *after* Ollama is confirmed unreachable."""

    last_stats = None

    def __init__(self, exc: Exception):
        self._exc = exc

    def is_available(self) -> bool:
        return True

    async def generate_structured(self, **kwargs):
        raise self._exc


def _context() -> MarketContext:
    return MarketContext(
        symbol="SOL", timeframe="1m", candle_open_time=1, close_price=100.0,
        trend=TrendFeatures(ema_fast=100, ema_slow=99, sma_fast=100, sma_slow=100, ema_slope=0.1, trend_strength=0.01),
        momentum=MomentumFeatures(rsi_14=55, macd=0.1, macd_signal=0.05, macd_hist=0.05, roc_10=1.0),
        volatility=VolatilityFeatures(atr_14=0.5, realized_vol=0.02, volatility_percentile=0.5, bb_upper=102, bb_middle=100, bb_lower=98, bb_width=0.02),
        structure=StructureFeatures(),
        volume=VolumeFeatures(volume_sma_20=1000, volume_ratio=1.0, volume_spike=False, vwap=100.0),
        price_action=PriceActionFeatures(body=0.1, wick_ratio=0.1, candle_range=1.0, gap=0.0, is_momentum_candle=False),
        regime=RegimeState(regime="RANGE", confidence=0.6),
    )


@pytest.mark.asyncio
async def test_propose_candidate_returns_none_on_ollama_timeout():
    client = _AlwaysFailsClient(OllamaTimeoutError("simulated timeout"))
    result = await propose_candidate(client, research_summary={"gap": "no volatility strategies"})
    assert result is None  # never raises, never returns an unvalidated payload


@pytest.mark.asyncio
async def test_propose_candidate_returns_none_on_ollama_rate_limit():
    client = _AlwaysFailsClient(OllamaRateLimitError("simulated 429"))
    result = await propose_candidate(client, research_summary={})
    assert result is None


@pytest.mark.asyncio
async def test_council_cycle_falls_back_to_hold_when_ollama_is_completely_down(db_session):
    """Every analyst call fails (simulated total Ollama outage). The
    council must still complete — never raise — and fall back to NEUTRAL
    (HOLD), while still persisting a CouncilDecision audit row so the
    outage itself is visible in the trail."""
    client = _AlwaysFailsClient(OllamaTimeoutError("ollama unreachable"))

    consensus = await run_council_cycle(db_session, client, _context())

    assert consensus.final_bias == Bias.NEUTRAL
    assert consensus.final_confidence == 0.0
    assert consensus.judge_invoked is False

    decisions = (await db_session.execute(select(CouncilDecision))).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].final_bias == Bias.NEUTRAL.value
