"""READ-ONLY side-by-side report of the production fitness and the SHADOW (Phase 0) proposed fitness.

Nothing is written: no fitness, status, selection, breeding or champion state is touched, and the session is rolled back.
`Agent.fitness` (current) stays the only score anything acts on.

Usage:
    python -m scripts.shadow_fitness_report                  # latest generation, top 10
    python -m scripts.shadow_fitness_report --generation 3 --top 25 --csv shadow.csv
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import csv

from sqlalchemy import func, select

from app.analytics.shadow_fitness import ShadowRow, rank_correlation, ranked, shadow_rows_for_generation
from app.core.database import AsyncSessionLocal, engine
from app.models.agent import Agent

COLUMNS = ["agent_id", "family", "current_fitness", "trade_count", "net_pnl", "net_bps", "mean_r", "drawdown", "expectancy",
           "R_posterior_mean", "R_posterior_variance", "R_reliability", "R_state", "bps_posterior_mean", "bps_posterior_variance",
           "bps_reliability", "bps_state"]


def _flat(r: ShadowRow) -> dict:
    return {"agent_id": r.agent_id, "family": r.family, "current_fitness": r.current_fitness, "trade_count": r.trade_count,
            "net_pnl": r.net_pnl, "net_bps": r.net_bps, "mean_r": r.mean_r, "drawdown": r.drawdown, "expectancy": r.expectancy,
            "R_posterior_mean": r.r.posterior_mean, "R_posterior_variance": r.r.posterior_variance, "R_reliability": r.r.reliability,
            "R_state": r.r.state, "bps_posterior_mean": r.bps.posterior_mean, "bps_posterior_variance": r.bps.posterior_variance,
            "bps_reliability": r.bps.reliability, "bps_state": r.bps.state}


def render(rows: list[ShadowRow], top: int) -> str:
    out = [f"agents: {len(rows)}"]
    for unit in ("R", "bps"):
        out.append(f"states ({unit}): {dict(collections.Counter(r.unit(unit).state for r in rows))}")
    for unit in ("R", "bps"):
        for inc in (False, True):
            rho, n = rank_correlation(rows, "current", unit, include_provisional=inc)
            out.append(f"Spearman(current, {unit}{' +PROVISIONAL' if inc else ' TESTED-only'}): "
                       f"{'n/a' if rho is None else f'{rho:.2f}'} over {n} agents")
    for label, key, inc in (("current", "current", False), ("R (TESTED+PROVISIONAL)", "R", True), ("bps (TESTED+PROVISIONAL)", "bps", True)):
        out.append(f"\ntop {top} by {label}:")
        for r in ranked(rows, key, top=top, include_provisional=inc):
            out.append(f"  {str(r.agent_id)[:8]} {r.family or '-':<16} n={r.trade_count:<4} pnl={r.net_pnl:+.2f} "
                       f"bps={'-' if r.net_bps is None else f'{r.net_bps:+.1f}'} dd={100 * r.drawdown:.2f}% "
                       f"cur={'-' if r.current_fitness is None else f'{r.current_fitness:+.3f}'} "
                       f"R={r.r.state}/{'-' if r.r.posterior_mean is None else f'{r.r.posterior_mean:+.2f}'} "
                       f"bps={r.bps.state}/{'-' if r.bps.posterior_mean is None else f'{r.bps.posterior_mean:+.1f}'}")
    return "\n".join(out)


async def main(generation: int | None, top: int, csv_path: str | None) -> None:
    async with AsyncSessionLocal() as db:
        gen = generation if generation is not None else (await db.execute(select(func.max(Agent.generation)))).scalar_one()
        rows = await shadow_rows_for_generation(db, gen)
        await db.rollback()      # read-only by construction; make it explicit
    print(f"generation {gen}")
    print(render(rows, top))
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(_flat(r) for r in rows)
        print(f"\nwrote {len(rows)} rows to {csv_path}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--generation", type=int, default=None)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()
    asyncio.run(main(args.generation, args.top, args.csv))
