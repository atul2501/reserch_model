"""READ-ONLY trade-quality report (Reports B, C, D): entry quality, exit quality, MFE/MAE.

    python -m scripts.report_trade_quality
    python -m scripts.report_trade_quality --by family --csv tq.csv --json tq.json

Distinguishes BAD SIGNAL vs BAD ENTRY TIMING vs BAD STOP vs BAD TAKE-PROFIT vs
EXECUTION vs TRANSACTION-COST problems via the trade_quality_class taxonomy,
and shows whether exits leave significant favourable movement unused
(left_on_table_r). Every aggregate carries its sample size.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter, defaultdict

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.analytics import TradeAnalytics
from app.models.trading import Trade

CLASS_EXPLANATIONS = {
    "TAKE_PROFIT_HIT": "plan worked: TP reached",
    "TRAILING_CAPTURED": "trailing stop locked a favourable move",
    "ROLLOVER": "force-closed at generation rollover (not a strategy decision)",
    "LIQUIDATED": "liquidated (margin exhausted)",
    "COST_EATEN": "BAD SIGNAL/TIMING? no: gross edge existed, costs ate it -> transaction-cost problem",
    "STOP_IMMEDIATE": "BAD SIGNAL or BAD ENTRY TIMING: went >= -0.8R before ever reaching +0.25R",
    "REVERSAL_AFTER_PROFIT": "BAD STOP/EXIT: reached >= +1R then gave it all back",
    "STOP_LOSS_OTHER": "stopped out (neither immediate nor reversal)",
    "SIGNAL_EXIT_WIN": "rule-based exit, net positive",
    "SIGNAL_EXIT_LOSS": "rule-based exit, net negative",
    "OTHER": "unclassified",
}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def getattr_r(r: dict, group: str):
    """Group value as a plain string ('SIDE.SHORT' enum repr -> 'SHORT', None -> '-')."""
    v = r.get(group)
    if v is None:
        return "-"
    return v.value if hasattr(v, "value") else v


def _mean(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(vals) -> float | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2


def render(rows: list[dict]) -> str:
    n = len(rows)
    out = [f"trades analysed: {n}", ""]
    if not n:
        out.append("no trade_analytics rows — run: python -m scripts.refresh_analytics --only trade_analytics")
        return "\n".join(out)

    classes = Counter(r["klass"] for r in rows)
    out.append("=== D. TRADE-QUALITY CLASSIFICATION (every row: share of trades) ===")
    for k, c in classes.most_common():
        out.append(f"  {k:<22} {c:>5}  {_pct(c / n):>6}   {CLASS_EXPLANATIONS.get(k, '')}")
    out.append("")

    out.append("=== D. MFE / MAE DISTRIBUTIONS ===")
    mfe_r = [r["mfe_r"] for r in rows]
    mae_r = [r["mae_r"] for r in rows]
    lot = [r["left_on_table_r"] for r in rows]
    out.append(f"  MFE (R): mean={_mean(mfe_r):+.2f} median={_median(mfe_r):+.2f}  (n={sum(v is not None for v in mfe_r)})")
    out.append(f"  MAE (R): mean={_mean(mae_r):+.2f} median={_median(mae_r):+.2f}  (n={sum(v is not None for v in mae_r)})")
    out.append(f"  left-on-table (R, 30 bars post-exit): mean={_mean(lot):+.2f} median={_median(lot):+.2f}"
               f"  (n={sum(v is not None for v in lot)})")
    for group in ("family", "regime", "side", "agent"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[str(getattr_r(r, group))].append(r)
        out.append(f"  --- by {group} (top 12 by n) ---")
        for g, grows in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12]:
            gm = _mean(r["mfe_r"] for r in grows)
            ga = _mean(r["mae_r"] for r in grows)
            gl = _mean(r["left_on_table_r"] for r in grows)
            out.append(f"    {g:>24} n={len(grows):<4} MFE={gm:+.2f}R MAE={ga:+.2f}R left={gl:+.2f}R")
    out.append("")

    out.append("=== B. ENTRY QUALITY ===")
    slip = [r["entry_slippage_bps"] for r in rows]
    delay = [r["entry_delay_seconds"] for r in rows]
    out.append(f"  entry slippage bps: mean={_mean(slip):+.1f} (n={sum(v is not None for v in slip)})")
    out.append(f"  entry delay s:      mean={_mean(delay):+.2f} (n={sum(v is not None for v in delay)})")
    out.append(f"  MFE-before-MAE (>=+0.25R before -0.8R): True={sum(1 for r in rows if r['mfe_before_mae'] is True)}"
               f" False={sum(1 for r in rows if r['mfe_before_mae'] is False)}"
               f" n/a={sum(1 for r in rows if r['mfe_before_mae'] is None)}")
    out.append("")

    out.append("=== C. EXIT QUALITY (are exits leaving money on the table?) ===")
    by_reason: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_reason[r["exit_reason"]].append(r)
    for reason, rrows in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        gl = _mean(r["left_on_table_r"] for r in rrows)
        pm = _mean(r["post_exit_mfe_bps_30"] for r in rrows)
        out.append(f"  {reason:<20} n={len(rrows):<5} left_on_table={gl:+.2f}R  post-exit favourable={pm:+.1f}bps")
    big_left = [r for r in rows if (r["left_on_table_r"] or 0) >= 1.0]
    out.append(f"  trades leaving >= 1.0R on the table within 30 bars: {len(big_left)}"
               f" ({_pct(len(big_left) / n) if n else '0%'})")
    out.append("")
    out.append("=== data integrity (replay vs persisted extremes) ===")
    ok = sum(1 for r in rows if r["peak_x_ok"] is True and r["trough_x_ok"] is True)
    fail = sum(1 for r in rows if r["peak_x_ok"] is False or r["trough_x_ok"] is False)
    skipped = sum(1 for r in rows if r["peak_x_ok"] is None or r["trough_x_ok"] is None)
    out.append(f"  cross-check ok={ok} FAILED={fail} skipped={skipped} (failures are data-integrity findings)")
    return "\n".join(out)


COLUMNS = ["trade_id", "agent", "family", "strategy_version_id", "regime", "side", "klass", "exit_reason",
           "gross_pnl", "net_pnl", "mfe_r", "mae_r", "mfe_before_mae", "left_on_table_r",
           "entry_slippage_bps", "entry_delay_seconds", "exit_delay_seconds", "peak_x_ok", "trough_x_ok"]


def _flat(r: dict) -> dict:
    return {k: (str(v) if hasattr(v, "hex") else v) for k, v in r.items() if k in COLUMNS}


async def main(by: str, limit: int, csv_path: str | None, json_path: str | None) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(TradeAnalytics, Trade.exit_reason, Trade.gross_pnl, Trade.net_pnl)
                .join(Trade, Trade.id == TradeAnalytics.trade_id)
                .order_by(TradeAnalytics.computed_at.desc())
                .limit(limit)
            )
        ).all()
        # read-only by construction; flatten INSIDE the session (rollback expires the ORM instances)
        data = [
            {
                "trade_id": str(ta.trade_id), "agent": str(ta.agent_id), "family": ta.family,
                "strategy_version_id": str(ta.strategy_version_id) if ta.strategy_version_id else None,
                "regime": ta.regime, "side": ta.side, "klass": ta.trade_quality_class,
                "exit_reason": exit_reason, "gross_pnl": gross_pnl, "net_pnl": net_pnl,
                "mfe_r": ta.mfe_r, "mae_r": ta.mae_r, "mfe_before_mae": ta.mfe_before_mae,
                "left_on_table_r": ta.left_on_table_r, "entry_slippage_bps": ta.entry_slippage_bps,
                "entry_delay_seconds": ta.entry_delay_seconds, "exit_delay_seconds": ta.exit_delay_seconds,
                "post_exit_mfe_bps_30": ta.post_exit_mfe_bps_30, "peak_x_ok": ta.peak_crosscheck_ok,
                "trough_x_ok": ta.trough_crosscheck_ok,
            }
            for (ta, exit_reason, gross_pnl, net_pnl) in rows
        ]
        await db.rollback()
    print(f"trade quality report (n={len(data)}; grouped views show per-group sample sizes)")
    print(render(data))
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(_flat(r) for r in data)
        print(f"\nwrote {len(data)} rows to {csv_path}")
    if json_path:
        with open(json_path, "w") as fh:
            json.dump([_flat(r) | {"post_exit_mfe_bps_30": r["post_exit_mfe_bps_30"]} for r in data], fh,
                      indent=1, default=str)
        print(f"wrote {len(data)} rows to {json_path}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--by", choices=["family", "regime", "side", "agent"], default="family",
                    help="primary grouping shown in the MFE/MAE section")
    ap.add_argument("--limit", type=int, default=20000)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    asyncio.run(main(args.by, args.limit, args.csv, args.json))