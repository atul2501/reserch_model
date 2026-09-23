"""Manually trigger ONE research/evolution cycle now (ignores the interval,
generation-age and paper-history gates).

The breeding pipeline is a single implementation — `app.research.pipeline`
(evaluate -> fitness -> correlation -> regime -> adversarial -> selection ->
mutation/crossover -> candidate validation -> new generation). This script only
invokes it; the scheduled equivalent is `python -m scripts.run_research`.

Usage:
    python -m scripts.breed_next_generation
"""
from __future__ import annotations

import asyncio

from app.core.database import AsyncSessionLocal
from app.core.logging import configure_logging, get_logger
from app.market.market_data_service import MarketDataService
from app.research.pipeline import run_research_cycle

logger = get_logger(__name__)


async def breed_next_generation(*, survivor_count: int | None = None) -> None:
    configure_logging()
    market = MarketDataService()
    try:
        async with AsyncSessionLocal() as db:
            report = await run_research_cycle(db, market_service=market, force=True)
    finally:
        await market.aclose()
    logger.info("breeding.finished", status=report.status, reason=report.reason, counts=report.counts,
                generation_from=report.generation_from, generation_to=report.generation_to)


if __name__ == "__main__":
    asyncio.run(breed_next_generation())
