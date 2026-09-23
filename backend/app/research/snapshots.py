"""Immutable strategy snapshots (spec phase 32).

A snapshot freezes everything needed to reproduce an agent's behaviour: DNA,
risk / indicator / regime / model configuration, fitness, performance metrics,
and provenance (experiment id, code version, schema version, dataset
fingerprint). Rows are write-once: the ORM (`ImmutableRecordError`) and the
database (triggers created by the T7 migration) both refuse UPDATE and DELETE.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.metrics import PerformanceMetric
from app.models.strategy import AgentSnapshot, StrategyVersion
from app.research.registry import code_version, schema_version
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import ENGINE_VERSION


async def create_agent_snapshot(
    db: AsyncSession,
    agent: Agent,
    version: StrategyVersion,
    *,
    experiment_id: str | None = None,
    dataset_fingerprint: str | None = None,
    performance: dict | None = None,
) -> AgentSnapshot:
    dna = StrategyDNA.model_validate(version.dna)
    settings = get_settings()
    if performance is None:
        latest = (
            await db.execute(
                select(PerformanceMetric).where(PerformanceMetric.agent_id == agent.id)
                .order_by(PerformanceMetric.as_of.desc()).limit(1)
            )
        ).scalar_one_or_none()
        performance = (
            {c.name: (getattr(latest, c.name).isoformat() if hasattr(getattr(latest, c.name), "isoformat") else getattr(latest, c.name))
             for c in latest.__table__.columns if c.name not in ("id", "agent_id", "created_at", "updated_at")}
            if latest is not None else {}
        )
    snap = AgentSnapshot(
        agent_id=agent.id,
        strategy_version_id=version.id,
        strategy_id=version.strategy_id,
        strategy_version_number=version.version,
        generation=agent.generation,
        strategy_dna=version.dna,
        risk_config={
            "risk_profile": dna.risk_profile.model_dump(), "position_sizing": dna.position_sizing.model_dump(),
            "stop_loss": dna.stop_loss.model_dump(), "take_profit": dna.take_profit.model_dump(),
            "trailing_stop": dna.trailing_stop.model_dump(), "cooldown": dna.cooldown.model_dump(),
            "max_trades_per_day": dna.max_trades_per_day, "leverage_limit": dna.leverage_limit,
            "global": {"max_leverage": settings.max_leverage, "max_position_size": settings.max_position_size,
                       "max_drawdown": settings.max_drawdown, "max_daily_loss": settings.max_daily_loss,
                       "max_exposure_multiple": settings.max_exposure_multiple,
                       "max_loss_per_trade_fraction": settings.max_loss_per_trade_fraction},
        },
        indicator_config={"indicators": [i.model_dump() for i in dna.indicators], "lookback_periods": dna.lookback_periods,
                          "engine_version": ENGINE_VERSION},
        regime_config={"regime_preferences": [r.value for r in dna.regime_preferences]},
        model_config_snapshot={"ollama_model": settings.ollama_model, "council_min_successful_analysts": settings.council_min_successful_analysts,
                               "council_interval_candles": settings.council_interval_candles},
        fitness=agent.fitness,
        performance_metrics=performance,
        software_version=code_version(),
        schema_version=schema_version(),
        experiment_id=experiment_id or version.experiment_id,
        dataset_fingerprint=dataset_fingerprint,
    )
    snap.id = uuid.uuid4()
    db.add(snap)
    return snap
