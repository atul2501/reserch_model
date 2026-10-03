"""Pre-trade shadow dashboard payload (sections A-M + daily). Pure functions over the shadow dataset.

Every statistic carries its sample size and warnings (insufficient sample, few independent bars, single window).
Nothing here estimates a number that was not measured: missing inputs produce None, never a default.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from app.pretrade.dataset import HORIZONS, CostModel, edge_stats

REJECTION_CATEGORIES = (
    "minimum_notional", "duplicate_position", "cooldown", "position_open", "pending_order", "stale",
    "price_drift", "spread", "risk", "regime", "conflict", "other",
)


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pct(s: pd.Series, q: float):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return _num(s.quantile(q)) if len(s) else None


def _dist(s) -> dict:
    if s is None or np.isscalar(s):          # column absent (e.g. no book data recorded) -> empty distribution
        s = pd.Series(dtype=float)
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    if not len(s):
        return dict(n=0, p50=None, p90=None, p95=None, p99=None, max=None)
    return dict(n=int(len(s)), p50=_num(s.quantile(.5)), p90=_num(s.quantile(.9)), p95=_num(s.quantile(.95)),
                p99=_num(s.quantile(.99)), max=_num(s.max()))


def categorize(reasons) -> set[str]:
    """Map raw gate/risk reason strings onto the dashboard's rejection categories."""
    out = set()
    for r in (reasons or []):
        r = str(r)
        if "below_min_order_notional" in r:
            out.add("minimum_notional")
        elif "duplicate_position" in r:
            out.add("duplicate_position")
        elif "cooldown" in r:
            out.add("cooldown")
        elif r == "position_already_open":
            out.add("position_open")
        elif r == "order_already_pending":
            out.add("pending_order")
        elif r in ("decision_too_old", "stale_signal_bar", "execution_before_information_cutoff"):
            out.add("stale")
        elif r == "price_moved_too_far":
            out.add("price_drift")
        elif r.startswith("spread"):
            out.add("spread")
        elif "regime" in r:
            out.add("regime")
        elif "conflict" in r:
            out.add("conflict")
        elif r.startswith("risk") or r in ("max_trades_per_day_reached",):
            out.add("risk")
        else:
            out.add("other")
    return out


