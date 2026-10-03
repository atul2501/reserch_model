"""Research datasets. Each returns a frame with:
    t                decision time (ms). Every feature in the row is known at or before t.
    side             +1/-1 when the SIGNAL fixes the direction ("directional"); absent for "bar" data, where the
                     model must choose the side (and a trade is taken only if |prediction| clears the cost).
    <features>
    ret_{h}          forward return over h minutes in bps: signed in `side` for directional data, raw (long) otherwise.
                     Measured from the entry observation at t to the first observation at/after t + h. NaN if unknown.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

BAR_MS = 60_000
HORIZONS = (1, 5, 10, 30, 60)


def _bps(a, b):
    return (np.asarray(a, float) / np.asarray(b, float) - 1) * 1e4


# --------------------------------------------------------------------------- 1m candles (+ BTC)
def bar_dataset(sol: pd.DataFrame, btc: pd.DataFrame | None = None, *, beta_window: int = 240) -> pd.DataFrame:
    """One decision per closed 1m SOL bar at t = open_time + 60 s (entry = that bar's close)."""
    s = sol.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    c = s.close.astype(float)
    df = pd.DataFrame({"t": s.open_time.astype("int64") + BAR_MS, "bar": s.open_time.astype("int64")})
    for n in (1, 5, 15):
        df[f"sol_ret_{n}"] = c.pct_change(n).to_numpy() * 1e4
    df["sol_vol_60"] = c.pct_change().rolling(60).std().to_numpy() * 1e4
    if btc is not None and len(btc):
        b = btc.sort_values("open_time").drop_duplicates("open_time").set_index("open_time").close.astype(float)
        bc = s.open_time.map(b)
        for n in (1, 5, 15):
            df[f"btc_ret_{n}"] = bc.pct_change(n).to_numpy() * 1e4
        # causal rolling beta of SOL on BTC (past bars only) -> BTC move not yet reflected in SOL
        x, y = pd.Series(df.btc_ret_1), pd.Series(df.sol_ret_1)
        beta = (x.rolling(beta_window).cov(y) / x.rolling(beta_window).var()).shift(1)
        df["btc_resid_1"] = (x - y / beta.replace(0, np.nan)).to_numpy()
        df["sol_minus_beta_btc_1"] = (y - beta * x).to_numpy()
    for h in HORIZONS:
        fut = c.shift(-h)
        okt = s.open_time.shift(-h) == s.open_time + h * BAR_MS
        df[f"ret_{h}"] = np.where(okt, _bps(fut, c), np.nan)
    return df


# --------------------------------------------------------------------------- strategy signals
def signal_dataset(signals: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    """signals: bar (signal bar open ms), side ('LONG'/'SHORT'), plus any feature columns. Entry at the next bar's
    open (the system's next_open fill), exit at the close h bars later; signed in the signal's direction."""
    cd = candles.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    idx = pd.Series(np.arange(len(cd)), index=cd.open_time.astype("int64"))
    out = signals.copy().reset_index(drop=True)
    out["t"] = out.bar.astype("int64") + BAR_MS
    out["side"] = np.where(out.side.isin(["LONG", 1]), 1.0, -1.0)
    k = out.bar.astype("int64").map(idx)
    o, cl, ot = cd.open.to_numpy(float), cd.close.to_numpy(float), cd.open_time.to_numpy()
    for h in HORIZONS:
        e, x = k + 1, k + h
        ok = k.notna() & (x < len(cd))
        ei, xi = e.where(ok, 0).astype(int).to_numpy(), x.where(ok, 0).astype(int).to_numpy()
        exact = ok.to_numpy() & (ot[xi] == out.bar.astype("int64").to_numpy() + h * BAR_MS)
        out[f"ret_{h}"] = np.where(exact, _bps(cl[xi], o[ei]) * out.side.to_numpy(), np.nan)
    return out


# --------------------------------------------------------------------------- microstructure (collector files)
def _read(root: Path, coin: str, channel: str) -> list[dict]:
    rows = []
    for f in sorted(root.glob(f"*/{coin}_{channel}_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            try:
                for line in fh:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue                    # a partially written last line
            except EOFError:
                pass                                # the current hour's file is still being written: keep complete lines
    return rows


def load_bbo(root: Path, coin: str) -> pd.DataFrame:
    rows = []
    for r in _read(root, coin, "bbo"):
        d = r["data"]; b = d.get("bbo") or [None, None]
        if b[0] and b[1]:
            rows.append((int(d["time"]), r["recv_ms"], float(b[0]["px"]), float(b[0]["sz"]), float(b[1]["px"]), float(b[1]["sz"])))
    df = pd.DataFrame(rows, columns=["ts", "recv_ms", "bid", "bid_sz", "ask", "ask_sz"]).sort_values("ts")
    return df.drop_duplicates("ts", keep="last").reset_index(drop=True)


def load_trades(root: Path, coin: str) -> pd.DataFrame:
    rows = []
    for r in _read(root, coin, "trades"):
        for t in r["data"]:
            rows.append((int(t["time"]), int(t.get("tid", 0)), 1.0 if t["side"] == "B" else -1.0, float(t["px"]), float(t["sz"])))
    df = pd.DataFrame(rows, columns=["ts", "tid", "aggr", "px", "sz"])
    return df.drop_duplicates("tid").sort_values("ts").reset_index(drop=True)   # subscribe snapshots repeat trades


def coverage(root: str | Path) -> dict:
    """Hours of data per coin/channel (for the research-lab data-sufficiency panel)."""
    root = Path(root)
    out = {}
    for f in root.glob("*/*.jsonl.gz"):
        coin, ch, _ = f.name.split("_", 2)
        out.setdefault(f"{coin}:{ch}", set()).add(f.name.rsplit("_", 1)[-1][:10])
    return {k: len(v) for k, v in sorted(out.items())}


def microstructure_dataset(root: str | Path, *, step_s: int = 15, horizons_min=(1, 5, 10, 30)) -> pd.DataFrame:
    """Decisions every `step_s` seconds. Every feature uses only exchange-timestamped data with ts <= t; the outcome is
    the first SOL BBO mid at/after t + h (an actual observation, never interpolated)."""
    root = Path(root)
    bbo, trades = load_bbo(root, "SOL"), load_trades(root, "SOL")
    btc = load_bbo(root, "BTC")
    if len(bbo) < 100:
        return pd.DataFrame()
    bbo["mid"] = (bbo.bid + bbo.ask) / 2
    t = np.arange(int(bbo.ts.iloc[0]) + 60_000, int(bbo.ts.iloc[-1]), step_s * 1000, dtype=np.int64)
    ts = bbo.ts.to_numpy()
    i = np.searchsorted(ts, t, side="right") - 1                      # last bbo with ts <= t
    ok = i >= 0
    t, i = t[ok], i[ok]
    b = bbo.iloc[i].reset_index(drop=True)
    df = pd.DataFrame({"t": t, "bar": (t // BAR_MS) * BAR_MS, "mid": b.mid.to_numpy(),
                       "bbo_age_ms": t - b.ts.to_numpy()})
    tot = b.bid_sz + b.ask_sz
    df["bbo_imbalance"] = ((b.bid_sz - b.ask_sz) / tot).to_numpy()
    micro = (b.bid * b.ask_sz + b.ask * b.bid_sz) / tot
    df["microprice_offset_bps"] = _bps(micro, b.mid)
    df["spread_bps"] = _bps(b.ask, b.bid)
    for w in (10, 60):
        j = np.searchsorted(ts, t - w * 1000, side="right") - 1
        prev = np.where(j >= 0, bbo.mid.to_numpy()[np.maximum(j, 0)], np.nan)
        df[f"sol_mid_ret_{w}s"] = _bps(df.mid, prev)
    if len(trades):
        tt = trades.ts.to_numpy()
        signed = np.cumsum(trades.aggr.to_numpy() * trades.sz.to_numpy())
        vol = np.cumsum(trades.sz.to_numpy())
        cnt = np.arange(1, len(trades) + 1)
        for w in (10, 60):
            hi = np.searchsorted(tt, t, side="right") - 1
            lo = np.searchsorted(tt, t - w * 1000, side="right") - 1
            sv = np.where(hi >= 0, signed[np.maximum(hi, 0)], 0) - np.where(lo >= 0, signed[np.maximum(lo, 0)], 0)
            vv = np.where(hi >= 0, vol[np.maximum(hi, 0)], 0) - np.where(lo >= 0, vol[np.maximum(lo, 0)], 0)
            df[f"trade_flow_imb_{w}s"] = np.where(vv > 0, sv / np.where(vv > 0, vv, 1), 0.0)
            df[f"trade_count_{w}s"] = np.where(hi >= 0, cnt[np.maximum(hi, 0)], 0) - np.where(lo >= 0, cnt[np.maximum(lo, 0)], 0)
    if len(btc) > 100:
        btc["mid"] = (btc.bid + btc.ask) / 2
        bts = btc.ts.to_numpy()
        k = np.searchsorted(bts, t, side="right") - 1
        now = np.where(k >= 0, btc.mid.to_numpy()[np.maximum(k, 0)], np.nan)
        for w in (10, 60):
            kj = np.searchsorted(bts, t - w * 1000, side="right") - 1
            prev = np.where(kj >= 0, btc.mid.to_numpy()[np.maximum(kj, 0)], np.nan)
            df[f"btc_mid_ret_{w}s"] = _bps(now, prev)
    for h in horizons_min:
        j = np.searchsorted(ts, t + h * BAR_MS, side="left")          # first observation at/after t + h
        okj = j < len(bbo)
        fut = np.where(okj, bbo.mid.to_numpy()[np.minimum(j, len(bbo) - 1)], np.nan)
        df[f"ret_{h}"] = np.where(okj, _bps(fut, df.mid), np.nan)
    return df
