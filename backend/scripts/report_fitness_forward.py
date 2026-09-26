"""READ-ONLY fitness -> future-performance report (Reports F and H).

    python -m scripts.report_fitness_forward
    python -m scripts.report_fitness_forward --horizon 360 --csv ff.csv --json ff.json

For every fitness snapshot cohort (as_of x horizon): correlation between fitness
at T and STRICTLY later realized performance, top-K lift, rank stability, with
explicit coverage/censoring disclosure. A cohort with too little future data is
reported as INSUFFICIENT — never silently extrapolated.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import defaultdict

import numpy as np
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.analytics import FitnessForwardPerformance

TOP_KS = (10, 25, 50, 100)
MIN_COHORT_AGENTS = 30          # below this the correlation is not reported
MIN_COHORT_TRADED = 10          # agents with >= 1 future trade


def _pearson(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    if len(x) < 3:
        return None, None
    r = float(np.corrcoef(np.asarray(x), np.asarray(y))[0, 1])
    if r != r:  # NaN (zero variance)
        return None, None
    n = len(x)
    from scipy import stats as sps

    t = r * ((n - 2) / (1 - r * r)) ** 0.5 if abs(r) < 1 else float("inf")
    p = 2 * sps.t.sf(abs(t), df=n - 2) if t == t else 0.0
    return r, p


def _spearman(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    if len(x) < 3:
        return None, None
    from scipy import stats as sps

    res = sps.spearmanr(x, y)
    r = float(res.statistic)
    if r != r:
        return None, None
    return r, float(res.pvalue)


def _ranks(vals: list[float]) -> list[float]:
    """Average ranks (ties share the mean rank) — deterministic."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def cohort_stats(rows: list[dict]) -> dict:
    """One cohort (as_of, horizon): the study's statistics, over flattened rows."""
    n = len(rows)
    traded = [r for r in rows if r["future_trade_count"] and r["future_trade_count"] > 0]
    out: dict = {
        "as_of": rows[0]["as_of"] if rows else None,
        "horizon_minutes": rows[0]["horizon_minutes"] if rows else None,
        "agents": n,
        "agents_with_future_trades": len(traded),
        "mean_coverage": (sum(r["window_coverage"] for r in rows) / n) if n else None,
        "censored": {k: sum(1 for r in rows if r["censor_reason"] == k)
                     for k in sorted({r["censor_reason"] for r in rows})},
        "insufficient": n < MIN_COHORT_AGENTS or len(traded) < MIN_COHORT_TRADED,
    }
    if out["insufficient"] or not traded:
        return out

    f = [r["fitness_at_t"] for r in traded]
    e = [r["future_expectancy"] for r in traded]
    b = [r["future_net_bps"] for r in traded]
    pr, pp = _pearson(f, e)
    sr_, sp = _spearman(f, e)
    pr_b, pp_b = _pearson(f, b)
    rank_f = _ranks(f)
    rank_e = _ranks(e)
    rr, rp = _pearson(rank_f, rank_e)
    pop_mean = float(np.mean(e))

    out.update({
        "pearson_expectancy": pr, "pearson_p": pp,
        "spearman_expectancy": sr_, "spearman_p": sp,
        "pearson_net_bps": pr_b, "pearson_net_bps_p": pp_b,
        "rank_stability": rr,
        "population_mean_future_expectancy": pop_mean,
        "top_k": {},
        "bottom_quartile": {},
    })
    order = sorted(traded, key=lambda r: -r["fitness_at_t"])
    for k in TOP_KS:
        if k > len(order):
            continue
        top = order[:k]
        bottom = order[-k:]
        top_mean = float(np.mean([r["future_expectancy"] for r in top]))
        out["top_k"][k] = {
            "mean_future_expectancy": top_mean,
            "lift_vs_population": (top_mean / pop_mean if pop_mean else None),
            "share_future_positive": float(np.mean([r["future_expectancy"] > 0 for r in top])),
            "mean_future_trades": float(np.mean([r["future_trade_count"] for r in top])),
        }
        out["bottom_quartile"][k] = {
            "mean_future_expectancy": float(np.mean([r["future_expectancy"] for r in bottom])),
            "share_future_positive": float(np.mean([r["future_expectancy"] > 0 for r in bottom])),
        }
    return out


