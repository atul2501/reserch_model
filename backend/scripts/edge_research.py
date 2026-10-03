"""Edge-research CLI. Nothing here trades, deploys or touches agents/evolution.

    python -m scripts.edge_research seed                 install the prior research into the registry (idempotent)
    python -m scripts.edge_research propose              what is the next best experiment, and why
    python -m scripts.edge_research run H1-MICRO-1M [--justify "..."] [--window-days 1 1 2]
    python -m scripts.edge_research list

Costs: measured from the paper trades in the database (falls back to the configured fee schedule, and says so).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.core.config import BACKEND_DIR, get_settings
from app.edge_research.datasets import bar_dataset, coverage, load_bbo, microstructure_dataset
from app.edge_research.experiments import ExperimentData, run_experiment
from app.edge_research.proposer import LIBRARY, propose
from app.edge_research.registry import ExperimentRegistry
from app.edge_research.seeds import install_seeds
from app.pretrade.dataset import measured_costs


def _micro_dir() -> Path:
    p = Path(get_settings().microstructure_dir)
    return p if p.is_absolute() else BACKEND_DIR / p


async def _costs():
    s = get_settings()
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.trading import Trade
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Trade.entry_price, Trade.quantity, Trade.fees, Trade.slippage_cost)
                                     .where(Trade.exit_reason != "generation_rollover").order_by(Trade.closed_at.desc()).limit(5000))).all()
        trades = pd.DataFrame(rows, columns=["entry_price", "quantity", "fees", "slippage_cost"])
    except Exception as exc:  # noqa: BLE001 - research CLI may run without the trading DB
        print(f"(cost: no database ({type(exc).__name__}); using the configured fee schedule)")
        trades = None
    return measured_costs(trades, taker_fee=s.paper_fee_rate, slippage_bps_per_side=s.paper_slippage_bps)


def _minute_bars(bbo: pd.DataFrame) -> pd.DataFrame:
    """1m bars from real BBO mids: close = last mid with ts <= minute end (causal)."""
    m = bbo.assign(mid=(bbo.bid + bbo.ask) / 2, open_time=(bbo.ts // 60_000) * 60_000)
    g = m.groupby("open_time").mid
    return pd.DataFrame({"open_time": g.last().index, "close": g.last().to_numpy(), "open": g.first().to_numpy()})


def data_days() -> dict:
    cov = coverage(_micro_dir()) if _micro_dir().exists() else {}
    micro = min(cov.get("SOL:bbo", 0), cov.get("SOL:trades", 0)) / 24.0
    return {"microstructure": micro, "candles_btc": cov.get("BTC:bbo", 0) / 24.0, "shadow": 0.0}


async def cmd_run(key: str, justification: str | None, window_days: tuple[float, float, float]) -> dict:
    h = {x.key: x for x in LIBRARY}[key]
    costs = await _costs()
    if h.data == "microstructure":
        df = microstructure_dataset(_micro_dir(), horizons_min=(h.spec.horizon_min,))
        kind, note = "bar", "15 s decision grid from collected BBO/trades; outcome = first real mid at/after t+h"
    elif h.data == "candles_btc":
        sol, btc = _minute_bars(load_bbo(_micro_dir(), "SOL")), _minute_bars(load_bbo(_micro_dir(), "BTC"))
        df = bar_dataset(sol, btc)
        kind, note = "bar", "1m bars from collected BBO mids"
    else:
        raise SystemExit(f"no dataset builder for {h.data}")
    if df.empty:
        return {"refused": False, "status": "NO DATA", "message": f"no {h.data} data collected yet"}
    data = ExperimentData(df=df, kind=kind, cost_bps=costs.total_bps, cost_source=costs.source, note=note)
    return run_experiment(h.spec, data, ExperimentRegistry(), justification=justification, window_days=window_days)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed"); sub.add_parser("propose"); sub.add_parser("list")
    r = sub.add_parser("run"); r.add_argument("key"); r.add_argument("--justify"); r.add_argument("--window-days", nargs=3, type=float, default=(1.0, 1.0, 2.0))
    a = ap.parse_args()
    reg = ExperimentRegistry()
    if a.cmd == "seed":
        print(f"seeded {install_seeds(reg)} prior experiments into {reg.path}")
    elif a.cmd == "propose":
        print(json.dumps(propose(reg, data_days=data_days()), indent=2, default=str))
    elif a.cmd == "list":
        for x in reg.all():
            print(f"{x['experiment_id']:<34} {x['status']:<16} {x['decision']:<20} net={x.get('oos_net_expectancy_bps')}  {x['hypothesis'][:70]}")
    else:
        out = asyncio.run(cmd_run(a.key, a.justify, tuple(a.window_days)))
        print(json.dumps({k: v for k, v in out.items() if k not in ("windows", "oos_pooled", "previous")}, indent=2, default=str))


if __name__ == "__main__":
    main()
