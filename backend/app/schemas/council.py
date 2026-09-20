"""Structured schemas for AI council analyst/judge outputs (spec 8-9).

No unstructured Ollama text is allowed to reach the trading engine — every
response is parsed into one of these models and rejected if it fails
validation (the caller then retries or treats the analyst as abstained).
"""
from __future__ import annotations

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

    model_config = {"extra": "forbid"}