def _as_list(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        return list(v)
    if isinstance(v, str) and v.startswith("["):
        import json
        try:
            return json.loads(v.replace("'", '"'))
        except ValueError:
            return [v]
    return [] if v is None or (isinstance(v, float) and math.isnan(v)) else [v]


def _edge(df: pd.DataFrame, h: int, cost: float) -> dict:
    return edge_stats(df[f"return_{h}m_bps"], df["bar_time"], cost_bps=cost) if len(df) else dict(n=0, warnings=["NO DATA"])


def _group_table(df: pd.DataFrame, key, h: int, cost: float) -> list[dict]:
    rows = []
    for k, g in df.groupby(key, dropna=False):
        e = _edge(g, h, cost)
        rows.append({
            "group": "UNKNOWN" if (k is None or (isinstance(k, float) and math.isnan(k))) else k, "signals": int(len(g)),
            "gate_pass_pct": _num(g.gate_pass.mean()), **{k2: v for k2, v in e.items()},
            "mfe_30m_bps": _num(pd.to_numeric(g.get("mfe_30m_bps"), errors="coerce").mean()),
            "mae_30m_bps": _num(pd.to_numeric(g.get("mae_30m_bps"), errors="coerce").mean()),
            "paper_hold_avg_s": _num(pd.to_numeric(g.get("paper_hold_s"), errors="coerce").mean()),
            "paper_hold_median_s": _num(pd.to_numeric(g.get("paper_hold_s"), errors="coerce").median()),
            "paper_fee_bps": _num(pd.to_numeric(g.get("paper_fee_bps"), errors="coerce").mean()),
            "paper_slippage_bps": _num(pd.to_numeric(g.get("paper_slippage_bps"), errors="coerce").mean()),
        })
    return sorted(rows, key=lambda r: -(r.get("signals") or 0))


def build_payload(*, records: pd.DataFrame, dataset: pd.DataFrame, costs: CostModel, settings_view: dict,
                  completed_cycles_ms: list[int] | None = None, horizon: int = 10, hour_group: int = 1,
                  now_ms: int | None = None) -> dict:
    now_ms = now_ms or time.time_ns() // 1_000_000
    h = horizon if horizon in HORIZONS else 10
    cost = costs.total_bps
    ds = dataset.copy()
    summ = records[records.record_type == "bar_summary"] if len(records) and "record_type" in records else pd.DataFrame()

    # ---------------- A. status
    first = _num(ds.timestamp.min()) if len(ds) else None
    last_dec = _num(ds.timestamp.max()) if len(ds) else None
    last_cycle = _num(summ.validation_ms.max()) if len(summ) and "validation_ms" in summ else None
    missed = None
    if completed_cycles_ms is not None and len(summ) and first:
        done = {int(t) for t in completed_cycles_ms if t >= summ.signal_bar_open_time_ms.min()}
        missed = len(done - set(summ.signal_bar_open_time_ms.astype("int64")))
    status = "NO DATA" if last_cycle is None else ("RUNNING" if now_ms - last_cycle < 3 * 60_000 else "STALE")
    A = dict(trading_mode=settings_view.get("trading_mode"), pretrade_mode=settings_view.get("pretrade_mode"),
             shadow_status=status, shadow_start_ms=first, shadow_duration_s=((now_ms - first) / 1000 if first else None),
             last_shadow_decision_ms=last_dec,
             last_market_timestamp_ms=(_num(ds.bar_time.max()) + 60_000) if len(ds) else None,
             last_successful_shadow_cycle_ms=last_cycle, shadow_bars=int(len(summ)),
             shadow_missed_cycles=missed,
             shadow_errors_note="missed cycles = worker cycles COMPLETED after shadow start with no shadow bar record")

    # ---------------- B. opportunities
    cats = {c: 0 for c in REJECTION_CATEGORIES}
    for gr, rr in zip(ds.get("gate_reasons", []), ds.get("risk_reasons", [None] * len(ds))):
        for c in categorize(_as_list(gr) + _as_list(rr)):
            cats[c] += 1
    n = len(ds)
    B = dict(total_candidates=n, would_trade=int(ds.gate_pass.sum()) if n else 0,
             would_reject=int((~ds.gate_pass).sum()) if n else 0,
             gate_pass_pct=_num(ds.gate_pass.mean()) if n else None,
             gate_reject_pct=_num((~ds.gate_pass).mean()) if n else None,
             rejection_reasons=[{"category": k, "count": v, "share_of_candidates": (v / n if n else None)} for k, v in cats.items()],
             note="a candidate can have several reasons; shares do not sum to 100%")

    # ---------------- C. signal edge
    groups = {"ALL SIGNALS": ds, "GATE-PASS": ds[ds.gate_pass] if n else ds, "GATE-REJECTED": ds[~ds.gate_pass] if n else ds,
              "LONG": ds[ds.direction == "LONG"] if n else ds, "SHORT": ds[ds.direction == "SHORT"] if n else ds}
    C = [{"group": g, "horizon_min": hz, **_edge(d, hz, cost)} for g, d in groups.items() for hz in HORIZONS]

    # ---------------- D. gross vs net (gate-pass, selected horizon)
    gp = groups["GATE-PASS"]
    gross = _num(pd.to_numeric(gp[f"return_{h}m_bps"], errors="coerce").mean()) if len(gp) else None
    D = dict(horizon_min=h, population="GATE-PASS", n=int(pd.to_numeric(gp.get(f"return_{h}m_bps"), errors="coerce").notna().sum()) if len(gp) else 0,
             gross_expected_move_bps=gross, fee_bps=-costs.fee_bps, slippage_bps=-costs.slippage_bps,
             spread_bps_measured=_num(pd.to_numeric(ds.get("spread_bps"), errors="coerce").median()) if n else None,
             spread_note="measured book spread, shown for reference; the paper slippage model already charges for crossing it",
             estimated_total_cost_bps=-cost, net_expected_move_bps=(gross - cost) if gross is not None else None,
             cost_source=costs.source)

    # ---------------- E. MFE / MAE
    def mm(d):
        return {f"{k}_{hz}m": _num(pd.to_numeric(d.get(f"{k}_{hz}m_bps"), errors="coerce").mean()) if len(d) else None
                for hz in HORIZONS for k in ("mfe", "mae")}
    E = {"ALL": mm(ds), "LONG": mm(groups["LONG"]), "SHORT": mm(groups["SHORT"]),
         "by_strategy": {k: mm(g) for k, g in ds.groupby("strategy")} if n else {},
         "by_regime": {k: mm(g) for k, g in ds.groupby("regime")} if n else {},
         "interpretation": "MFE >> |MAE| with near-zero forward return = good entry, bad exit; MFE ~ |MAE| = entry has no edge"}

    # ---------------- F/G/H/I
    F = _group_table(ds, "strategy", h, cost) if n else []
    G = _group_table(ds, "regime", h, cost) if n else []
    if n:
        hours = pd.to_datetime(ds.bar_time, unit="ms", utc=True).dt.hour
        ds["_hour_bucket"] = (hours // hour_group) * hour_group
    H = _group_table(ds, "_hour_bucket", h, cost) if n else []
    for r in H:
        r["warnings"] = list(r.get("warnings", [])) + ["DO NOT SELECT AN HOUR FROM THIS TABLE WITHOUT OOS CONFIRMATION"]
    I = _group_table(ds, "direction", h, cost) if n else []

    # ---------------- J. LLM council (non-authoritative)
    J = dict(n=n)
    if n:
        dirn = ds.council_direction.isin(["LONG", "SHORT"])
        agree = dirn & (ds.council_direction == ds.direction)
        disagree = dirn & (ds.council_direction != ds.direction)
        J.update(council_available_pct=_num(ds.council_called.mean()), agreement_pct_of_directional=_num(agree[dirn].mean()) if dirn.any() else None,
                 disagreement_pct_of_directional=_num(disagree[dirn].mean()) if dirn.any() else None,
                 council_confidence_mean=_num(pd.to_numeric(ds.council_confidence, errors="coerce").mean()),
                 council_age_ms=_dist(ds.council_age_ms),
                 quant_only=_edge(ds, h, cost), llm_agree=_edge(ds[agree], h, cost), llm_disagree=_edge(ds[disagree], h, cost))
        a, d = J["llm_agree"], J["llm_disagree"]
        if (a.get("n") or 0) < 100 or (d.get("n") or 0) < 100:
            J["llm_value"] = "INSUFFICIENT DATA"
        elif (a.get("net_ci95_low") is not None and d.get("net_ci95_high") is not None and a["net_ci95_low"] > d["net_ci95_high"]
              and a["net_expectancy_bps"] > J["quant_only"]["net_expectancy_bps"]):
            J["llm_value"] = "POSSIBLE (agree-subset beats disagree-subset outside both CIs) - shadow only, never execution"
        else:
            J["llm_value"] = "NONE"
    J["authority"] = "NONE: the LLM never authorises, vetoes or sizes anything"

    # ---------------- K. latency / freshness
    K = {}
    if len(summ):
        s = summ
        K = dict(bar_close_to_features=_dist(s.features_started_ms - s.market_event_ms),
                 features=_dist(s.features_completed_ms - s.features_started_ms),
                 features_to_signal=_dist(s.signal_created_ms - s.features_completed_ms),
                 signal_to_decision=_dist(s.decision_ms - s.signal_created_ms),
                 decision_to_book=_dist(s.validation_ms - s.decision_ms),
                 total_decision_latency=_dist(s.decision_ms - s.market_event_ms))
    if n:
        reasons = ds.gate_reasons.map(lambda v: _as_list(v))
        K.update(stale_pct=_num(reasons.map(lambda r: "decision_too_old" in r).mean()),
                 price_drift_abs_bps=_dist(pd.to_numeric(ds.price_drift_bps, errors="coerce").abs()),
                 spread_bps=_dist(ds.spread_bps),
                 book_timestamp_lag_ms=_dist(pd.to_numeric(ds.get("book_received_ms"), errors="coerce")
                                            - pd.to_numeric(ds.get("price_at_shadow_execution_point_ts_ms"), errors="coerce")))

    # ---------------- L. paper vs shadow
    L = {}
    if n:
        pt = ds[ds.paper_traded]
        pn = pd.to_numeric(pt.paper_net_bps, errors="coerce").dropna()
        L = dict(
            paper=dict(signals=n, trades=int(len(pt)), win_rate=_num((pn > 0).mean()) if len(pn) else None,
                       net_expectancy_bps=_num(pn.mean()) if len(pn) else None,
                       gross_expectancy_bps=_num((pn + pd.to_numeric(pt.paper_fee_bps, errors="coerce")).mean()) if len(pn) else None,
                       profit_factor=_num(pn[pn > 0].sum() / -pn[pn <= 0].sum()) if (pn <= 0).any() and len(pn) else None,
                       avg_winner_bps=_num(pn[pn > 0].mean()) if (pn > 0).any() else None,
                       avg_loser_bps=_num(pn[pn <= 0].mean()) if (pn <= 0).any() else None,
                       avg_hold_s=_num(pd.to_numeric(pt.paper_hold_s, errors="coerce").mean()),
                       fee_bps=_num(pd.to_numeric(pt.paper_fee_bps, errors="coerce").mean()),
                       slippage_bps=_num(pd.to_numeric(pt.paper_slippage_bps, errors="coerce").mean()),
                       note="realised paper P&L (closed trades only)"),
            shadow={**_edge(gp, h, cost), "trades": int(len(gp)), "mfe_30m_bps": _num(pd.to_numeric(gp.mfe_30m_bps, errors="coerce").mean()),
                    "mae_30m_bps": _num(pd.to_numeric(gp.mae_30m_bps, errors="coerce").mean()),
                    "note": f"HYPOTHETICAL: gate-pass candidates held {h} min at measured cost"},
            same_direction_pct=_num((pt.paper_direction == pt.direction).mean()) if len(pt) else None,
            paper_trade_and_shadow_pass_pct=_num((ds.paper_traded & ds.gate_pass).mean()),
            paper_trade_and_shadow_reject_pct=_num((ds.paper_traded & ~ds.gate_pass).mean()),
            shadow_pass_and_paper_no_trade_pct=_num((~ds.paper_traded & ds.gate_pass).mean()),
            note="observational only: shadow never authorises or vetoes a paper trade")

    # ---------------- M. hypothetical shadow equity
    M = dict(label="HYPOTHETICAL SHADOW - NOT REAL P&L", horizon_min=h, cost_bps=cost, points=[])
    if len(gp):
        e = gp[["timestamp", f"net_return_{h}m_bps"]].dropna().sort_values("timestamp")
        cum = e[f"net_return_{h}m_bps"].cumsum()
        step = max(1, len(e) // 500)
        M["points"] = [{"t": int(t), "cum_net_bps": _num(v)} for t, v in zip(e.timestamp.iloc[::step], cum.iloc[::step])]
        M["n_trades"] = int(len(e))
        M["method"] = "entry = real book mid at the shadow execution point; exit = confirmed bar close at the horizon; " \
                      "no high/low fills; one unit notional per candidate"

    # ---------------- daily (14-day run tracking)
    daily = []
    if n:
        ds["_day"] = pd.to_datetime(ds.bar_time, unit="ms", utc=True).dt.strftime("%Y-%m-%d")
        for day, g in ds.groupby("_day"):
            e = _edge(g[g.gate_pass], h, cost)
            daily.append(dict(day=day, signals=int(len(g)), gate_passes=int(g.gate_pass.sum()),
                              gross_expectancy_bps=e.get("mean_gross_bps"), net_expectancy_bps=e.get("net_expectancy_bps"),
                              cost_bps=cost, mfe_30m_bps=_num(pd.to_numeric(g.mfe_30m_bps, errors="coerce").mean()),
                              mae_30m_bps=_num(pd.to_numeric(g.mae_30m_bps, errors="coerce").mean())))
    warnings = []
    if len(daily) < 2:
        warnings.append("SINGLE WINDOW: fewer than 2 days of shadow data - no time-stability evidence")
    if n < 1000:
        warnings.append(f"SMALL DATASET: {n} candidates")
    return dict(selected_horizon_min=h, hour_group=hour_group, cost_model=dict(fee_bps=costs.fee_bps, slippage_bps=costs.slippage_bps,
                total_bps=cost, source=costs.source, n_trades=costs.n_trades),
                A_status=A, B_opportunities=B, C_signal_edge=C, D_gross_vs_net=D, E_mfe_mae=E, F_strategy=F,
                G_regime=G, H_time_of_day=H, I_long_short=I, J_llm=J, K_latency=K, L_paper_vs_shadow=L,
                M_equity=M, daily=daily, warnings=warnings)
