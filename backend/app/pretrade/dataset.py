"""Shadow research dataset: one row per shadow candidate, enriched with what happened AFTER the decision.

Strict information boundary
  * Everything the gate used is in the raw record, written at decision time (app/pretrade/shadow.py).
  * Outcome columns are measured LATER from confirmed candles strictly after the decision:
      return_{h}m_bps = signed (close of bar K+h  /  entry observation - 1) * 1e4     h in 1,5,10,30,60
      mfe/mae_30m_bps = best/worst signed excursion of bars K+1..K+30 vs the entry observation (measurement only;
                        a high/low is never treated as a fill)
    A horizon whose bar has not closed yet is NULL ("partial horizon"), never estimated.
  * entry observation = the real best-bid/ask MID at the shadow execution point when available (entry_price_source
    = "l2_mid"); otherwise the signal-bar close ("signal_close"). The source is always recorded.

Costs are MEASURED, not hard-coded: `measured_costs()` derives fee and slippage bps from the paper trades the
existing path actually booked (falling back to the configured fee schedule only when no trades exist, and saying so).
Spread is the measured book spread, reported separately (paper's slippage model already represents crossing it, so it
is not added a second time).
"""
from __future__ import annotations

import glob
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Fewer independent 2-hour clusters than this -> no t-stat / CI (a t from 2 clusters is noise, not evidence).
MIN_CLUSTERS = 5

HORIZONS = (1, 5, 10, 30, 60)
BAR_MS = 60_000
DATASET_VERSION = "shadow_dataset_v1"

# The documented column contract of the exported dataset (PART 4). Raw-record columns are kept as well.
DATASET_COLUMNS = (
    "decision_id", "timestamp", "bar_time", "symbol", "agent_id", "generation", "strategy", "direction",
    "signal_strength", "regime", "entry_price", "entry_price_source", "gate_pass", "gate_reasons",
    "decision_age_ms", "price_drift_bps", "spread_bps", "estimated_cost_bps", "cost_source",
    "council_called", "council_direction", "council_confidence", "council_agrees", "council_age_ms",
    "paper_traded", "paper_direction", "paper_entry_price", "paper_exit_price", "paper_pnl", "paper_net_bps",
    *[f"return_{h}m_bps" for h in HORIZONS], "mfe_30m_bps", "mae_30m_bps",
    "fee_bps", "slippage_bps", *[f"net_return_{h}m_bps" for h in HORIZONS],
)


@dataclass(frozen=True)
class CostModel:
    fee_bps: float           # round trip, measured
    slippage_bps: float      # round trip, measured
    source: str              # "measured_paper_trades(n=...)" | "configured_fee_schedule(no paper trades)"
    n_trades: int

    @property
    def total_bps(self) -> float:
        return self.fee_bps + self.slippage_bps


def measured_costs(trades: pd.DataFrame | None, *, taker_fee: float, slippage_bps_per_side: float) -> CostModel:
    """Round-trip cost per unit notional from REAL paper fills (`fees`, `slippage_cost`, `entry_price*quantity`)."""
    if trades is not None and len(trades) > 0:
        notional = trades["entry_price"] * trades["quantity"]
        ok = notional > 0
        fee = float((trades.loc[ok, "fees"] / notional[ok]).mean() * 1e4)
        slip = float((trades.loc[ok, "slippage_cost"] / notional[ok]).mean() * 1e4)
        return CostModel(fee, slip, f"measured_paper_trades(n={int(ok.sum())})", int(ok.sum()))
    return CostModel(2 * taker_fee * 1e4, 2 * slippage_bps_per_side, "configured_fee_schedule(no paper trades)", 0)


_FILE_CACHE: dict[str, tuple[float, int, pd.DataFrame]] = {}


