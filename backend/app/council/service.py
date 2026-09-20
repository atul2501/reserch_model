"""AI Council orchestration (spec sections 4/8/9).

Runs all analysts concurrently against ONE shared MarketContext, computes a
deterministic consensus, invokes the Ollama judge only when the vote is
close, and persists the full audit trail. This runs once per council cycle
— not once per agent (spec section 4).
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.council.analysts import ANALYST_FOCUS, run_analyst
from app.council.consensus import apply_judge, compute_consensus
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.enums import Bias
from app.schemas.council import ANALYST_NAMES, AnalystResponse, ConsensusResult, JudgeResponse
from app.schemas.market_context import MarketContext
from app.services.ollama_client import OllamaClient, OllamaResponseError

logger = get_logger(__name__)

_JUDGE_SYSTEM_PROMPT = """You are the head risk judge on a crypto trading research council.
Several analysts disagree on direction for the same market snapshot. You will
receive their individual analyses. Weigh their reasoning and produce a final
call. Respond with ONLY a JSON object:
{
  "decision": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<concise reasoning>",
  "key_risks": ["..."],
  "invalidators": ["..."]
}
When in doubt, prefer NEUTRAL over a low-confidence directional call."""


def should_run_council(candle_index: int, interval_candles: int) -> bool:
    if interval_candles <= 1:
        return True
    return candle_index % interval_candles == 0


async def run_council_cycle(
    db: AsyncSession,
    client: OllamaClient,
    context: MarketContext,
) -> ConsensusResult:
    settings = get_settings()

    tasks = [run_analyst(client, name, context) for name in ANALYST_NAMES]
    raw_results = await asyncio.gather(*tasks, return_exceptions=False)
    valid_responses: list[AnalystResponse] = [r for r in raw_results if r is not None]

    if not valid_responses:
        logger.error("council.all_analysts_failed", candle_open_time=context.candle_open_time)
        # Spec section 41: on failure, fall back to HOLD.
        consensus = ConsensusResult(
            vote_tally={"LONG": 0, "SHORT": 0, "NEUTRAL": 0},
            consensus_bias=Bias.NEUTRAL,
            consensus_confidence=0.0,
            is_strong_consensus=True,
            final_bias=Bias.NEUTRAL,
            final_confidence=0.0,
        )
    else:
        consensus = compute_consensus(valid_responses, consensus_margin=settings.council_consensus_margin)

        if not consensus.is_strong_consensus and settings.judge_enabled:
            judge_response = await _run_judge(client, context, valid_responses)
            if judge_response is not None:
                consensus = apply_judge(consensus, judge_response)

    decision_row = CouncilDecision(
        market_candle_open_time=context.candle_open_time,
        market_timestamp=_open_time_to_dt(context.candle_open_time),
        consensus_bias=consensus.consensus_bias.value,
        consensus_confidence=consensus.consensus_confidence,
        vote_tally=consensus.vote_tally,
        judge_invoked=consensus.judge_invoked,
        judge_response=consensus.judge_response.model_dump() if consensus.judge_response else None,
        final_bias=consensus.final_bias.value,
        final_confidence=consensus.final_confidence,
        key_risks=consensus.judge_response.key_risks if consensus.judge_response else [],
        invalidators=consensus.judge_response.invalidators if consensus.judge_response else [],
    )
    db.add(decision_row)
    await db.flush()

    for response in valid_responses:
        db.add(
            CouncilAnalysis(
                council_decision_id=decision_row.id,
                analyst=response.analyst,
                bias=response.bias.value,
                confidence=response.confidence,
                reasoning=response.reasoning,
                key_factors=response.key_factors,
                invalidators=response.invalidators,
                request_id=client.last_stats.request_id if client.last_stats else "",
                latency_ms=client.last_stats.latency_ms if client.last_stats else 0,
                model=client.last_stats.model if client.last_stats else "",
                was_valid=True,
            )
        )
    await db.commit()

    return consensus


async def _run_judge(client: OllamaClient, context: MarketContext, responses: list[AnalystResponse]) -> JudgeResponse | None:
    analyses_text = "\n".join(
        f"- {r.analyst}: {r.bias.value} (confidence {r.confidence:.2f}) — {r.reasoning}" for r in responses
    )
    user_prompt = (
        f"Market: {context.symbol} {context.timeframe} @ {context.close_price}\n"
        f"Regime: {context.regime.regime.value}\n\n"
        f"Analyst opinions:\n{analyses_text}"
    )
    try:
        judge_response, _stats = await client.generate_structured(
            system_prompt=_JUDGE_SYSTEM_PROMPT, user_prompt=user_prompt, response_model=JudgeResponse
        )
        return judge_response
    except OllamaResponseError:
        logger.error("council.judge_failed", candle_open_time=context.candle_open_time)
        return None


def _open_time_to_dt(open_time_ms: int):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
