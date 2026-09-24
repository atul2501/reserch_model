"""Structured schemas for AI council analyst/judge outputs (spec 8-9).

No unstructured Ollama text is allowed to reach the trading engine — every
response is parsed into one of these models and rejected if it fails
validation (the caller then retries or treats the analyst as abstained).
"""
from __future__ import annotations

import uuid
from typing import ClassVar

from pydantic import BaseModel, Field

from app.models.enums import Bias
from app.schemas.normalization import BoundedResponse

ANALYST_NAMES = (
    "trend",
    "momentum",
    "structure",
    "order_flow",
    "volatility",
    "regime",
    "risk",
    "contrarian",
)


class AnalystResponse(BoundedResponse):
    """`key_factors` and `invalidators` are ORDERED MOST-IMPORTANT-FIRST (the prompt says so); that documented
    ordering is what allows the boundary normaliser to keep the first 10 of an over-long list (see
    app.schemas.normalization). The max_length=10 constraints themselves stay strict."""

    ordered_lists: ClassVar[frozenset[str]] = frozenset({"key_factors", "invalidators"})

    analyst: str = Field(pattern="^(" + "|".join(ANALYST_NAMES) + ")$")
    bias: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2048)
    key_factors: list[str] = Field(default_factory=list, max_length=10)
    invalidators: list[str] = Field(default_factory=list, max_length=10)

    model_config = {"extra": "forbid"}


class JudgeResponse(BoundedResponse):
    ordered_lists: ClassVar[frozenset[str]] = frozenset({"key_risks", "invalidators"})

    decision: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2048)
    key_risks: list[str] = Field(default_factory=list, max_length=10)
    invalidators: list[str] = Field(default_factory=list, max_length=10)

    model_config = {"extra": "forbid"}


class ConsensusResult(BaseModel):
    """Deterministic tally computed in Python from AnalystResponses — never
    itself produced by an LLM (spec section 9)."""

    vote_tally: dict[str, int]
    consensus_bias: Bias
    consensus_confidence: float
    is_strong_consensus: bool
    judge_invoked: bool = False
    judge_response: JudgeResponse | None = None
    final_bias: Bias
    final_confidence: float

    # --- Quorum -------------------------------------------------------
    # A partial response (e.g. 5/8 analysts after some fail) must never be
    # treated as an ordinary full-strength consensus — these fields make
    # that distinction explicit and machine-checkable downstream (Risk
    # Engine gates on trade_allowed, never on final_bias/confidence alone).
    council_status: str = "COMPLETE"  # "COMPLETE" | "INCOMPLETE"
    expected_analysts: int = 0
    successful_analysts: int = 0
    failed_analysts: list[str] = Field(default_factory=list)
    failure_reasons: dict[str, str] = Field(default_factory=dict)
    quorum_met: bool = True
    trade_allowed: bool = True

    # --- Audit timing (council_start/analyst-level timing live on the
    # persisted CouncilAnalysis rows; these are the cycle-level summary) --
    council_decision_id: uuid.UUID | None = None  # set once the CouncilDecision row is flushed
    candle_open_time: int | None = None  # the candle this consensus was produced for (never reused for another)
    council_completed_at: float | None = None  # unix epoch seconds
    council_start: float | None = None  # unix epoch seconds
    consensus_time: float | None = None  # seconds from council_start to consensus computed
    total_council_latency: float | None = None  # seconds from council_start to full persistence

    model_config = {"extra": "forbid"}