def render(stats: list[dict]) -> str:
    out = ["fitness -> future performance (look-ahead-safe: fitness at T from trades closed <= T only)"]
    out.append("cohort = one (snapshot time, horizon); rows only for agents that traded")
    # full detail for cohorts with a population-wide sample; count-only for tiny/legacy ones
    big = [s for s in stats if s["agents"] >= MIN_COHORT_AGENTS]
    small = [s for s in stats if s["agents"] < MIN_COHORT_AGENTS]
    for s in big:
        out.append("")
        out.append(f"--- T={s['as_of']}  +{s['horizon_minutes']}m ---")
        coverage = "-" if s["mean_coverage"] is None else f"{s['mean_coverage']:.2f}"
        out.append(f"  agents={s['agents']} with_future_trades={s['agents_with_future_trades']}"
                   f" mean_coverage={coverage}")
        out.append(f"  censored: {s['censored']}")
        if s["insufficient"]:
            out.append("  INSUFFICIENT DATA: correlations and top-K are not reported for this cohort")
            continue
        out.append(f"  Pearson (fitness, future expectancy): {s['pearson_expectancy']:+.3f} (p={s['pearson_p']:.3g})")
        out.append(f"  Spearman:                             {s['spearman_expectancy']:+.3f} (p={s['spearman_p']:.3g})")
        out.append(f"  Pearson (fitness, future net bps):    {s['pearson_net_bps']:+.3f} (p={s['pearson_net_bps_p']:.3g})")
        out.append(f"  rank stability:                       {s['rank_stability']:+.3f}")
        out.append(f"  population mean future expectancy:     {s['population_mean_future_expectancy']:+.4f}")
        for k, v in s["top_k"].items():
            lift = "-" if v["lift_vs_population"] is None else f"{v['lift_vs_population']:+.2f}x"
            out.append(f"  top-{k:<4} future E[x]={v['mean_future_expectancy']:+.4f} (lift {lift},"
                       f" {100 * v['share_future_positive']:.0f}% positive)")
        for k, v in s["bottom_quartile"].items():
            out.append(f"  bottom-{k:<4} future E[x]={v['mean_future_expectancy']:+.4f}"
                       f" ({100 * v['share_future_positive']:.0f}% positive)")
    if small:
        out.append("")
        out.append(f"({len(small)} further cohorts with < {MIN_COHORT_AGENTS} agents exist (early per-trade anchors /"
                   " legacy grid points); too small for correlation statistics — see the CSV/JSON export for every row)")
    return "\n".join(out)


COLUMNS = ["as_of", "horizon_minutes", "agent_id", "source", "fitness_at_t", "future_trade_count",
           "future_net_pnl", "future_net_bps", "future_expectancy", "future_win_rate",
           "future_max_drawdown_currency", "censor_reason", "window_coverage"]


def _flat(r: FitnessForwardPerformance) -> dict:
    return {
        "as_of": r.as_of.isoformat(), "horizon_minutes": r.horizon_minutes, "agent_id": str(r.agent_id),
        "source": r.snapshot_source, "fitness_at_t": r.fitness_at_t,
        "future_trade_count": r.future_trade_count, "future_net_pnl": r.future_net_pnl,
        "future_net_bps": r.future_net_bps, "future_expectancy": r.future_expectancy,
        "future_win_rate": r.future_win_rate, "future_max_drawdown_currency": r.future_max_drawdown_currency,
        "censor_reason": r.censor_reason, "window_coverage": r.window_coverage,
    }


async def main(horizon: int | None, csv_path: str | None, json_path: str | None) -> None:
    async with AsyncSessionLocal() as db:
        stmt = select(FitnessForwardPerformance).order_by(FitnessForwardPerformance.as_of, FitnessForwardPerformance.horizon_minutes)
        if horizon:
            stmt = stmt.where(FitnessForwardPerformance.horizon_minutes == horizon)
        rows = (await db.execute(stmt)).scalars().all()
        # read-only by construction; flatten INSIDE the session (rollback expires the ORM instances)
        flat_rows = [_flat(r) for r in rows]
        await db.rollback()
    rows = flat_rows
    if not rows:
        print("no fitness_forward rows — run: python -m scripts.refresh_analytics --only fitness_forward")
        await engine.dispose()
        return
    cohorts: dict[tuple, list] = defaultdict(list)
    for r in rows:
        cohorts[(r["as_of"], r["horizon_minutes"])].append(r)
    stats = [cohort_stats(c) for c in cohorts.values()]
    print(render(stats))
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {len(rows)} rows to {csv_path}")
    if json_path:
        with open(json_path, "w") as fh:
            json.dump({"cohorts": stats, "rows": rows}, fh, indent=1, default=str)
        print(f"wrote {len(rows)} rows to {json_path}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--horizon", type=int, default=None, choices=[60, 360, 1440, 4320])
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    asyncio.run(main(args.horizon, args.csv, args.json))