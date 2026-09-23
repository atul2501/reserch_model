from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.council import CouncilAnalysis, CouncilDecision

router = APIRouter(prefix="/api/council", tags=["council"])


def _decision(d: CouncilDecision) -> dict:
    return {
        "id": str(d.id), "candle_open_time": d.market_candle_open_time, "status": d.council_status,
        "quorum_met": d.quorum_met, "trade_allowed": d.trade_allowed, "expected_analysts": d.expected_analysts,
        "successful_analysts": d.successful_analysts, "failed_analysts": d.failed_analysts, "failure_reasons": d.failure_reasons,
        "vote_tally": d.vote_tally, "consensus_bias": d.consensus_bias, "consensus_confidence": d.consensus_confidence,
        "judge_invoked": d.judge_invoked, "judge": d.judge_response, "final_bias": d.final_bias,
        "final_confidence": d.final_confidence, "key_risks": d.key_risks, "invalidators": d.invalidators,
        "latency_seconds": d.total_council_latency_seconds, "created_at": d.created_at.isoformat(),
    }


@router.get("/latest")
async def latest(db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(CouncilDecision).order_by(CouncilDecision.market_candle_open_time.desc(),
                                                            CouncilDecision.created_at.desc()).limit(1))).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "no council decision yet")
    analyses = (await db.execute(select(CouncilAnalysis).where(CouncilAnalysis.council_decision_id == d.id))).scalars().all()
    return {**_decision(d), "analysts": [
        {"analyst": a.analyst, "bias": a.bias, "confidence": a.confidence, "reasoning": a.reasoning, "valid": a.was_valid,
         "latency_ms": a.latency_ms, "request_id": a.request_id} for a in analyses]}


@router.get("/history")
async def history(db: AsyncSession = Depends(get_db), limit: int = Query(default=30, le=200)):
    rows = (await db.execute(select(CouncilDecision).order_by(CouncilDecision.created_at.desc()).limit(limit))).scalars().all()
    return [_decision(d) for d in rows]
