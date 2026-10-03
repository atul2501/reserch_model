"""Shared research helpers: loading with anomaly flags, trading metrics."""
import os
import numpy as np
import pandas as pd

D = os.path.join(os.path.dirname(__file__), "data")
END_TS = pd.Timestamp("2026-10-02 16:27:00", tz="UTC")  # last candle in backup


def load_trades():
    t = pd.read_parquet(f"{D}/trades.parquet")
    c = pd.read_parquet(f"{D}/candles.parquet").set_index("open_time")
    xb = (t.closed_at.astype("int64") // 10**6 // 60000) * 60000
    bar_close = xb.map(c.close)
    t["exit_dev_bps"] = (t.exit_price / bar_close - 1) * 1e4
    t["flag_stale_rollover"] = (t.exit_reason == "generation_rollover") & (
        (t.closed_at < t.opened_at) | (t.exit_dev_bps.abs() > 20))
    t["is_rollover"] = t.exit_reason == "generation_rollover"
    t["notional"] = t.entry_price * t.quantity
    t["net_bps"] = t.net_pnl / t.notional * 1e4
    t["gross_bps"] = t.gross_pnl / t.notional * 1e4
    t["fee_bps"] = t.fees / t.notional * 1e4
    t["net_r"] = t.net_pnl / t.risk_amount.where(t.risk_amount > 0)
    t["win"] = (t.net_pnl > 0).astype(int)
    t["signal_ts"] = pd.to_datetime(t.signal_bar_open_time_ms, unit="ms", utc=True)
    return t.sort_values("opened_at").reset_index(drop=True)


def max_dd(pnl_sorted):
    eq = np.cumsum(pnl_sorted)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return float((peak - eq).max()) if len(eq) else 0.0


def metrics(df, pnl="net_pnl"):
    n = len(df)
    if n == 0:
        return dict(trades=0)
    x = df[pnl].to_numpy()
    w, l = x[x > 0], x[x <= 0]
    gp, gl = w.sum(), -l.sum()
    aw = w.mean() if len(w) else np.nan
    al = l.mean() if len(l) else np.nan
    payoff = aw / abs(al) if len(w) and len(l) and al != 0 else np.nan
    order = df.sort_values("closed_at")[pnl].to_numpy()
    return dict(
        trades=n, wins=len(w), losses=len(l), win_rate=len(w) / n,
        gross_profit=gp, gross_loss=gl, net=x.sum(), pf=gp / gl if gl > 0 else np.nan,
        exp=x.mean(), avg_win=aw, avg_loss=al,
        med_win=np.median(w) if len(w) else np.nan, med_loss=np.median(l) if len(l) else np.nan,
        payoff=payoff, be_wr=1 / (1 + payoff) if payoff == payoff else np.nan,
        max_dd=max_dd(order),
        exp_bps=df.net_bps.mean() if "net_bps" in df else np.nan,
        gross_exp_bps=df.gross_bps.mean() if "gross_bps" in df else np.nan,
        fees=df.fees.sum() if "fees" in df else np.nan,
        funding=df.funding.sum() if "funding" in df else np.nan,
        hold_avg_min=df.holding_seconds.mean() / 60 if "holding_seconds" in df else np.nan,
        hold_med_min=df.holding_seconds.median() / 60 if "holding_seconds" in df else np.nan,
    )


def fmt(m, keys=None):
    keys = keys or list(m.keys())
    out = []
    for k in keys:
        v = m.get(k)
        if isinstance(v, float):
            out.append(f"{k}={v:.4f}" if abs(v) < 10 else f"{k}={v:.2f}")
        else:
            out.append(f"{k}={v}")
    return "  ".join(out)


SHORT = ["trades", "win_rate", "pf", "exp", "net", "avg_win", "avg_loss", "payoff", "be_wr", "max_dd", "exp_bps"]


def table(df, by, keys=SHORT, min_n=0, sort=None):
    rows = []
    for k, g in df.groupby(by, observed=True):
        if len(g) < min_n:
            continue
        m = metrics(g)
        rows.append({**({b: kk for b, kk in zip(by, k)} if isinstance(by, list) else {by: k}),
                     **{kk: m[kk] for kk in keys}})
    out = pd.DataFrame(rows)
    if sort and len(out):
        out = out.sort_values(sort, ascending=False)
    return out
