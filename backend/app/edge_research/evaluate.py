"""Trading metrics and the objective profitability gate.

STATUS DEFINITIONS (all on pooled + per-window OUT-OF-SAMPLE trades, NET of measured costs)
  ROBUST OOS EDGE  every one of:
                     >= MIN_OOS_WINDOWS windows, each with >= MIN_TRADES_PER_WINDOW trades, >= MIN_INDEPENDENT_BARS bars;
                     pooled net expectancy > 0 AND its block-bootstrap 95% CI lower bound > 0;
                     multiple-testing-adjusted one-sided p < 0.05 (Bonferroni over every non-seed experiment run);
                     net profit factor >= 1.10;
                     >= 75% of windows net-positive and no single window > 50% of total net P&L;
                     stable: the neighbouring selection levels are also net-positive OOS.
  OOS POSITIVE     enough windows/trades, pooled net > 0, net PF > 1.0, >= 60% of windows positive (no CI/MT test).
  PROMISING        pooled OOS net > 0 but not enough windows/trades to judge.
  (insufficient evidence with OOS net <= 0 -> status NO EDGE but decision NEEDS_MORE_DATA: never rejected on too little data)
  WEAK EDGE        pooled OOS GROSS mean > 0 with clustered t >= 2, but NET <= 0: a real effect that costs consume.
  NO EDGE          anything else.
Decision mapping: ROBUST -> ACCEPTED_FOR_SHADOW; OOS POSITIVE -> PROMISING (must replicate on new data);
PROMISING -> NEEDS_MORE_DATA; WEAK EDGE -> REJECTED (does not survive costs); NO EDGE -> OOS_FAILED when validation
looked positive (overfit), else REJECTED.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Fewer independent 2-hour clusters than this -> no t-stat / CI (a t from 2 clusters is noise, not evidence).
MIN_CLUSTERS = 5

MIN_OOS_WINDOWS = 4
MIN_TRADES_PER_WINDOW = 30
MIN_INDEPENDENT_BARS = 200
ROBUST_PF = 1.10
ROBUST_WINDOW_SHARE = 0.75
POSITIVE_WINDOW_SHARE = 0.60
MAX_SINGLE_WINDOW_PNL_SHARE = 0.50
ALPHA = 0.05


def _clusters(t: np.ndarray) -> np.ndarray:
    return (np.asarray(t) // (2 * 3_600_000)).astype(np.int64)


def cluster_t(x: np.ndarray, t: np.ndarray) -> float | None:
    x = np.asarray(x, float); g = _clusters(t)
    m = np.isfinite(x); x, g = x[m], g[m]
    if len(x) < 3 or len(np.unique(g)) < MIN_CLUSTERS:
        return None
    s = pd.Series(x - x.mean()).groupby(g).sum().to_numpy()
    se = math.sqrt((s ** 2).sum()) / len(x)
    return float(x.mean() / se) if se > 0 else None


def bootstrap_ci(x: np.ndarray, t: np.ndarray, *, n: int = 2000, seed: int = 11) -> tuple[float | None, float | None]:
    x = np.asarray(x, float); g = _clusters(t)
    m = np.isfinite(x); x, g = x[m], g[m]
    u = np.unique(g)
    if len(u) < MIN_CLUSTERS:
        return None, None
    rng = np.random.default_rng(seed)
    idx = {k: np.where(g == k)[0] for k in u}
    means = np.array([x[np.concatenate([idx[k] for k in rng.choice(u, len(u))])].mean() for _ in range(n)])
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def one_sided_p_from_t(tstat: float | None) -> float | None:
    if tstat is None:
        return None
    return 0.5 * math.erfc(tstat / math.sqrt(2))      # P(Z >= t), normal approximation with clustered SE


def metrics(net_bps: np.ndarray, gross_bps: np.ndarray, t: np.ndarray, cost_bps: float) -> dict:
    net = np.asarray(net_bps, float); gross = np.asarray(gross_bps, float)
    if len(net) == 0:
        return dict(trades=0)
    wins, losses = net[net > 0], net[net <= 0]
    eq = np.cumsum(net)
    dd = float((np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq).max())
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    dsd = net[net < 0].std(ddof=1) if (net < 0).sum() > 1 else 0.0
    lo, hi = bootstrap_ci(net, t)
    tn = cluster_t(net, t)
    return dict(
        trades=int(len(net)), independent_bars=int(len(np.unique(t))), gross_expectancy_bps=float(gross.mean()),
        net_expectancy_bps=float(net.mean()), cost_per_trade_bps=float(cost_bps), win_rate=float((net > 0).mean()),
        profit_factor=float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        avg_winner_bps=float(wins.mean()) if len(wins) else None, avg_loser_bps=float(losses.mean()) if len(losses) else None,
        total_net_bps=float(net.sum()), max_drawdown_bps=dd,
        sharpe_per_trade=float(net.mean() / sd) if sd > 0 else None, sortino_per_trade=float(net.mean() / dsd) if dsd > 0 else None,
        t_stat_net=tn, t_stat_gross=cluster_t(gross, t), p_one_sided_net=one_sided_p_from_t(tn),
        net_ci95_low=lo, net_ci95_high=hi,
    )


def classify(windows: list[dict], pooled: dict, *, n_tests: int, neighbours_positive: bool | None,
             validation_net_bps: float | None, windows_available: int | None = None) -> tuple[str, str, list[str]]:
    """Returns (status, decision, reasons). `windows` = per-OOS-window metrics of windows that traded;
    `windows_available` = OOS windows the DATA provided (traded or not). Too little DATA (< MIN_OOS_WINDOWS windows) is
    never a rejection; ample data on which a hypothesis rarely fires and loses IS a rejection."""
    reasons = []
    nw = len(windows)
    avail = nw if windows_available is None else windows_available
    data_enough = avail >= MIN_OOS_WINDOWS
    enough = (data_enough and nw >= MIN_OOS_WINDOWS and all(w.get("trades", 0) >= MIN_TRADES_PER_WINDOW for w in windows)
              and (pooled.get("independent_bars") or 0) >= MIN_INDEPENDENT_BARS)
    if not enough:
        reasons.append(f"insufficient OOS evidence: {avail} windows available / {nw} traded (need {MIN_OOS_WINDOWS}), "
                       f"trades/window {[w.get('trades', 0) for w in windows]} (need {MIN_TRADES_PER_WINDOW}), "
                       f"bars {pooled.get('independent_bars')} (need {MIN_INDEPENDENT_BARS})")
    net = pooled.get("net_expectancy_bps")
    if net is None or pooled.get("trades", 0) == 0:
        if not data_enough:  # no evidence at all is never a rejection (it would block the hypothesis forever)
            return "NO EDGE", "NEEDS_MORE_DATA", reasons + ["no OOS trades: not enough data to evaluate"]
        return "NO EDGE", "REJECTED", reasons + ["no OOS trades: the hypothesis never fired out of sample on ample data"]
    pos_share = np.mean([w.get("net_expectancy_bps", -1) > 0 for w in windows]) if windows else 0.0
    totals = [w.get("total_net_bps", 0.0) for w in windows]
    pos_total = sum(v for v in totals if v > 0)
    single_share = (max(totals) / pos_total) if pos_total > 0 else 1.0
    p_adj = min(1.0, pooled["p_one_sided_net"] * max(1, n_tests)) if pooled.get("p_one_sided_net") is not None else None
    pf = pooled.get("profit_factor")
    if pf is None:                     # undefined PF = no losing trade at all -> infinite, not zero
        pf = math.inf if (pooled.get("win_rate") or 0) >= 1.0 else 0.0
    if (enough and net > 0 and (pooled.get("net_ci95_low") or -1) > 0 and p_adj is not None and p_adj < ALPHA
            and pf >= ROBUST_PF and pos_share >= ROBUST_WINDOW_SHARE and single_share <= MAX_SINGLE_WINDOW_PNL_SHARE
            and neighbours_positive):
        return "ROBUST OOS EDGE", "ACCEPTED_FOR_SHADOW", reasons + [f"adjusted p={p_adj:.4f} over {n_tests} tests"]
    if enough and net > 0 and pf > 1.0 and pos_share >= POSITIVE_WINDOW_SHARE:
        return "OOS POSITIVE", "PROMISING", reasons + [f"not robust: CI low {pooled.get('net_ci95_low')}, adjusted p {p_adj}, "
                                                       f"PF {pf:.2f}, windows positive {pos_share:.0%}, stable={neighbours_positive}"]
    if net > 0:
        return "PROMISING", "NEEDS_MORE_DATA", reasons + ["positive pooled OOS net but evidence insufficient/unstable"]
    if not data_enough:
        # A hypothesis is never REJECTED on too little DATA: that would block it forever in the registry.
        return "NO EDGE", "NEEDS_MORE_DATA", reasons + [f"OOS net {net:+.2f} bps on insufficient data - not a rejection"]
    tg = pooled.get("t_stat_gross")
    if (pooled.get("gross_expectancy_bps") or 0) > 0 and tg is not None and tg >= 2:
        return "WEAK EDGE", "REJECTED", reasons + [f"gross +{pooled['gross_expectancy_bps']:.2f} bps (t {tg:.2f}) is consumed by "
                                                   f"{pooled['cost_per_trade_bps']:.2f} bps of cost"]
    if validation_net_bps is not None and validation_net_bps > 0:
        return "NO EDGE", "OOS_FAILED", reasons + [f"validation net {validation_net_bps:+.2f} bps did not survive OOS ({net:+.2f})"]
    return "NO EDGE", "REJECTED", reasons + [f"OOS net {net:+.2f} bps"]
