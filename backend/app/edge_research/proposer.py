"""Evidence-driven choice of the NEXT research experiment. Never runs or deploys anything by itself.

Order of reasoning:
  1. A PROMISING / OOS-POSITIVE result that is not yet ROBUST -> replicate it on NEW data first (the most valuable
     thing to learn is whether a positive result is real).
  2. Otherwise walk the hypothesis library in prior order. Skip any hypothesis the registry refuses (already tested /
     materially equivalent failure). For the first one left: if its data requirement is met -> RUN it; if not -> the
     next experiment is to COLLECT that data (with the exact shortfall).
The library is deliberately short and ordered by how much NEW information each hypothesis brings: candle-only
signals have been exhausted (see seeds), so information the system does not yet use comes first.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.edge_research.registry import ExperimentRegistry, ExperimentSpec

MICRO_FEATURES = ("bbo_imbalance", "microprice_offset_bps", "trade_flow_imb_10s", "trade_flow_imb_60s",
                  "sol_mid_ret_10s", "sol_mid_ret_60s")


@dataclass(frozen=True)
class Hypothesis:
    key: str
    spec: ExperimentSpec
    data: str                 # "microstructure" | "candles_btc" | "shadow"
    min_days: float
    why: str


LIBRARY = (
    Hypothesis("H1-MICRO-1M", ExperimentSpec(
        "Order-book imbalance, microprice and aggressor trade flow predict SOL's mid over the next minute by more than cost",
        "bar:microstructure", MICRO_FEATURES, "fwd_mid_return_bps", 1, "ridge", hyperparameters={"alpha": 10.0, "cost_margin_bps": 1.0}),
        "microstructure", 7.0, "Information the system has never used; the forensic audit's #1 recommendation."),
    Hypothesis("H2-MICRO-5M", ExperimentSpec(
        "Same microstructure features at a 5-minute horizon (larger moves vs fixed cost)",
        "bar:microstructure", MICRO_FEATURES, "fwd_mid_return_bps", 5, "ridge", hyperparameters={"alpha": 10.0, "cost_margin_bps": 1.0}),
        "microstructure", 7.0, "Same information, horizon where typical moves exceed the ~13 bps cost more often."),
    Hypothesis("H3-BTC-LEAD-SEC", ExperimentSpec(
        "BTC's last 10-60 s mid move (not yet in SOL) predicts SOL's next minute",
        "bar:microstructure", ("btc_mid_ret_10s", "btc_mid_ret_60s", "sol_mid_ret_10s", "sol_mid_ret_60s"),
        "fwd_mid_return_bps", 1, "ridge", hyperparameters={"alpha": 10.0, "cost_margin_bps": 1.0}),
        "microstructure", 7.0, "The 1-minute lead-lag test found a real but intra-minute effect; seconds-level data is needed."),
    Hypothesis("H4-CANDLE-BTC-RIDGE", ExperimentSpec(
        "Cost-aware ridge on SOL+BTC 1m returns and volatility at 5 min",
        "bar:candles+btc", ("btc_ret_1", "btc_ret_5", "btc_resid_1", "sol_ret_1", "sol_ret_5", "sol_vol_60"),
        "fwd_return_bps", 5, "ridge", hyperparameters={"alpha": 10.0, "cost_margin_bps": 1.0}),
        "candles_btc", 4.0, "Cheapest test of whether a cost-aware target extracts anything from public 1m bars incl. BTC."),
)


def propose(registry: ExperimentRegistry, *, data_days: dict[str, float]) -> dict:
    """data_days: {"microstructure": days covered, "candles_btc": days, "shadow": days}."""
    recs = registry.all()
    open_positive = [r for r in recs if r.get("decision") in ("PROMISING",) and not r.get("seed")]
    if open_positive:
        best = max(open_positive, key=lambda r: r.get("oos_net_expectancy_bps") or -1e9)
        return dict(action="REPLICATE", experiment=best.get("experiment_id"), hypothesis=best.get("hypothesis"),
                    why="A positive OOS result is only evidence once it repeats on data it has never seen. Re-run the SAME "
                        f"spec when >= 3 new days exist (registry allows exact replication on new data).", skipped=[])
    skipped = []
    for h in LIBRARY:
        chk = registry.check(h.spec, data_end_ms=None)
        if not chk.allowed:
            skipped.append({"hypothesis": h.key, "reason": chk.message[:300]})
            continue
        have = data_days.get(h.data, 0.0)
        if have < h.min_days:
            return dict(action="COLLECT_DATA", hypothesis=h.key, spec=h.spec.canonical(),
                        why=f"{h.why} Needs >= {h.min_days:g} days of {h.data} data for >= 4 independent OOS windows; "
                            f"have {have:.2f} days ({h.min_days - have:.2f} short).", skipped=skipped)
        return dict(action="RUN", hypothesis=h.key, spec=h.spec.canonical(), why=h.why, skipped=skipped)
    return dict(action="STOP", why="Every hypothesis in the library has been tested or refused. No deployable edge found; "
                                   "new information sources are required before more research is worthwhile.", skipped=skipped)
