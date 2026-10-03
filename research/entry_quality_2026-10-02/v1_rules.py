"""Phase 9/10 (V1 thresholds & buckets) and Phase 20 (simple rules) on the FINAL fold split."""
import numpy as np
import pandas as pd
from lib import D, max_dd

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
ds = pd.read_parquet(f"{D}/dataset.parquet")
ds = ds.dropna(subset=["p_v1"]).copy()  # 5 warm-up rows unscorable by V1
ds["closed_ms"] = ds.closed_at.astype("int64") // 10**6
T = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
EMB = 2 * 3600_000
a, b, c = T("2026-09-30 14:00"), T("2026-10-01 14:00"), T("2026-10-02 16:00")
tr = ds[(ds.signal_bar < a - EMB) & (ds.closed_ms < a)]
va = ds[(ds.signal_bar >= a) & (ds.signal_bar < b - EMB) & (ds.closed_ms < b)]
oo = ds[(ds.signal_bar >= b) & (ds.signal_bar < c)]
V1_END = 1_790_776_320_000  # last bar in V1's dataset (2026-09-30 13:52)


def st(d):
    if len(d) == 0:
        return dict(n=0)
    x = d.net_pnl.to_numpy(); w, l = x[x > 0], x[x <= 0]
    return dict(n=len(d), bars=d.signal_bar.nunique(), wr=len(w) / len(x), pf=w.sum() / -l.sum() if len(l) else np.nan,
                exp_bps=d.net_bps.mean(), exp_usd=x.mean(), net=x.sum(), avg_win=w.mean() if len(w) else np.nan,
                avg_loss=l.mean() if len(l) else np.nan, max_dd=max_dd(d.sort_values("closed_at").net_pnl.to_numpy()),
                mfe=d.mfe_bps.mean(), mae=d.mae_bps.mean())


print("V1 probability distribution (all scored):", ds.p_v1.describe().round(3).to_dict())
print("\n=== PHASE 9: V1 THRESHOLD GRID ===")
for name, d in [("TRAIN-period (V1 in-sample!)", tr), ("VALID (V1 unseen)", va), ("TRUE OOS (V1 unseen; report only)", oo)]:
    print(f"\n-- {name}")
    rows = [dict(thr="all", **st(d))] + [dict(thr=t, **st(d[d.p_v1 >= t])) for t in (0.5, .55, .6, .65, .7, .75, .8, .85, .9)]
    print(pd.DataFrame(rows).to_string(index=False))

print("\n=== PHASE 10: V1 PROBABILITY BUCKETS (data V1 never saw: signal > 2026-09-30 13:52) ===")
un = ds[ds.signal_bar > V1_END]
edges = [0, .5, .55, .6, .65, .7, .75, .8, .85, .9, 1.01]
un = un.assign(bucket=pd.cut(un.p_v1, edges, right=False))
rows = []
for k, g in un.groupby("bucket", observed=True):
    rows.append(dict(bucket=str(k), mean_p=g.p_v1.mean(), **st(g)))
print(pd.DataFrame(rows).to_string(index=False))
from scipy.stats import spearmanr
dec = pd.qcut(un.p_v1, 10, labels=False)
dd = un.groupby(dec).agg(p=("p_v1", "mean"), wr=("win", "mean"), exp=("net_bps", "mean"), n=("win", "size"))
print("\nV1 deciles on unseen data:\n", dd.to_string())
print("Spearman(decile, win rate) =", spearmanr(dd.index, dd.wr).correlation.round(3),
      " Spearman(decile, exp_bps) =", spearmanr(dd.index, dd.exp).correlation.round(3))
from sklearn.metrics import roc_auc_score
print("V1 AUC on unseen:", round(roc_auc_score(un.win, un.p_v1), 4), " in-sample (<= V1_END):",
      round(roc_auc_score(ds[ds.signal_bar <= V1_END].win, ds[ds.signal_bar <= V1_END].p_v1), 4))
print("V1 AUC by day (unseen):", un.groupby(un.closed_at.dt.strftime('%m-%d')).apply(lambda g: round(roc_auc_score(g.win, g.p_v1), 3)).to_dict())
print("V1 within-family AUC (unseen):", un.groupby("family").apply(lambda g: round(roc_auc_score(g.win, g.p_v1), 3) if g.win.nunique() > 1 and len(g) > 100 else None).dropna().to_dict())

print("\n=== PHASE 20: SIMPLE RULES (parameter chosen on VALID; OOS report) ===")
rules = {
    "extension: reject ext_atr > k": [(k, lambda d, k=k: d.extension_atr <= k) for k in (0.5, 1.0, 1.5, 2.0, 3.0)],
    "momentum exhaustion: reject rsi_extreme>k & rsi_accel<0": [(k, lambda d, k=k: ~((d.rsi_extreme > k) & (d.rsi_accel < 0))) for k in (10, 15, 20, 25)],
    "volatility: reject vol_ratio_10_60 > k": [(k, lambda d, k=k: d.vol_ratio_10_60 <= k) for k in (1.0, 1.25, 1.5, 2.0)],
    "volatility: reject atr_pctile > k": [(k, lambda d, k=k: d.atr_pctile <= k) for k in (0.5, 0.7, 0.9)],
    "volume: reject vol_z60 > k": [(k, lambda d, k=k: d.vol_z60 <= k) for k in (1.0, 1.5, 2.0, 3.0)],
    "trend align: require signed htf_trend_240 > k": [(k, lambda d, k=k: d.htf_trend_240 > k) for k in (-0.0005, 0.0, 0.0005)],
    "trend align: require signed htf_trend_60 > 0": [(0, lambda d: d.htf_trend_60 > 0)],
    "council aligned only": [(1, lambda d: d.council_aligned > 0)],
    "volatility: require atr_14 >= k (cost-coverage)": [(k, lambda d, k=k: d.atr_14 >= k) for k in (0.0008, 0.001, 0.0012, 0.0015)],
    "family: order_flow only": [("of", lambda d: d.family == "order_flow")],
}
# regime/strategy filter learned on TRAIN: keep combos with train gross_bps > k
combo_g = tr.groupby(["family", "regime", "side"]).agg(g=("gross_bps", "mean"), n=("gross_bps", "size"))
for k in (-2.0, 0.0, 2.0):
    keep_set = set(combo_g[(combo_g.n >= 100) & (combo_g.g > k)].index)
    rules.setdefault("regime filter: train combo gross_bps > k", []).append(
        (k, lambda d, s=keep_set: pd.Series([x in s for x in zip(d.family, d.regime, d.side)], index=d.index)))
out = []
for rname, variants in rules.items():
    best = None
    for k, f in variants:
        sv = va[f(va)]
        if len(sv) >= 100 and sv.signal_bar.nunique() >= 30 and (best is None or sv.net_bps.mean() > best[1]):
            best = (k, sv.net_bps.mean(), f)
    if best is None:
        out.append(dict(rule=rname, param="(none valid)")); continue
    k, vexp, f = best
    so = oo[f(oo)]
    out.append(dict(rule=rname, param=k, val_exp_bps=vexp, val_base=va.net_bps.mean(), **{f"oos_{x}": y for x, y in st(so).items()}))
print(f"VALID baseline exp_bps={va.net_bps.mean():.2f}; OOS baseline: ", {k: round(v, 3) for k, v in st(oo).items()})
print(pd.DataFrame(out).to_string(index=False))