def load_records(directory: str | Path) -> pd.DataFrame:
    """All shadow JSONL records (every record_type). Parsed files are cached by (mtime, size): finished days are
    parsed once; only the file still being appended to is re-read."""
    frames = []
    for p in sorted(glob.glob(str(Path(directory) / "pretrade_shadow_*.jsonl"))):
        st = Path(p).stat()
        hit = _FILE_CACHE.get(p)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            frames.append(hit[2])
            continue
        with open(p, encoding="utf-8") as fh:
            df = pd.DataFrame([json.loads(line) for line in fh if line.strip()])
        _FILE_CACHE[p] = (st.st_mtime, st.st_size, df)
        frames.append(df)
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_dataset(records: pd.DataFrame, candles: pd.DataFrame, costs: CostModel,
                  paper: pd.DataFrame | None = None) -> pd.DataFrame:
    """records: raw shadow records; candles: confirmed 1m bars (open_time, open, high, low, close);
    paper: existing-path entries (agent_id, bar, side, entry_price, exit_price, net_pnl, notional) or None."""
    if records.empty or "record_type" not in records:
        return pd.DataFrame(columns=list(DATASET_COLUMNS))
    c = records[records.record_type == "candidate"].copy()
    if c.empty:
        return pd.DataFrame(columns=list(DATASET_COLUMNS))
    c = c.reset_index(drop=True)
    sign = np.where(c.direction == "LONG", 1.0, -1.0)
    mid = pd.to_numeric(c.get("price_at_shadow_execution_point"), errors="coerce")
    entry = mid.where(mid > 0, c.price_at_signal)
    out = pd.DataFrame({
        "decision_id": c.decision_id, "timestamp": c.decision_ms, "bar_time": c.signal_bar_open_time_ms,
        "symbol": "SOL", "agent_id": c.agent_id, "generation": c.generation, "strategy": c.strategy,
        "direction": c.direction, "signal_strength": c.get("setup_strength"), "regime": c.regime,
        "entry_price": entry, "entry_price_source": np.where(mid > 0, "l2_mid", "signal_close"),
        "gate_pass": c.gate_allowed.astype(bool), "gate_reasons": c.gate_rejection_reasons,
        "decision_age_ms": c.decision_age_ms, "price_drift_bps": c.signed_drift_bps, "spread_bps": c.spread_bps,
        "estimated_cost_bps": costs.total_bps, "cost_source": costs.source,
        "council_called": c.council_available.astype(bool), "council_direction": c.council_direction,
        "council_confidence": c.council_confidence, "council_agrees": c.llm_agrees, "council_age_ms": c.council_age_ms,
        "fee_bps": costs.fee_bps, "slippage_bps": costs.slippage_bps,
    })
    # keep the raw record's audit columns too (risk reasons, latencies, versions...)
    for col in ("risk_allowed", "risk_reasons", "position_state", "pending_order_state", "signal_created_ms",
                "validation_ms", "market_event_ms", "features_started_ms", "features_completed_ms", "information_cutoff_ms",
                "strategy_version_id", "feature_version", "pretrade_version", "llm_would_veto", "bid", "ask",
                "book_received_ms", "price_at_shadow_execution_point_ts_ms", "strategy_confidence"):
        if col in c:
            out[col] = c[col]

    # ---- outcomes from confirmed candles strictly after the signal bar
    cd = candles.sort_values("open_time").drop_duplicates("open_time")
    idx = pd.Series(np.arange(len(cd)), index=cd.open_time.astype("int64"))
    cl, hi, lo = cd.close.to_numpy(float), cd.high.to_numpy(float), cd.low.to_numpy(float)
    k = c.signal_bar_open_time_ms.astype("int64").map(idx)
    contiguous = cd.open_time.diff().fillna(BAR_MS).to_numpy()
    for h in HORIZONS:
        j = k + h
        okj = k.notna() & (j < len(cd))
        jj = j.where(okj, 0).astype(int).to_numpy()
        # the bar at K+h must be exactly h minutes after K (a gap would silently stretch the horizon)
        exact = okj.to_numpy() & (cd.open_time.to_numpy()[jj] == (c.signal_bar_open_time_ms.astype("int64") + h * BAR_MS).to_numpy())
        r = (cl[jj] / entry.to_numpy() - 1) * 1e4 * sign
        out[f"return_{h}m_bps"] = np.where(exact, r, np.nan)
        out[f"net_return_{h}m_bps"] = out[f"return_{h}m_bps"] - costs.total_bps
    # excursions over bars K+1..K+h (measurement only, never a fill) - vectorised forward rolling max/min
    ot = cd.open_time.to_numpy()
    sig_bar = c.signal_bar_open_time_ms.astype("int64").to_numpy()
    ent = entry.to_numpy(float)
    kk = k.to_numpy(dtype=float)
    hi_s, lo_s = pd.Series(hi[::-1]), pd.Series(lo[::-1])
    for h in HORIZONS:
        # fwd_max[i] = max(high[i+1 .. i+h]); computed on the reversed series, then shifted by one bar
        fmax = hi_s.rolling(h, min_periods=h).max().to_numpy()[::-1]
        fmin = lo_s.rolling(h, min_periods=h).min().to_numpy()[::-1]
        fmax = np.concatenate([fmax[1:], [np.nan]])
        fmin = np.concatenate([fmin[1:], [np.nan]])
        ok = np.isfinite(kk)
        ki = np.where(ok, kk, 0).astype(int)
        end = ki + h
        ok &= end < len(cd)
        ok &= np.where(ok, ot[np.minimum(end, len(cd) - 1)] == sig_bar + h * BAR_MS, False)   # no gaps inside
        up = (fmax[ki] / ent - 1) * 1e4
        dn = (fmin[ki] / ent - 1) * 1e4
        out[f"mfe_{h}m_bps"] = np.where(ok, np.where(sign > 0, up, -dn), np.nan)
        out[f"mae_{h}m_bps"] = np.where(ok, np.where(sign > 0, dn, -up), np.nan)

    # ---- the existing (paper) path on the same agent + bar
    out["paper_traded"] = False
    for col in ("paper_direction", "paper_entry_price", "paper_exit_price", "paper_pnl", "paper_net_bps",
                "paper_hold_s", "paper_fee_bps", "paper_slippage_bps"):
        out[col] = np.nan
    if paper is not None and len(paper):
        p = paper.rename(columns={"side": "paper_direction", "entry_price": "paper_entry_price",
                                  "exit_price": "paper_exit_price", "net_pnl": "paper_pnl"})
        notional = p["notional"] if "notional" in p else np.nan
        p = p.assign(paper_net_bps=p.paper_pnl / notional * 1e4,
                     paper_hold_s=p["holding_seconds"] if "holding_seconds" in p else np.nan,
                     paper_fee_bps=p["fees"] / notional * 1e4 if "fees" in p else np.nan,
                     paper_slippage_bps=p["slippage_cost"] / notional * 1e4 if "slippage_cost" in p else np.nan)
        cols = ["paper_direction", "paper_entry_price", "paper_exit_price", "paper_pnl", "paper_net_bps",
                "paper_hold_s", "paper_fee_bps", "paper_slippage_bps"]
        m = out[["agent_id", "bar_time"]].merge(p[["agent_id", "bar", *cols]].drop_duplicates(["agent_id", "bar"]),
                                                left_on=["agent_id", "bar_time"], right_on=["agent_id", "bar"], how="left")
        for col in cols:
            out[col] = m[col].to_numpy()
        out["paper_traded"] = m.paper_direction.notna().to_numpy()
    out.attrs["dataset_version"] = DATASET_VERSION
    return out


