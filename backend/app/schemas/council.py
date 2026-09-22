"""Structured schemas for AI council analyst/judge outputs (spec 8-9).

No unstructured Ollama text is allowed to reach the trading engine — every
response is parsed into one of these models and rejected if it fails
validation (the caller then retries or treats the analyst as abstained).
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models.enums import Bias

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


class AnalystResponse(BaseModel):
    analyst: str = Field(pattern="^(" + "|".join(ANALYST_NAMES) + ")$")
    bias: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2048)
    key_factors: list[str] = Field(default_factory=list, max_length=10)
    invalidators: list[str] = Field(default_factory=list, max_length=10)

    model_config = {"extra": "forbid"}


class JudgeResponse(BaseModel):
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
    council_start: float | None = None  # unix epoch seconds
    consensus_time: float | None = None  # seconds from council_start to consensus computed
    total_council_latency: float | None = None  # seconds from council_start to full persistence

    model_config = {"extra": "forbid"}
