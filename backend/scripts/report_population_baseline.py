"""READ-ONLY population/lifecycle baseline (24h diagnostic report, phase 2).

    python -m scripts.report_population_baseline <path-to-snapshot-sqlite-db>

Reports population counts, capital distribution, lifetime, and death causes
directly from Agent/Strategy/StrategyVersion — the ground raw tables, not the
derived analytics tables (those are covered by report_trade_quality.py and
report_strategy_regime.py). Never writes anything.
"""
from __future__ import annotations

import asyncio
import statistics
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent import Agent
from app.models.enums import AgentStatus
from app.models.strategy import Strategy, StrategyVersion  # noqa: E402


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def _stats(vals: list[float]) -> str:
    if not vals:
        return "n/a"
    return (f"mean={statistics.mean(vals):.4f} median={statistics.median(vals):.4f} "
            f"min={min(vals):.4f} max={max(vals):.4f} stdev={statistics.pstdev(vals):.4f}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.report_population_baseline <path-to-snapshot-sqlite-db>")
        raise SystemExit(1)
    engine = create_async_engine(f"sqlite+aiosqlite:///{sys.argv[1]}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        agents = (await db.execute(select(Agent))).scalars().all()
        versions = {v.id: v for v in (await db.execute(select(StrategyVersion))).scalars().all()}
        strategies = {s.id: s for s in (await db.execute(select(Strategy))).scalars().all()}
    await engine.dispose()

    n = len(agents)
    print(f"=== POPULATION ({n} agents) ===\n")

    by_status = Counter(a.status.value for a in agents)
    for status in ("ACTIVE", "PAUSED", "DEAD", "RETIRED"):
        print(f"  {status:8s}: {by_status.get(status, 0):5d}  ({_pct(by_status.get(status, 0), n)})")

    generations = sorted({a.generation for a in agents})
    print(f"\n  generations present: {generations}")
    for g in generations:
        gc = sum(1 for a in agents if a.generation == g)
        print(f"    generation {g}: {gc} agents")

    by_family = Counter()
    for a in agents:
        v = versions.get(a.strategy_version_id)
        s = strategies.get(v.strategy_id) if v else None
        by_family[s.family.value if s else "UNKNOWN"] += 1
    print("\n  agents by strategy family:")
    for fam, c in by_family.most_common():
        print(f"    {fam:18s}: {c:5d}  ({_pct(c, n)})")

    # DEAD agents carry a precise death_timestamp; RETIRED ones (superseded at generation
    # rollover) don't get one (lifecycle.py only sets it in the DEAD path) -- updated_at
    # is the best available proxy for when a RETIRED agent's generation ended.
    lifetimes_hours = []
    for a in agents:
        if a.status == AgentStatus.DEAD and a.death_timestamp is not None:
            lifetimes_hours.append((a.death_timestamp - a.created_at).total_seconds() / 3600.0)
        elif a.status == AgentStatus.RETIRED:
            lifetimes_hours.append((a.updated_at - a.created_at).total_seconds() / 3600.0)
    print(f"\n  average agent lifetime (dead/retired agents, n={len(lifetimes_hours)}): "
          f"{_stats(lifetimes_hours)} hours")

    dead = [a for a in agents if a.status == AgentStatus.DEAD]
    print(f"\n=== DEATH CAUSES (n={len(dead)} dead agents) ===")
    by_reason = Counter(a.death_reason or "UNSPECIFIED" for a in dead)
    for reason, c in by_reason.most_common():
        print(f"  {reason:30s}: {c:5d}  ({_pct(c, len(dead))})")

    print("\n=== CAPITAL DISTRIBUTION (active + paused agents) ===")
    live = [a for a in agents if a.status in (AgentStatus.ACTIVE, AgentStatus.PAUSED)]
    print(f"  starting_balance: {_stats([a.starting_balance for a in live])}")
    print(f"  equity:           {_stats([a.equity for a in live])}")
    print(f"  balance:          {_stats([a.balance for a in live])}")
    print(f"  max_drawdown:     {_stats([a.max_drawdown for a in live])}")
    print(f"  trade_count:      {_stats([float(a.trade_count) for a in live])}")

    print("\n=== FITNESS (agents with a computed fitness score) ===")
    scored = [a for a in agents if a.fitness is not None]
    print(f"  scored: {len(scored)}/{n}")
    print(f"  fitness: {_stats([a.fitness for a in scored])}")

    print("\n24-hour diagnostic baseline -- insufficient for long-term strategy conclusions.")


if __name__ == "__main__":
    asyncio.run(main())
