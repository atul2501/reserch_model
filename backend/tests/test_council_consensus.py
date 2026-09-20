"""Deterministic consensus tallying and judge overlay (spec section 9/45)."""
from __future__ import annotations

from app.council.consensus import apply_judge, compute_consensus
from app.models.enums import Bias
from app.schemas.council import AnalystResponse, JudgeResponse


def _resp(analyst: str, bias: Bias, confidence: float = 0.7) -> AnalystResponse:
    return AnalystResponse(analyst=analyst, bias=bias, confidence=confidence, reasoning="test")


def test_strong_consensus_does_not_need_judge():
    responses = [
        _resp("trend", Bias.LONG),
        _resp("momentum", Bias.LONG),
        _resp("structure", Bias.LONG),
        _resp("order_flow", Bias.LONG),
        _resp("volatility", Bias.LONG),
        _resp("regime", Bias.LONG),
        _resp("risk", Bias.SHORT),
        _resp("contrarian", Bias.NEUTRAL),
    ]
    consensus = compute_consensus(responses, consensus_margin=2)
    assert consensus.is_strong_consensus is True
    assert consensus.final_bias == Bias.LONG
    assert consensus.vote_tally == {"LONG": 6, "SHORT": 1, "NEUTRAL": 1}


def test_weak_consensus_flagged_for_judge():
    responses = [
        _resp("trend", Bias.LONG),
        _resp("momentum", Bias.LONG),
        _resp("structure", Bias.LONG),
        _resp("order_flow", Bias.SHORT),
        _resp("volatility", Bias.SHORT),
        _resp("regime", Bias.SHORT),
        _resp("risk", Bias.SHORT),
        _resp("contrarian", Bias.NEUTRAL),
    ]
    consensus = compute_consensus(responses, consensus_margin=2)
    assert consensus.is_strong_consensus is False
    assert consensus.judge_invoked is False  # caller decides whether to invoke


def test_judge_overlay_sets_final_decision():
    responses = [_resp("trend", Bias.LONG), _resp("momentum", Bias.SHORT)]
    consensus = compute_consensus(responses, consensus_margin=2)
    judge = JudgeResponse(decision=Bias.NEUTRAL, confidence=0.9, reasoning="too much conflict")

    final = apply_judge(consensus, judge)
    assert final.judge_invoked is True
    assert final.final_bias == Bias.NEUTRAL
    assert final.final_confidence == 0.9
    # Original vote tally is preserved for audit even after judge overrides.
    assert final.vote_tally == consensus.vote_tally


def test_malformed_analyst_response_rejected_by_schema():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AnalystResponse.model_validate({"analyst": "trend", "bias": "UP_A_LOT", "confidence": 2.0, "reasoning": ""})
