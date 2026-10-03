"""Section 18 information test: does BTC's last-minute move carry information about SOL's next minutes
beyond SOL's own move? Public Hyperliquid 1m candles (BTC) vs stored SOL candles. Descriptive, no fitting."""
import glob, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "phase2_signal_horizon"))
from p2lib import cluster_t, block2h
HL = sys.argv[1]
b = pd.DataFrame([dict(t=int(c["t"]), bo=float(c["o"]), bc=float(c["c"])) for f in glob.glob(f"{HL}/btc_*.json") for c in json.load(open(f))]).drop_duplicates("t")
s = pd.read_parquet(sys.argv[2])[["open_time", "open", "close"]].rename(columns={"open_time": "t"})
m = s.merge(b, on="t").sort_values("t").reset_index(drop=True)
m["sr"] = (m.close / m.open - 1) * 1e4; m["br"] = (m.bc / m.bo - 1) * 1e4
m["resid"] = m.br - m.sr * (np.cov(m.br, m.sr)[0, 1] / m.sr.var())   # BTC move not reflected in SOL this bar
for h in (1, 5, 15):
    m[f"sfwd{h}"] = (m.close.shift(-h) / m.close - 1) * 1e4               # SOL from this close (entry at next open ~ close)
print(f"bars {len(m)}  {pd.to_datetime(m.t.min(), unit='ms')} -> {pd.to_datetime(m.t.max(), unit='ms')}; same-bar corr(BTC,SOL) {m.br.corr(m.sr):.3f}")
for h in (1, 5, 15):
    print(f"h={h:2d}: corr(BTC ret_t, SOL fwd) {m.br.corr(m[f'sfwd{h}']):+.4f} | corr(BTC residual_t, SOL fwd) {m.resid.corr(m[f'sfwd{h}']):+.4f} | corr(SOL ret_t, SOL fwd) {m.sr.corr(m[f'sfwd{h}']):+.4f}")
q = m.resid.quantile([.05, .95])
for lab, mask, sgn in [("BTC led UP (resid top 5%)", m.resid > q[.95], 1), ("BTC led DOWN (resid bottom 5%)", m.resid < q[.05], -1)]:
    for h in (1, 5, 15):
        x = sgn * m.loc[mask, f"sfwd{h}"]
        print(f"  {lab} -> SOL fwd{h} in BTC direction: {x.mean():+.2f} bps (t {cluster_t(x, block2h(m.t[mask]))[0]:+.2f}, n {mask.sum()})")
