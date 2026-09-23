from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent
from app.models.metrics import FitnessScore
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Trade
from app.schemas.api import AgentDetail, AgentSummary

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _to_summary(agent: Agent) -> AgentSummary:
    roi = (agent.equity - agent.starting_balance) / agent.starting_balance if agent.starting_balance else 0.0
    return AgentSummary(
        id=agent.id,
        identifier=agent.identifier,
        generation=agent.generation,
        status=agent.status,
        strategy_version_id=agent.strategy_version_id,
        balance=agent.balance,
        equity=agent.equity,
        starting_balance=agent.starting_balance,
        roi=roi,
        realized_pnl=agent.realized_pnl,
        max_drawdown=agent.max_drawdown,
        trade_count=agent.trade_count,
        is_professional=agent.is_professional,
        best_milestone_multiple=agent.best_milestone_multiple,
        fitness=agent.fitness,
        created_at=agent.created_at,
    )


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    generation: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
):
    stmt = select(Agent)
    if generation is not None:
        stmt = stmt.where(Agent.generation == generation)
    if status_filter is not None:
        stmt = stmt.where(Agent.status == status_filter)
    stmt = stmt.order_by(Agent.identifier).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_to_summary(a) for a in result.scalars().all()]


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    summary = _to_summary(agent)
    return AgentDetail(
        **summary.model_dump(),
        fees_paid=agent.fees_paid,
        funding_paid=agent.funding_paid,
        peak_equity=agent.peak_equity,
        death_timestamp=agent.death_timestamp,
        death_reason=agent.death_reason,
        final_equity=agent.final_equity,
        final_pnl=agent.final_pnl,
    )


@router.get("/{agent_id}/dna")
async def agent_dna(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """The agent's strategy DNA, versioning and lineage (all real, runtime-effective fields)."""
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    version = await db.get(StrategyVersion, agent.strategy_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="strategy version not found")
    strategy = await db.get(Strategy, version.strategy_id)
    return {
        "agent": agent.identifier, "generation": agent.generation, "strategy_code": strategy.code if strategy else None,
        "strategy_version_id": str(version.id), "strategy_version": version.version, "family": strategy.family.value if strategy else None,
        "stage": version.stage.value, "champion_status": version.champion_status.value if version.champion_status else None,
        "parent_a": str(version.parent_strategy_version_id) if version.parent_strategy_version_id else None,
        "parent_b": str(version.parent_b_strategy_version_id) if version.parent_b_strategy_version_id else None,
        "lineage_id": str(strategy.lineage_id) if strategy and strategy.lineage_id else None,
        "experiment_id": version.experiment_id, "dna": version.dna,
    }


@router.get("/{agent_id}/equity-curve")
async def agent_equity_curve(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Realized equity after every closed trade + running drawdown, ending at the live mark-to-market equity."""
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    trades = (await db.execute(select(Trade).where(Trade.agent_id == agent_id).order_by(Trade.closed_at))).scalars().all()
    equity, peak, points = agent.starting_balance, agent.starting_balance, [
        {"t": agent.created_at.isoformat(), "equity": agent.starting_balance, "drawdown": 0.0}]
    for t in trades:
        equity += t.net_pnl
        peak = max(peak, equity)
        points.append({"t": t.closed_at.isoformat(), "equity": equity, "drawdown": (peak - equity) / peak if peak > 0 else 0.0,
                       "net_pnl": t.net_pnl, "exit_reason": t.exit_reason})
    return {"points": points, "current_equity": agent.equity, "max_drawdown": agent.max_drawdown}


@router.get("/{agent_id}/regime-performance")
async def agent_regime_performance(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Trade.entry_regime, Trade.net_pnl).where(Trade.agent_id == agent_id))).all()
    by: dict[str, list[float]] = {}
    for regime, pnl in rows:
        by.setdefault(regime or "UNKNOWN", []).append(pnl)
    return [{"regime": r, "trade_count": len(p), "pnl": sum(p), "win_rate": sum(1 for x in p if x > 0) / len(p),
             "expectancy": sum(p) / len(p)} for r, p in sorted(by.items())]


@router.get("/{agent_id}/fitness")
async def agent_fitness(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db), limit: int = Query(default=20, le=100)):
    rows = (await db.execute(select(FitnessScore).where(FitnessScore.agent_id == agent_id).order_by(FitnessScore.as_of.desc()).limit(limit))).scalars().all()
    return [{"as_of": r.as_of.isoformat(), "fitness": r.fitness, "return": r.return_score, "risk": r.risk_score,
             "consistency": r.consistency_score, "robustness": r.robustness_score, "oos": r.oos_score,
             "drawdown_penalty": r.drawdown_penalty, "instability_penalty": r.instability_penalty,
             "correlation_penalty": r.correlation_penalty, "expectancy": r.expectancy_score, "regime": r.regime_score,
             "adversarial": r.adversarial_score} for r in rows]
