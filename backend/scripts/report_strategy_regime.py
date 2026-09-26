"""READ-ONLY Strategy x Regime report (Reports A and G).

    python -m scripts.report_strategy_regime                       # family x regime, full window
    python -m scripts.report_strategy_regime --granularity version --window 24h --top 20
    python -m scripts.report_strategy_regime --csv matrix.csv --json matrix.json

Never ranks a strategy as "best" on insufficient data: every row carries its
sample size, episode count, evidence state and confidence interval, and cells
that are under-sampled are flagged as such.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.analytics import StrategyRegimeMatrix

COLUMNS = [
    "window", "granularity", "dim", "regime", "trades", "wins", "win_rate", "win_rate_ci95",
    "episodes", "evidence", "under_sampled", "net_pnl", "gross_pnl", "fees", "funding", "slippage",
    "expectancy", "expectancy_ci95", "profit_factor", "avg_winner", "avg_loser", "avg_hold_s",
    "max_dd", "mfe_r_mean", "mae_r_mean", "tp_first_pct", "sl_first_pct", "reversal_pct",
    "cost_eaten_pct", "gross_edge", "net_edge",
]


def _fmt_pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def _fmt(v: float | None, nd: int = 2, signed: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:+.{nd}f}" if signed else f"{v:.{nd}f}"


def render(rows: list[dict]) -> str:
    out: list[str] = []
    by_window: dict[str, list] = {}
    for r in rows:
        by_window.setdefault(r["window"], []).append(r)
    for window, wrows in by_window.items():
        out.append(f"=== window: {window} — cells: {len(wrows)} ===")
        out.append("hint: an edge is only claimed when its bootstrap CI excludes 0 AND the cell is not under-sampled")
        for r in sorted(wrows, key=lambda x: (x["granularity"], -(x["trades"] or 0), x["dim"], x["regime"])):
            ci = (f"[{_fmt(r['win_rate_ci95'][0], 2)}, {_fmt(r['win_rate_ci95'][1], 2)}]"
                  if r["win_rate_ci95"] and r["win_rate_ci95"][0] is not None else "n/a")
            eci = (f"[{_fmt(r['expectancy_ci95'][0], 3, True)}, {_fmt(r['expectancy_ci95'][1], 3, True)}]"
                   if r["expectancy_ci95"] and r["expectancy_ci95"][0] is not None else "n/a (needs >= 2 episodes)")
            dim = r["dim"]
            flag = " *UNDER-SAMPLED*" if r["under_sampled"] else ""
            out.append(
                f"{r['granularity']:>8} {dim:>24} x {r['regime']:<16} n={r['trades']:<4} "
                f"ep={r['episodes']:<3} {r['evidence']:<10}{flag}\n"
                f"{'':>10}win={_fmt_pct(r['win_rate'])} ci95={ci}  net={_fmt(r['net_pnl'], 2, True)} "
                f"gross={_fmt(r['gross_pnl'], 2, True)} costs(fees={_fmt(r['fees'], 2)}/fund={_fmt(r['funding'], 2)}"
                f"/slip={_fmt(r['slippage'], 2)})\n"
                f"{'':>10}E[x]={_fmt(r['expectancy'], 3, True)} ci95={eci}  PF={_fmt(r['profit_factor'], 2)} "
                f"MFE={_fmt(r['mfe_r_mean'], 2)}/MAE={_fmt(r['mae_r_mean'], 2)}R  "
                f"TPfirst={_fmt_pct(r['tp_first_pct'])} SLfirst={_fmt_pct(r['sl_first_pct'])} "
                f"rev={_fmt_pct(r['reversal_pct'])} cost={_fmt_pct(r['cost_eaten_pct'])} "
                f"edges(gross/net)={r['gross_edge']}/{r['net_edge']}"
            )
    return "\n".join(out)


def _flat(r: StrategyRegimeMatrix) -> dict:
    return {
        "window": r.window_key, "granularity": r.granularity, "dim": r.dim_label or r.dim_id,
        "regime": r.regime, "trades": r.trade_count, "wins": r.win_count, "win_rate": r.win_rate,
        "win_rate_ci95": [r.win_rate_ci_low, r.win_rate_ci_high], "episodes": r.episode_count,
        "evidence": r.evidence_state, "under_sampled": r.under_sampled, "net_pnl": r.net_pnl,
        "gross_pnl": r.gross_pnl, "fees": r.fees, "funding": r.funding, "slippage": r.slippage,
        "expectancy": r.expectancy, "expectancy_ci95": [r.expectancy_ci_low, r.expectancy_ci_high],
        "profit_factor": r.profit_factor, "avg_winner": r.avg_winner, "avg_loser": r.avg_loser,
        "avg_hold_s": r.avg_holding_seconds, "max_dd": r.max_drawdown_currency,
        "mfe_r_mean": r.mfe_r_mean, "mae_r_mean": r.mae_r_mean,
        "tp_first_pct": r.tp_first_pct, "sl_first_pct": r.sl_first_pct, "reversal_pct": r.reversal_pct,
        "cost_eaten_pct": r.cost_eaten_pct, "gross_edge": r.gross_edge, "net_edge": r.net_edge,
    }
async def main(granularity: str, window: str, top: int | None, csv_path: str | None, json_path: str | None) -> None:
    async with AsyncSessionLocal() as db:
        stmt = select(StrategyRegimeMatrix).where(StrategyRegimeMatrix.granularity == granularity)
        if window != "all":
            stmt = stmt.where(StrategyRegimeMatrix.window_key == window)
        rows = (await db.execute(stmt.order_by(StrategyRegimeMatrix.trade_count.desc()))).scalars().all()
        # read-only by construction; flatten INSIDE the session (rollback expires the ORM instances)
        flat_rows = [_flat(r) for r in rows]
        await db.rollback()
    rows = flat_rows
    if top:
        rows = rows[:top]
    if not rows:
        print("no matrix rows — run: python -m scripts.refresh_analytics --only matrix")
        await engine.dispose()
        return
    print(f"strategy x regime ({granularity}; sample sizes and intervals shown for every row)")
    print(render(rows))
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {len(rows)} rows to {csv_path}")
    if json_path:
        with open(json_path, "w") as fh:
            json.dump(rows, fh, indent=1, default=str)
        print(f"wrote {len(rows)} rows to {json_path}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--granularity", choices=["family", "version", "agent"], default="family")
    ap.add_argument("--window", choices=["full", "24h", "7d", "all"], default="full")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    asyncio.run(main(args.granularity, args.window, args.top, args.csv, args.json))