# --------------------------------------------------------------------------- statistics (shared with the dashboard)
def _clusters(bar_time: pd.Series) -> np.ndarray:
    return (bar_time.astype("int64") // (2 * 3600_000)).to_numpy()   # 2-hour blocks: correlated agents/bars


def cluster_t(x: np.ndarray, groups: np.ndarray) -> float | None:
    m = np.isfinite(x)
    x, g = x[m], groups[m]
    if len(x) < 3 or len(set(g)) < MIN_CLUSTERS:
        return None
    s = pd.Series(x - x.mean()).groupby(g).sum().to_numpy()
    se = math.sqrt((s ** 2).sum()) / len(x)
    return float(x.mean() / se) if se > 0 else None


def block_bootstrap_ci(x: np.ndarray, groups: np.ndarray, *, n: int = 1000, seed: int = 7, alpha: float = 0.05):
    m = np.isfinite(x)
    x, g = x[m], groups[m]
    u = np.unique(g)
    if len(u) < MIN_CLUSTERS:
        return None, None
    rng = np.random.default_rng(seed)
    idx = {k: np.where(g == k)[0] for k in u}
    means = [x[np.concatenate([idx[k] for k in rng.choice(u, len(u))])].mean() for _ in range(n)]
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def edge_stats(values: pd.Series, bar_time: pd.Series, *, cost_bps: float, min_n: int = 100, min_bars: int = 30) -> dict:
    """Gross and NET (after measured cost) economics of a vector of signed forward returns (bps)."""
    x = pd.to_numeric(values, errors="coerce").to_numpy(float)
    g = _clusters(bar_time)
    m = np.isfinite(x)
    n = int(m.sum())
    bars = int(pd.Series(bar_time[m]).nunique()) if n else 0
    warnings = []
    if n < min_n:
        warnings.append(f"INSUFFICIENT SAMPLE: only {n} observations (< {min_n})")
    if bars < min_bars:
        warnings.append(f"FEW INDEPENDENT BARS: {bars} distinct signal bars (< {min_bars})")
    nclust = len(set(g[m])) if n else 0
    if nclust < MIN_CLUSTERS:
        warnings.append(f"TOO FEW INDEPENDENT TIME BLOCKS: {nclust} two-hour blocks (< {MIN_CLUSTERS}) - no t-stat/CI")
    if n == 0:
        return dict(n=0, bars=0, warnings=warnings)
    gx, nx = x[m], x[m] - cost_bps
    wins, losses = nx[nx > 0], nx[nx <= 0]
    lo_ci, hi_ci = block_bootstrap_ci(nx, g[m])
    return dict(
        n=n, bars=bars, mean_gross_bps=float(gx.mean()), median_gross_bps=float(np.median(gx)),
        win_rate_gross=float((gx > 0).mean()), cost_bps=cost_bps, net_expectancy_bps=float(nx.mean()),
        win_rate_net=float((nx > 0).mean()),
        profit_factor_net=float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        avg_winner_net=float(wins.mean()) if len(wins) else None, avg_loser_net=float(losses.mean()) if len(losses) else None,
        t_stat_gross=cluster_t(gx, g[m]), t_stat_net=cluster_t(nx, g[m]),
        net_ci95_low=lo_ci, net_ci95_high=hi_ci, warnings=warnings,
    )
