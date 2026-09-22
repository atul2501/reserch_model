"""Breeds and spawns the next generation from the current one's survivors
(spec sections 25, 27, 29). Mirrors bootstrap_population.py's structure but
selects/breeds DNA from the live population instead of generating it fresh.

Usage:
    python -m scripts.breed_next_generation
"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.agents.lifecycle import create_generation
from app.analytics.fitness_service import compute_and_persist_agent_fitness
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.evolution.breeding import select_and_breed_next_generation
from app.evolution.correlation_service import (
    apply_diversity_pressure,
    compute_generation_correlation_report,
    persist_generation_correlation,
)
from app.models.strategy import Generation

logger = get_logger(__name__)


async def breed_next_generation(*, survivor_count: int | None = None) -> None:
    configure_logging()
    settings = get_settings()

    async with session_scope() as db:
        current_generation_number = (await db.execute(select(func.max(Generation.number)))).scalar()
        if current_generation_number is None:
            raise RuntimeError("no generation exists yet — run scripts.bootstrap_population first")

        fitness_summary = await compute_and_persist_agent_fitness(db, generation=current_generation_number)
        await db.commit()
        logger.info(
            "breeding.fitness_computed",
            generation=fitness_summary.generation,
            agent_count=fitness_summary.agent_count,
            mean_fitness=fitness_summary.mean_fitness,
        )

        pressure = None
        if settings.correlation_diversity_pressure_enabled:
            correlation_report = await compute_generation_correlation_report(
                db,
                generation=current_generation_number,
                bucket=settings.correlation_time_bucket,
                lookback_days=settings.correlation_lookback_days,
                max_strategy_correlation=settings.max_strategy_correlation,
            )
            await persist_generation_correlation(db, correlation_report)
            pressure = await apply_diversity_pressure(
                db,
                report=correlation_report,
                max_strategy_correlation=settings.max_strategy_correlation,
                min_strategy_diversity=settings.min_strategy_diversity,
            )
            await db.commit()
            logger.info(
                "breeding.correlation_computed",
                generation=current_generation_number,
                mean_pairwise_correlation=correlation_report.mean_pairwise_correlation,
                population_diversity_score=correlation_report.population_diversity_score,
                diversity_pressure_applied=pressure.diversity_pressure_applied,
                reasons=pressure.reasons,
            )

        result = await select_and_breed_next_generation(
            db,
            generation_number=current_generation_number,
            survivor_count=survivor_count or max(1, settings.agent_count // 5),
            next_generation_size=settings.agent_count,
            preserve_family_codes=pressure.preserve_family_codes if pressure else None,
            mutation_rate_multiplier=pressure.mutation_rate_multiplier if pressure else 1.0,
            max_family_survivor_fraction=settings.max_family_survivor_fraction,
        )

        generation = await create_generation(
            db,
            generation_number=current_generation_number + 1,
            strategy_version_ids=result.strategy_version_ids,
            starting_balance=settings.agent_starting_balance,
            triggered_by="evolution_breeding",
        )

    logger.info(
        "breeding.complete",
        generation=generation.number,
        agent_count=generation.population_created,
        diversity_score=result.diversity_score,
        injected_fresh_count=result.injected_fresh_count,
        rejected_and_remutated_count=result.rejected_and_remutated_count,
    )


if __name__ == "__main__":
    asyncio.run(breed_next_generation())
