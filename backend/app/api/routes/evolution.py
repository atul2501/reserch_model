from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.enums import AgentStatus, EvolutionEventType
from app.models.evolution import EvolutionEvent
from app.models.research import Experiment
from app.models.strategy import Generation
from app.models.trading import Trade

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/generations")
async def generations(db: AsyncSession = Depends(get_db), limit: int = Query(default=20, le=100)):
    gens = (await db.execute(select(Generation).order_by(Generation.number.desc()).limit(limit))).scalars().all()
    out = []
    for g in gens:
        rows = (await db.execute(select(Agent.status, func.count(), func.coalesce(func.sum(Agent.equity), 0.0))
                                 .where(Agent.generation == g.number).group_by(Agent.status))).all()
        by = {s.value: {"count": n, "equity": float(e)} for s, n, e in rows}
        deaths = by.get(AgentStatus.DEAD.value, {}).get("count", 0)

        # PnL/fitness aggregates for the dashboard's Generation Performance panel - additive,
        # read-only, computed from realized_pnl/fitness that already live on Agent.
        pnl_rows = (await db.execute(select(Agent.realized_pnl).where(Agent.generation == g.number))).scalars().all()
        fitness_rows = [f for f in (await db.execute(
            select(Agent.fitness).where(Agent.generation == g.number)
        )).scalars().all() if f is not None]
        population = len(pnl_rows)
        total_trades = (await db.execute(
            select(func.count()).select_from(Trade).join(Agent, Agent.id == Trade.agent_id)
            .where(Agent.generation == g.number)
        )).scalar_one()

        out.append({"number": g.number, "population": g.population_created, "triggered_by": g.triggered_by,
                    "created_at": g.created_at.isoformat(), "by_status": by, "deaths": deaths,
                    "total_trades": total_trades,
                    "avg_pnl": statistics.fmean(pnl_rows) if pnl_rows else None,
                    "median_pnl": statistics.median(pnl_rows) if pnl_rows else None,
                    "best_pnl": max(pnl_rows) if pnl_rows else None,
                    "avg_fitness": statistics.fmean(fitness_rows) if fitness_rows else None,
                    "best_fitness": max(fitness_rows) if fitness_rows else None,
                    "survival_rate": ((population - deaths) / population) if population else None})
    return out


@router.get("/events")
async def events(db: AsyncSession = Depends(get_db), generation: int | None = None, limit: int = Query(default=100, le=500)):
    stmt = select(EvolutionEvent).order_by(EvolutionEvent.created_at.desc()).limit(limit)
    if generation is not None:
        stmt = stmt.where(EvolutionEvent.generation == generation)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"type": e.event_type.value, "generation": e.generation, "parent_a": str(e.parent_strategy_version_id) if e.parent_strategy_version_id else None,
             "parent_b": str(e.parent_strategy_version_id_2) if e.parent_strategy_version_id_2 else None,
             "child": str(e.child_strategy_version_id) if e.child_strategy_version_id else None, "accepted": e.accepted,
             "rejection_reason": e.rejection_reason, "created_at": e.created_at.isoformat()} for e in rows]


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    counts = dict((t.value, n) for t, n in (await db.execute(select(EvolutionEvent.event_type, func.count()).group_by(EvolutionEvent.event_type))).all())
    last = (await db.execute(select(Experiment).where(Experiment.kind == "evolution").order_by(Experiment.created_at.desc()).limit(1))).scalar_one_or_none()
    return {"event_counts": counts, "births": sum(counts.get(t.value, 0) for t in (EvolutionEventType.CROSSOVER, EvolutionEventType.MUTATION, EvolutionEventType.NOVEL_GENERATION)),
            "last_experiment": None if last is None else {"experiment_id": last.experiment_id, "status": last.status, "result": last.result,
                                                          "created_at": last.created_at.isoformat(), "dataset_fingerprint": last.dataset_fingerprint,
                                                          "code_version": last.code_version, "schema_version": last.schema_version}}


@router.get("/experiments")
async def experiments(db: AsyncSession = Depends(get_db), kind: str | None = None, limit: int = Query(default=30, le=200)):
    stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(Experiment.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"experiment_id": e.experiment_id, "kind": e.kind, "status": e.status, "generation": e.generation,
             "dataset_fingerprint": e.dataset_fingerprint, "epoch_id": e.epoch_id, "random_seed": e.random_seed,
             "code_version": e.code_version, "schema_version": e.schema_version, "parameters": e.parameters,
             "result": e.result, "created_at": e.created_at.isoformat(),
             "finished_at": e.finished_at.isoformat() if e.finished_at else None} for e in rows]


@router.get("/experiments/diff")
async def experiment_diff(experiment_a: str, experiment_b: str, db: AsyncSession = Depends(get_db)):
    """Baseline-vs-candidate diff for two experiment_ids (see
    app.research.experiment_runner.diff_experiments)."""
    from app.research.experiment_runner import diff_experiments

    a = (await db.execute(select(Experiment).where(Experiment.experiment_id == experiment_a))).scalar_one_or_none()
    b = (await db.execute(select(Experiment).where(Experiment.experiment_id == experiment_b))).scalar_one_or_none()
    if a is None or b is None:
        return {"error": "one or both experiment_ids not found", "experiment_a": experiment_a, "experiment_b": experiment_b}
    return {
        "experiment_a": {"experiment_id": a.experiment_id, "parameters": a.parameters, "created_at": a.created_at.isoformat()},
        "experiment_b": {"experiment_id": b.experiment_id, "parameters": b.parameters, "created_at": b.created_at.isoformat()},
        "diff": {k: {"a": va, "b": vb, "delta": d} for k, (va, vb, d) in diff_experiments(a, b).items()},
    }
