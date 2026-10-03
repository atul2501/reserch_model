"""Phase 2 shared helpers. Research only — reads parquet extracts of the restored backup.

Unit of analysis: a SIGNAL = unique (signal_bar, family, side). Hundreds of agents fire the same
family on the same bar; collapsing them removes the duplicate-agent inflation. Entry is the OPEN of
the bar after the signal bar (production PAPER_FILL_TIMING=next_open). Forward returns are measured
at mid/bar prices (frictionless); costs are subtracted explicitly per scenario.
"""
import os
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

D = os.environ.get("P2_DATA", os.path.join(os.path.dirname(__file__), "..", "entry_quality_2026-10-02", "data"))
OUT = os.path.dirname(os.path.abspath(__file__))
HORIZONS = [1, 3, 5, 10, 15, 30, 60]
BAR = 60_000
T = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)

# Round-trip cost scenarios in bps (entry + exit, fees + slippage). Sensitivity only.
COSTS = {
    "S1_current": 13.5,        # measured: fees 8.67 + slippage 4.81 on real fills
    "S2_lower_slippage": 11.0,  # taker 4.5x2 fees + 1 bp slippage per side
    "S3_maker_both": 3.0,      # maker 1.5x2, zero slippage (assumes passive fills, ignores adverse selection)
    "S4_zero_slippage": 9.0,   # taker fees only
    "S5_zero_fee": 4.8,        # slippage only
    "S6_plausible_maker": 8.0,  # maker entry 1.5 + taker exit 4.5 + 2 bp exit slippage
    "S0_frictionless": 0.0,
}

# Walk-forward folds on signal-bar time; 1h embargo (max horizon 60m) between val and OOS.
FOLDS = {
    "F1": (T("2026-09-27 08:00"), T("2026-09-28 20:00"), T("2026-09-29 20:00"), T("2026-09-30 20:00")),
    "F2": (T("2026-09-27 08:00"), T("2026-09-29 20:00"), T("2026-09-30 20:00"), T("2026-10-01 20:00")),
    "F3": (T("2026-09-27 08:00"), T("2026-09-30 20:00"), T("2026-10-01 20:00"), T("2026-10-02 16:30")),
}
EMBARGO = 3600_000


def fold_parts(df, fold, col="bar"):
    s, a, b, c = FOLDS[fold]
    tr = df[(df[col] >= s) & (df[col] < a - EMBARGO)]
    va = df[(df[col] >= a) & (df[col] < b - EMBARGO)]
    oo = df[(df[col] >= b) & (df[col] < c - EMBARGO if fold != "F3" else df[col] < c)]
    return tr, va, oo


def candles():
    c = pd.read_parquet(f"{D}/candles.parquet")
    return c[c.is_final].sort_values("open_time").reset_index(drop=True)


def path_arrays(c):
    """For each entry index e and horizon h: close at e+h-1, max high / min low over [e, e+h-1],
    argmax/argmin (bars to MFE/MAE). Entry price = open[e]."""
    o, h, l, cl = (c[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n, H = len(c), max(HORIZONS)
    pad = lambda x, v: np.concatenate([x, np.full(H, v)])
    hw = sliding_window_view(pad(h, np.nan), H)[:n]
    lw = sliding_window_view(pad(l, np.nan), H)[:n]
    cw = sliding_window_view(pad(cl, np.nan), H)[:n]
    return o, hw, lw, cw


def add_forward(sig, c, idx_of_bar):
    """Adds per-horizon signed fwd return, MFE, MAE, bars-to-MFE/MAE (bps, frictionless) to `sig`
    (needs columns bar, side). Signals whose entry bar or window is beyond the data get NaN."""
    o, hw, lw, cw = path_arrays(c)
    e = sig.bar.map(idx_of_bar).to_numpy() + 1
    ok = (e >= 1) & (e < len(c))
    e = np.where(ok, e, 0)
    sgn = np.where(sig.side.to_numpy() == "LONG", 1.0, -1.0)
    p0 = o[e]
    for hz in HORIZONS:
        hh, ll, cc = hw[e, :hz], lw[e, :hz], cw[e, hz - 1]
        up = (np.nanmax(hh, axis=1) / p0 - 1) * 1e4
        dn = (np.nanmin(ll, axis=1) / p0 - 1) * 1e4
        complete = ok & ~np.isnan(hh).any(axis=1)
        fwd = (cc / p0 - 1) * 1e4 * sgn
        sig[f"fwd_{hz}"] = np.where(complete, fwd, np.nan)
        sig[f"mfe_{hz}"] = np.where(complete, np.where(sgn > 0, up, -dn), np.nan)
        sig[f"mae_{hz}"] = np.where(complete, np.where(sgn > 0, dn, -up), np.nan)
        if hz == 60:
            fav = np.where(sgn[:, None] > 0, hh, -ll)
            adv = np.where(sgn[:, None] > 0, -ll, hh)
            sig["bars_to_mfe_60"] = np.where(complete, np.nanargmax(np.nan_to_num(fav, nan=-1e18), axis=1), np.nan)
            sig["bars_to_mae_60"] = np.where(complete, np.nanargmax(np.nan_to_num(adv, nan=-1e18), axis=1), np.nan)
    return sig


def cluster_t(x, groups):
    """Cluster-robust t-stat of the mean (clusters = groups, e.g. 2-hour blocks)."""
    x = np.asarray(x, float); g = np.asarray(groups)
    m = ~np.isnan(x); x, g = x[m], g[m]
    n = len(x)
    if n < 3:
        return np.nan, n, 0
    mu = x.mean()
    s = pd.Series(x - mu).groupby(g).sum().to_numpy()
    se = np.sqrt((s ** 2).sum()) / n
    return (mu / se if se > 0 else np.nan), n, len(s)


def econ(x_bps, order=None):
    """Trading economics of a vector of per-signal net bps (equal notional per signal)."""
    x = np.asarray(x_bps, float); x = x[~np.isnan(x)]
    if len(x) == 0:
        return dict(n=0)
    w, l = x[x > 0], x[x <= 0]
    aw, al = (w.mean() if len(w) else np.nan), (l.mean() if len(l) else np.nan)
    payoff = aw / -al if len(w) and len(l) and al < 0 else np.nan
    eq = np.cumsum(x)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    return dict(n=len(x), win_rate=len(w) / len(x), exp_bps=x.mean(), median_bps=np.median(x),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.nan, net_bps_sum=x.sum(), avg_win=aw, avg_loss=al,
                payoff=payoff, be_wr=1 / (1 + payoff) if payoff == payoff else np.nan, max_dd_bps=dd)


def block2h(bar):
    return np.asarray(bar) // (2 * 3600_000)
