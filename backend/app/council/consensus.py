"""Deterministic consensus engine (spec section 9). Never produced by an
LLM — this is plain Python vote counting over validated AnalystResponses.
"""
from __future__ import annotations

from app.models.enums import Bias
from app.schemas.council import AnalystResponse, ConsensusResult, JudgeResponse


def tally_votes(responses: list[AnalystResponse]) -> dict[str, int]:
    tally = {Bias.LONG.value: 0, Bias.SHORT.value: 0, Bias.NEUTRAL.value: 0}
    for r in responses:
        tally[r.bias.value] += 1
    return tally


def compute_consensus(
    responses: list[AnalystResponse],
    *,
    consensus_margin: int = 2,
) -> ConsensusResult:
    """A "strong" consensus is a lead of at least `consensus_margin` votes
    over the second-place bias (spec section 9's LONG=6/SHORT=1/NEUTRAL=1
    example is a lead of 5). Below that margin, the judge must be invoked
    by the caller — this function only reports whether it's strong."""
    if not responses:
        raise ValueError("cannot compute consensus with zero analyst responses")

    tally = tally_votes(responses)
    ranked = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
    top_bias, top_votes = ranked[0]
    second_votes = ranked[1][1] if len(ranked) > 1 else 0
    is_strong = (top_votes - second_votes) >= consensus_margin

    matching = [r for r in responses if r.bias.value == top_bias]
    avg_confidence = sum(r.confidence for r in matching) / len(matching) if matching else 0.0

    return ConsensusResult(
        vote_tally=tally,
        consensus_bias=Bias(top_bias),
        consensus_confidence=avg_confidence,
        is_strong_consensus=is_strong,
        judge_invoked=False,
        judge_response=None,
        final_bias=Bias(top_bias),
        final_confidence=avg_confidence,
    )


def apply_judge(consensus: ConsensusResult, judge: JudgeResponse) -> ConsensusResult:
    """Overlays a judge's ruling onto a weak-consensus result. The risk
    engine downstream still has final veto regardless of this outcome
    (spec section 9)."""
    return consensus.model_copy(
        update={
            "judge_invoked": True,
            "judge_response": judge,
            "final_bias": judge.decision,
            "final_confidence": judge.confidence,
        }
    )
