"""AI Council orchestration (spec sections 4/8/9).

Runs all analysts concurrently (asyncio.gather — see should_run_council's
neighbor run_council_cycle below; this is NOT 8 sequential calls) against
ONE shared MarketContext, computes a deterministic consensus, invokes the
Ollama judge only when the vote is close, enforces a minimum-quorum gate,
and persists the full audit trail — including failed analysts, not just
successful ones. This runs once per council cycle, not once per agent
(spec section 4).

Fail-closed contract: if fewer than settings.council_min_successful_analysts
respond, this returns council_status="INCOMPLETE", final_bias=NEUTRAL,
trade_allowed=False. Every downstream consumer must gate new entries on
`trade_allowed`, never on final_bias/final_confidence alone — a forced
NEUTRAL from a healthy 8/8 council and a forced NEUTRAL from a degraded
3/8 council must never be indistinguishable to the Risk Engine.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.council.analysts import AnalystRunResult, run_analyst
from app.council.consensus import apply_judge, compute_consensus, tally_votes
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.enums import Bias
from app.schemas.council import ANALYST_NAMES, AnalystResponse, ConsensusResult, JudgeResponse
from app.schemas.market_context import MarketContext
from app.services.ollama_client import OllamaClient, OllamaError

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


def _failed_result(analyst: str, reason: str, started: datetime | None = None) -> AnalystRunResult:
    now = datetime.now(timezone.utc)
    started = started or now
    return AnalystRunResult(
        analyst=analyst, response=None, error=reason, started_at=started, completed_at=now,
        request_id="", latency_ms=int((now - started).total_seconds() * 1000), model="",
    )


async def _gather_analysts_with_deadline(
    client: OllamaClient, context: MarketContext, *, analyst_timeout: float, deadline: float
) -> list[AnalystRunResult]:
    """Runs every analyst concurrently, each with its own timeout, and the
    whole set under one hard deadline. Anything still running at the deadline
    is CANCELLED and recorded as failed — a slow model can delay the council
    by at most `deadline` seconds, never by minutes."""
    if not client.is_available():
        # Known-bad credentials / cooldown: no network, no waiting — fail closed now.
        return [_failed_result(name, "ollama_unavailable") for name in ANALYST_NAMES]

    async def _one(name: str) -> AnalystRunResult:
        started = datetime.now(timezone.utc)
        try:
            return await asyncio.wait_for(
                run_analyst(client, name, context, deadline_seconds=analyst_timeout), timeout=analyst_timeout
            )
        except asyncio.TimeoutError:
            return _failed_result(name, "analyst_timeout", started)

    tasks = {name: asyncio.create_task(_one(name), name=f"analyst-{name}") for name in ANALYST_NAMES}
    done, pending = await asyncio.wait(tasks.values(), timeout=deadline)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        logger.error("council.deadline_exceeded_cancelled_slow_analysts", deadline=deadline, cancelled=len(pending))
    results: list[AnalystRunResult] = []
    for name, task in tasks.items():
        if task in done and not task.cancelled() and task.exception() is None:
            results.append(task.result())
        else:
            results.append(_failed_result(name, "council_deadline_exceeded"))
    return results


async def run_council_cycle(
    db: AsyncSession,
    client: OllamaClient,
    context: MarketContext,
    *,
    deadline_seconds: float | None = None,
    analyst_timeout_seconds: float | None = None,
) -> ConsensusResult:
    settings = get_settings()
    council_start_monotonic = time.monotonic()
    council_start_epoch = time.time()
    deadline = deadline_seconds if deadline_seconds is not None else settings.council_deadline_seconds
    analyst_timeout = analyst_timeout_seconds if analyst_timeout_seconds is not None else settings.council_analyst_timeout_seconds

    # All analysts share the SAME client instance (auth/backoff/concurrency
    # live there) and run concurrently under per-analyst and whole-council
    # deadlines. The result is bound to `context.candle_open_time` and is
    # never reused for another candle.
    results: list[AnalystRunResult] = await _gather_analysts_with_deadline(
        client, context, analyst_timeout=analyst_timeout, deadline=deadline
    )

    expected_analysts = len(ANALYST_NAMES)
    succeeded = [r for r in results if r.response is not None]
    failed = [r for r in results if r.response is None]
    successful_analysts = len(succeeded)
    failed_analysts = [r.analyst for r in failed]
    failure_reasons = {r.analyst: (r.error or "unknown_error") for r in failed}
    quorum_met = successful_analysts >= settings.council_min_successful_analysts

    consensus_time_monotonic: float
    metrics.inc("council_cycles", status="COMPLETE" if quorum_met else "INCOMPLETE")
    if not quorum_met:
        metrics.inc("council_quorum_failures")
        logger.error(
            "council.quorum_not_met",
            candle_open_time=context.candle_open_time,
            expected=expected_analysts,
            successful=successful_analysts,
            required=settings.council_min_successful_analysts,
            failed_analysts=failed_analysts,
        )
        valid_responses = [r.response for r in succeeded if r.response is not None]
        consensus = ConsensusResult(
            vote_tally=tally_votes(valid_responses) if valid_responses else {"LONG": 0, "SHORT": 0, "NEUTRAL": 0},
            consensus_bias=Bias.NEUTRAL,
            consensus_confidence=0.0,
            is_strong_consensus=False,
            judge_invoked=False,
            judge_response=None,
            final_bias=Bias.NEUTRAL,
            final_confidence=0.0,
            council_status="INCOMPLETE",
            expected_analysts=expected_analysts,
            successful_analysts=successful_analysts,
            failed_analysts=failed_analysts,
            failure_reasons=failure_reasons,
            quorum_met=False,
            trade_allowed=False,
        )
        consensus_time_monotonic = time.monotonic()
    else:
        valid_responses = [r.response for r in succeeded if r.response is not None]
        consensus = compute_consensus(valid_responses, consensus_margin=settings.council_consensus_margin)
        consensus = consensus.model_copy(
            update={
                "council_status": "COMPLETE",
                "expected_analysts": expected_analysts,
                "successful_analysts": successful_analysts,
                "failed_analysts": failed_analysts,
                "failure_reasons": failure_reasons,
                "quorum_met": True,
                "trade_allowed": True,
            }
        )

        remaining = deadline - (time.monotonic() - council_start_monotonic)
        if not consensus.is_strong_consensus and settings.judge_enabled and remaining > 2.0:
            try:
                judge_response = await asyncio.wait_for(_run_judge(client, context, valid_responses), timeout=remaining)
            except asyncio.TimeoutError:
                logger.error("council.judge_deadline_exceeded", remaining=remaining)
                judge_response = None
            if judge_response is not None:
                consensus = apply_judge(consensus, judge_response)
        consensus_time_monotonic = time.monotonic()

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
        council_status=consensus.council_status,
        expected_analysts=expected_analysts,
        successful_analysts=successful_analysts,
        failed_analysts=failed_analysts,
        failure_reasons=failure_reasons,
        quorum_met=quorum_met,
        trade_allowed=consensus.trade_allowed,
        council_start=council_start_epoch,
        total_council_latency_seconds=time.monotonic() - council_start_monotonic,
    )
    db.add(decision_row)
    await db.flush()

    # Persist a CouncilAnalysis row for EVERY analyst, succeeded or failed
    # — was_valid distinguishes them, so "who failed and why" is part of
    # the permanent audit trail, not just a transient log line.
    for r in results:
        db.add(
            CouncilAnalysis(
                council_decision_id=decision_row.id,
                analyst=r.analyst,
                bias=r.response.bias.value if r.response else Bias.NEUTRAL.value,
                confidence=r.response.confidence if r.response else 0.0,
                reasoning=r.response.reasoning if r.response else f"FAILED: {r.error}",
                key_factors=r.response.key_factors if r.response else [],
                invalidators=r.response.invalidators if r.response else [],
                request_id=r.request_id,
                latency_ms=r.latency_ms,
                model=r.model,
                was_valid=r.response is not None,
                started_at=r.started_at,
                completed_at=r.completed_at,
            )
        )
    await db.commit()

    total_latency = time.monotonic() - council_start_monotonic
    consensus = consensus.model_copy(
        update={
            "council_decision_id": decision_row.id,
            "council_start": council_start_epoch,
            "consensus_time": consensus_time_monotonic - council_start_monotonic,
            "total_council_latency": total_latency,
        }
    )

    logger.info(
        "council.cycle_timing",
        candle_open_time=context.candle_open_time,
        council_start=council_start_epoch,
        consensus_time=consensus.consensus_time,
        total_council_latency=total_latency,
        successful_analysts=successful_analysts,
        expected_analysts=expected_analysts,
    )

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
    except (OllamaError, httpx.HTTPError) as exc:
        logger.error("council.judge_failed", candle_open_time=context.candle_open_time, error=str(exc))
        return None


def _open_time_to_dt(open_time_ms: int) -> datetime:
    return datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
