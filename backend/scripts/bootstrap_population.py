"""One-time (or post-extinction) bootstrap: creates AGENT_COUNT diverse
strategies and the first/next generation of agents against them (spec
sections 11, 15, 52).

Usage:
    python -m scripts.bootstrap_population
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.agents.lifecycle import create_generation
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.models.enums import StrategyStage
from app.models.strategy import Generation, Strategy, StrategyVersion
from app.strategies.factory import generate_population_dna

logger = get_logger(__name__)


async def bootstrap() -> None:
    configure_logging()
    settings = get_settings()

    async with session_scope() as db:
        last_generation_number = (await db.execute(select(func.max(Generation.number)))).scalar() or 0
        next_generation_number = last_generation_number + 1

        dnas = generate_population_dna(settings.agent_count, seed=next_generation_number)

        strategy_version_ids = []
        for i, dna in enumerate(dnas, start=1):
            code = f"STRAT-{dna.strategy_family.value.upper()}-GEN{next_generation_number:02d}-{i:04d}"
            strategy = Strategy(code=code, family=dna.strategy_family, name=code)
            db.add(strategy)
            await db.flush()
            strategy.lineage_id = strategy.id  # every founder starts its own lineage

            version = StrategyVersion(
                strategy_id=strategy.id,
                version=1,
                generation=next_generation_number,
                dna=dna.model_dump(mode="json"),
                proposed_by="system",
                stage=StrategyStage.PAPER,          # the population trades on paper from birth
                stage_entered_at=datetime.now(timezone.utc),
            )
            db.add(version)
            await db.flush()
            strategy_version_ids.append(version.id)

        await db.commit()

        generation = await create_generation(
            db,
            generation_number=next_generation_number,
            strategy_version_ids=strategy_version_ids,
            starting_balance=settings.agent_starting_balance,
            triggered_by="bootstrap_script",
        )

    logger.info(
        "bootstrap.complete",
        generation=generation.number,
        agent_count=generation.population_created,
        total_capital_allocated=generation.total_capital_allocated,
    )


if __name__ == "__main__":
    asyncio.run(bootstrap())
