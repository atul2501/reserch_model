"""Advance strategy versions through the Candidate -> ... -> Promotion
pipeline using whatever evidence currently exists (no new backtests; the
scheduled research cycle produces those). Safe to run any time.

Usage:
    python -m scripts.evaluate_generation
"""
from __future__ import annotations

import asyncio

from sqlalchemy import or_, select

from app.backtesting.reality_gap_engine import compute_full_reality_gap_chain, persist_reality_gap_report
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.evolution.champion_challenger_service import advance_pipeline_stage, latest_challenger_evaluation
from app.models.enums import ChampionStatus
from app.models.strategy import StrategyVersion

logger = get_logger(__name__)


async def evaluate_generation() -> None:
    configure_logging()
    async with session_scope() as db:
        versions = (
            await db.execute(
                select(StrategyVersion).where(
                    or_(StrategyVersion.champion_status.is_(None), StrategyVersion.champion_status != ChampionStatus.RETIRED)
                )
            )
        ).scalars().all()
        for version in versions:
            evaluation = await latest_challenger_evaluation(db, version.id)
            current_stage = evaluation.pipeline_stage if evaluation is not None else "candidate"
            if current_stage in ("promoted", "rejected"):
                continue
            chain = await compute_full_reality_gap_chain(db, version.id)
            if chain.transitions:
                await persist_reality_gap_report(db, chain)
            result = await advance_pipeline_stage(db, version.id, promotion_stage=version.stage)
            await db.commit()
            logger.info("evaluate_generation.pipeline_advanced", strategy_version_id=str(version.id), from_stage=current_stage,
                        to_stage=result.pipeline_stage, blocking_reasons=result.blocking_reasons)


if __name__ == "__main__":
    asyncio.run(evaluate_generation())
