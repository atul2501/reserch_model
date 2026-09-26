"""Phase 1 dependency-boundary regression: council/service.py and
council/analysts.py must depend on AIClientPort (a Protocol), not on the
concrete OllamaClient class - and must work correctly with ANY object that
satisfies the protocol's shape, proving the dependency is real and not just
a renamed type hint. See REFACTOR_PLAN.md item 3 / REFACTOR_PROGRESS.md.
"""
from __future__ import annotations

import importlib
import inspect

import pytest

from app.council.ports import AIClientPort
from app.council.service import run_council_cycle
from app.schemas.council import ANALYST_NAMES, AnalystResponse, JudgeResponse
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
from app.services.ollama_client import OllamaCallStats, OllamaClient


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


@pytest.mark.parametrize("module", ["app.council.service", "app.council.analysts"])
def test_council_no_longer_imports_the_concrete_ollama_client(module):
    """The boundary is real: neither council module imports app.services.ollama_client
    at all (a docstring may still mention OllamaClient by name for explanation - only
    the import is disallowed)."""
    src = inspect.getsource(importlib.import_module(module))
    assert "app.services.ollama_client" not in src
    assert "import OllamaClient" not in src


def test_ollama_client_satisfies_the_protocol_structurally():
    """OllamaClient itself is UNCHANGED and still works as the council's AI client -
    it satisfies AIClientPort by shape, with no inheritance/registration needed."""
    instance = OllamaClient.__new__(OllamaClient)  # no I/O; only checking the shape
    assert isinstance(instance, AIClientPort)


class BareMinimumClient:
    """Deliberately NOT an OllamaClient, not a subclass, not registered with it -
    only implements the two methods AIClientPort declares. If run_council_cycle
    secretly required the concrete class (isinstance checks, attribute access
    beyond the protocol, etc.), this would fail."""

    def is_available(self) -> bool:
        return True

    async def generate_structured(self, *, system_prompt, user_prompt, response_model,
                                   temperature=0.2, max_retries_override=None, deadline_seconds=None):
        stats = OllamaCallStats(request_id="req-1", latency_ms=1, prompt_tokens=1,
                                 completion_tokens=1, model="test-model", retries=0)
        if response_model is JudgeResponse:
            return JudgeResponse(decision="NEUTRAL", confidence=0.5, reasoning="ok"), stats
        analyst = next(n for n in ANALYST_NAMES if f"{n} analyst" in system_prompt)
        return AnalystResponse(analyst=analyst, bias="NEUTRAL", confidence=0.6, reasoning="ok"), stats


def test_bare_minimum_protocol_conformant_object_is_not_an_ollama_client():
    assert not isinstance(BareMinimumClient(), OllamaClient)
    assert isinstance(BareMinimumClient(), AIClientPort)


@pytest.mark.asyncio
async def test_run_council_cycle_works_through_a_non_ollama_client_implementation(db_session):
    """End-to-end proof: the full council cycle (quorum, consensus, persistence)
    runs correctly against an object that is provably not an OllamaClient -
    the existing behavior (see test_council_service.py) is preserved through
    the new boundary, not just type-checked."""
    consensus = await run_council_cycle(db_session, BareMinimumClient(), _context())

    assert consensus.council_status == "COMPLETE"
    assert consensus.quorum_met is True
    assert consensus.trade_allowed is True
    assert consensus.successful_analysts == len(ANALYST_NAMES)
