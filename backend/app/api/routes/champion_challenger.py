from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.evolution.champion_challenger_service import latest_challenger_evaluation
from app.models.enums import ChampionStatus, EvolutionEventType
from app.models.evolution import EvolutionEvent
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.champion_challenger import ChallengerEvaluationOut, ChampionSummaryOut, EvolutionEventOut

router = APIRouter(prefix="/api/champions", tags=["champion-challenger"])


@router.get("", response_model=list[ChampionSummaryOut])
async def list_champions(db: AsyncSession = Depends(get_db)):
    """Current champion per Strategy lineage — promotion is scoped per-
    lineage (not cross-family competition), so this is the full "one
    champion per lineage" roster, not a single global best."""
    rows = (
        await db.execute(
            select(Strategy, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(StrategyVersion.champion_status == ChampionStatus.CHAMPION)
        )
    ).all()
    return [
        ChampionSummaryOut(
            strategy_id=strategy.id,
            strategy_code=strategy.code,
            strategy_family=strategy.family.value,
            champion_version_id=version.id,
            champion_version_number=version.version,
        )
        for strategy, version in rows
    ]


@router.get("/{strategy_id}/challengers", response_model=list[ChallengerEvaluationOut])
async def list_challengers(strategy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Every non-retired StrategyVersion in this lineage with its latest
    pipeline_stage — the champion itself included, so the champion's own
    evaluation history stays visible alongside its challengers."""
    # champion_status is nullable (most versions never had it set) — see
    # the matching comment in scripts/evaluate_generation.py for why this
    # can't be a plain `!=`.
    versions = (
        await db.execute(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id,
                or_(StrategyVersion.champion_status.is_(None), StrategyVersion.champion_status != ChampionStatus.RETIRED),
            )
        )
    ).scalars().all()

    results = []
    for version in versions:
        evaluation = await latest_challenger_evaluation(db, version.id)
        if evaluation is not None:
            results.append(evaluation)
    return results


@router.get("/{strategy_id}/history", response_model=list[EvolutionEventOut])
async def get_promotion_history(
    strategy_id: uuid.UUID, db: AsyncSession = Depends(get_db), limit: int = Query(default=50, le=200)
):
    """The full promotion/rejection audit log for this lineage — champion_id
    (parent_strategy_version_id), challenger_id (child_strategy_version_id),
    metrics, decision, decision_reason, timestamp are all directly on
    EvolutionEvent, populated by promotion_service.evaluate_and_promote."""
    version_ids = (
        await db.execute(select(StrategyVersion.id).where(StrategyVersion.strategy_id == strategy_id))
    ).scalars().all()
    if not version_ids:
        return []

    events = (
        await db.execute(
            select(EvolutionEvent)
            .where(
                EvolutionEvent.event_type.in_([EvolutionEventType.PROMOTION, EvolutionEventType.REJECTION]),
                EvolutionEvent.child_strategy_version_id.in_(version_ids),
            )
            .order_by(EvolutionEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return events
