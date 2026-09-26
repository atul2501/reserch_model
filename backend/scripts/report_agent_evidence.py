"""READ-ONLY agent evidence report (Report E): is a high fitness GENUINE?

    python -m scripts.report_agent_evidence
    python -m scripts.report_agent_evidence --generation 2 --top 25 --csv ev.csv --json ev.json

Reuses the production shadow-fitness evidence states (UNTESTABLE / UNTESTED /
PROVISIONAL / TESTED, empirical-Bayes reliability) and adds the observation
window, exposure, current fitness, forward performance (from
fitness_forward_performance) and a dominant-explanation decomposition — where
this agent's score is actually coming from (genuine edge / low drawdown /
inactivity / insufficient evidence / luck / family concentration).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import defaultdict

from sqlalchemy import func, select

from app.analytics.shadow_fitness import shadow_rows_for_generation
from app.core.database import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.analytics import FitnessForwardPerformance, TradeAnalytics
from app.models.stage_metrics import StageMetrics

COLUMNS = ["agent", "generation", "family", "evidence_state", "trades", "observation_days", "exposure",
           "fitness_now", "mean_r", "net_pnl", "posterior_r", "reliability", "p_edge_positive",
           "future_trades", "future_net_pnl", "dominant_explanation"]

MIN_GENUINE_TRADES = 10


def _explanation(state: str, trade_count: int, mean_r: float | None, expectancy: float | None,
                 drawdown: float, p_edge_positive: float | None) -> str:
    """The dominant explanation for this agent's score, checked in priority order."""
    if state == "UNTESTABLE":
        return "untestable (cannot reach the exchange minimum)"
    if trade_count == 0:
        return "inactivity (no trades — the score is priors/penalties, not performance)"
    if trade_count < MIN_GENUINE_TRADES:
        return "insufficient evidence (short history)"
    if state in ("UNTESTED", "PROVISIONAL"):
        return "insufficient evidence (estimate not yet reliable)"
    # TESTED from here: separate a real edge from cosmetics
    if p_edge_positive is not None and p_edge_positive >= 0.8 and (mean_r or 0) > 0:
        return "genuine positive edge (posterior P(edge>0) >= 0.8)"
    if drawdown < 0.02 and abs(expectancy or 0.0) < 1e-9:
        return "low drawdown with ~zero expectancy (survival cosmetics)"
    if drawdown < 0.02 and (expectancy or 0.0) <= 0:
        return "low drawdown, negative expectancy (not an edge)"
    return "TESTED edge estimate not conclusive"


async def main(generation: int | None, top: int, csv_path: str | None, json_path: str | None) -> None:
    async with AsyncSessionLocal() as db:
        gen = generation if generation is not None else (
            (await db.execute(select(func.max(Agent.generation)))).scalar_one()
        )
        srows = await shadow_rows_for_generation(db, gen)
        row_by_agent = {r.agent_id: r for r in srows}

        # plain fields fetched BEFORE the rollback (rollback expires ORM instances)
        agent_facts = {
            a.id: (a.identifier, a.strategy_version_id, a.starting_balance)
            for a in (await db.execute(select(Agent).where(Agent.generation == gen))).scalars()
        }
        observed: dict = {}
        for sm in (await db.execute(select(StageMetrics).where(StageMetrics.stage == "PAPER"))).scalars():
            observed[sm.strategy_version_id] = sm.observed_days

        # exposure: traded notional per (starting balance x observed day) from trade_analytics
        notional_by_agent: dict = defaultdict(float)
        trades_by_agent: dict = defaultdict(int)
        for ta in (await db.execute(select(TradeAnalytics))).scalars():
            if ta.agent_id in agent_facts:
                notional_by_agent[ta.agent_id] += ta.position_notional or 0.0
                trades_by_agent[ta.agent_id] += 1

        fwd: dict = {}
        for r in (await db.execute(
            select(FitnessForwardPerformance)
            .where(FitnessForwardPerformance.agent_id.in_(list(agent_facts)))
            .order_by(FitnessForwardPerformance.as_of, FitnessForwardPerformance.horizon_minutes)
        )).scalars():
            fwd[r.agent_id] = (r.future_trade_count, r.future_net_pnl)   # plain fields, ORM expires later

        await db.rollback()  # read-only by construction; make it explicit

    out: list[dict] = []
    for row in srows:
        facts_ = agent_facts.get(row.agent_id)
        identifier, version_id, starting_balance = facts_ if facts_ else (str(row.agent_id), None, None)
        obs_days = observed.get(version_id) if version_id else None
        exposure = None
        if obs_days and obs_days > 0 and starting_balance and starting_balance > 0:
            exposure = notional_by_agent.get(row.agent_id, 0.0) / (starting_balance * obs_days)
        f = fwd.get(row.agent_id)
        out.append({
            "agent": identifier,
            "generation": gen,
            "family": row.family,
            "evidence_state": row.r.state,
            "trades": row.trade_count,
            "observation_days": obs_days,
            "exposure": exposure,
            "fitness_now": row.current_fitness,
            "mean_r": row.mean_r,
            "net_pnl": row.net_pnl,
            "posterior_r": row.r.posterior_mean,
            "reliability": row.r.reliability,
            "p_edge_positive": row.r.p_edge_positive,
            "future_trades": f[0] if f else None,
            "future_net_pnl": f[1] if f else None,
            "dominant_explanation": _explanation(
                row.r.state, row.trade_count, row.mean_r, row.expectancy, row.drawdown, row.r.p_edge_positive
            ),
        })

    ranked = [r for r in out if r["fitness_now"] is not None]
    ranked.sort(key=lambda r: -r["fitness_now"])
    shown = ranked[:top]

    states: dict[str, int] = defaultdict(int)
    for r in out:
        states[r["evidence_state"]] += 1

    print(f"agent evidence report — generation {gen}, agents: {len(out)}")
    print(f"evidence states: {dict(states)}")
    print(f"top {len(shown)} by current fitness (every row shows its evidence basis):")
    for r in shown:
        obs = f"{r['observation_days']:.1f}" if r["observation_days"] is not None else "-"
        expo = f"{r['exposure']:.1f}" if r["exposure"] is not None else "-"
        mr = f"{r['mean_r']:+.2f}" if r["mean_r"] is not None else "-"
        pe = f"{r['p_edge_positive']:.2f}" if r["p_edge_positive"] is not None else "-"
        ft = r["future_trades"] if r["future_trades"] is not None else "-"
        fp = f"{r['future_net_pnl']:+.2f}" if r["future_net_pnl"] is not None else "-"
        print(f"  {r['agent']:<14} {str(r['family']):<16} n={r['trades']:<4} {r['evidence_state']:<10}"
              f" obs_d={obs:<6} expo={expo:<6} fitness={r['fitness_now']:+.3f} R={mr} P(edge>0)={pe}"
              f" fwd(n={ft},pnl={fp})")
        print(f"      -> {r['dominant_explanation']}")

    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(shown)
        print(f"\nwrote {len(shown)} rows to {csv_path}")
    if json_path:
        with open(json_path, "w") as fh:
            json.dump(shown, fh, indent=1, default=str)
        print(f"wrote {len(shown)} rows to {json_path}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--generation", type=int, default=None)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    asyncio.run(main(args.generation, args.top, args.csv, args.json))