"""Export the pre-trade shadow dataset and summaries (read-only).

    python -m scripts.export_pretrade_shadow [--out ../reports/pretrade_shadow] [--horizon 10]

Writes: shadow_decisions.csv (one row per shadow candidate), shadow_summary.json, shadow_report.md (incl. the data
dictionary, so the files are self-contained for independent analysis), strategy_performance.csv,
regime_performance.csv, gate_rejections.csv, latency.csv, council_comparison.csv.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import BACKEND_DIR, get_settings
from app.core.database import AsyncSessionLocal
from app.pretrade.assemble import assemble
from app.pretrade.dataset import DATASET_COLUMNS, DATASET_VERSION, HORIZONS

DATA_DICTIONARY = {
    "decision_id": "agent_id:signal_bar_open_ms - unique per shadow candidate",
    "timestamp": "wall-clock ms when the shadow decision was created (UTC epoch ms)",
    "bar_time": "signal bar OPEN time (UTC epoch ms); its close (bar_time+60000) is the information cutoff",
    "symbol": "instrument", "agent_id": "agent (paper population)", "generation": "agent generation",
    "strategy": "strategy family of the agent's DNA", "direction": "LONG/SHORT signalled by the strategy",
    "signal_strength": "family setup strength (0..1) recorded by the strategy engine",
    "regime": "rule-based regime of the signal bar",
    "entry_price": "entry observation: real best bid/ask MID at the shadow execution point (entry_price_source=l2_mid), else signal-bar close",
    "gate_pass": "ExecutionGate verdict (would trade)", "gate_reasons": "JSON list of gate rejection reasons",
    "decision_age_ms": "validation time minus information cutoff", "price_drift_bps": "signed move from signal close to execution point (+ = in the trade's favour)",
    "spread_bps": "measured best ask-bid spread at the execution point (NULL if the book read failed)",
    "estimated_cost_bps": "round-trip fee+slippage MEASURED from the paper trades actually booked (see cost_source)",
    "council_called": "an LLM council snapshot existed at decision time", "council_direction": "its bias",
    "council_confidence": "its confidence", "council_agrees": "council direction == strategy direction",
    "council_age_ms": "decision time minus the council's information cutoff",
    "paper_traded": "the EXISTING paper path placed an entry for the same agent+bar", "paper_direction": "its side",
    "paper_entry_price": "its fill", "paper_exit_price": "its exit", "paper_pnl": "its realised net P&L (USD)",
    "paper_net_bps": "its realised net P&L per unit notional (bps)",
    **{f"return_{h}m_bps": f"signed (in `direction`) return from entry_price to the close of the bar {h} min after the signal bar; NULL until that bar closed" for h in HORIZONS},
    **{f"mfe_{h}m_bps": f"best signed excursion over the next {h} bars (high/low; measurement only, never a fill)" for h in HORIZONS},
    **{f"mae_{h}m_bps": f"worst signed excursion over the next {h} bars" for h in HORIZONS},
    "fee_bps": "measured round-trip fees (bps)", "slippage_bps": "measured round-trip slippage (bps)",
    **{f"net_return_{h}m_bps": f"return_{h}m_bps minus estimated_cost_bps" for h in HORIZONS},
}


def _flat(df: pd.DataFrame) -> pd.DataFrame:
    out = df.drop(columns=[c for c in df.columns if c.startswith("_")]).copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, (list, dict))).any():
            out[col] = out[col].map(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v)
    lead = [c for c in DATASET_COLUMNS if c in out.columns]
    return out[lead + [c for c in out.columns if c not in lead]]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BACKEND_DIR.parent / "reports" / "pretrade_shadow"))
    ap.add_argument("--horizon", type=int, default=10)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        records, dataset, costs, payload = await assemble(db, settings, horizon=a.horizon)
    _flat(dataset).to_csv(out / "shadow_decisions.csv", index=False)
    (out / "shadow_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(payload["F_strategy"]).to_csv(out / "strategy_performance.csv", index=False)
    pd.DataFrame(payload["G_regime"]).to_csv(out / "regime_performance.csv", index=False)
    pd.DataFrame(payload["B_opportunities"]["rejection_reasons"]).to_csv(out / "gate_rejections.csv", index=False)
    pd.DataFrame([{"stage": k, **v} for k, v in payload["K_latency"].items() if isinstance(v, dict)]).to_csv(out / "latency.csv", index=False)
    J = payload["J_llm"]
    pd.DataFrame([{"subset": k, **{kk: vv for kk, vv in J.get(k, {}).items() if kk != "warnings"}}
                  for k in ("quant_only", "llm_agree", "llm_disagree") if k in J]).to_csv(out / "council_comparison.csv", index=False)
    D = payload["D_gross_vs_net"]
    lines = [
        "# Pre-trade shadow export", "",
        f"Generated {datetime.now(timezone.utc).isoformat()} - dataset version `{DATASET_VERSION}` - "
        f"{len(dataset)} candidates over {payload['A_status']['shadow_bars']} shadow bars.", "",
        "**HYPOTHETICAL SHADOW DATA - NOT REAL P&L. Shadow never placed an order.**", "",
        f"Cost model: fee {costs.fee_bps:.2f} + slippage {costs.slippage_bps:.2f} = **{costs.total_bps:.2f} bps** round trip ({costs.source}).", "",
        f"Gate-pass, {D['horizon_min']} min: gross {D['gross_expected_move_bps']} bps -> **net {D['net_expected_move_bps']} bps** (n={D['n']}).", "",
        "Warnings: " + ("; ".join(payload["warnings"]) or "none"), "",
        "## Information boundary", "",
        "Every gate input was recorded at decision time. Outcome columns (return_*, mfe_*, mae_*) were measured afterwards "
        "from confirmed candles strictly after the signal bar and are NULL until the horizon has passed. High/low are "
        "never used as fill prices.", "",
        "## Data dictionary (shadow_decisions.csv)", "", "| column | meaning |", "|---|---|",
        *[f"| `{k}` | {v} |" for k, v in DATA_DICTIONARY.items()], "",
        "Additional audit columns (risk reasons, latency stamps, versions, bid/ask, book timestamps) follow the documented ones.",
    ]
    (out / "shadow_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "candidates": len(dataset), "cost_bps": costs.total_bps}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
