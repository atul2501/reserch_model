"""Phase 18/19/21/25/26/27 post-analysis of models.py output."""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from lib import D

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 300)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
res = pd.read_pickle(f"{D}/model_results.pkl")
preds = pd.read_pickle(f"{D}/preds.pkl")
imp = pd.read_pickle(f"{D}/importances.pkl")
ds = pd.read_parquet(f"{D}/dataset.parquet")
T = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
b, c = T("2026-10-01 14:00"), T("2026-10-02 16:00")
oo = ds[(ds.signal_bar >= b) & (ds.signal_bar < c)].copy()

print("=== PHASE 18: SAME-PERIOD TRUE OOS (FINAL fold) ===")
f = res[res.fold == "FINAL"]
print(f[["model", "fset", "target", "thr_rule", "thr", "trades", "bars", "win_rate", "pf", "exp_bps", "exp_usd", "net", "max_dd",
         "payoff", "hold_min", "auc", "pr_auc", "brier", "ece", "precision", "recall", "train_auc", "val_auc", "val_exp_bps",
         "train_exp_bps_at_thr"]].to_string(index=False))
print("\nconfusion matrices [tn, fp, fn, tp]:")
for _, r in f.iterrows():
    if isinstance(r.get("cm"), list):
        print(f"  {r.model:24s} {r.fset:3s} {r.target}: {r.cm}   boot(mean,lo,hi,P<=0)={tuple(round(x, 2) for x in r.boot)}")

print("\n=== WALK-FORWARD SUMMARY: OOS exp_bps minus fold baseline (positive = model helped) ===")
base = res[res.model.str.startswith("BASELINE")].set_index("fold").exp_bps
m = res[res.model.isin(["LR", "RF", "HGB", "XGB"])].copy()
m["delta"] = m.exp_bps - m.fold.map(base)
m["oos_positive"] = m.exp_bps > 0
piv = m.pivot_table(index=["model", "fset", "target"], columns="fold", values="delta")
piv["folds_improved"] = (piv > 0).sum(axis=1)
print(piv.to_string())
print("\nOOS exp_bps (absolute):")
print(m.pivot_table(index=["model", "fset", "target"], columns="fold", values="exp_bps").to_string())
print("\nany model with positive OOS expectancy in ANY fold:", m[m.exp_bps > 0][["fold", "model", "fset", "target", "trades", "bars", "exp_bps"]].to_string(index=False))
print("\n=== PHASE 27: OVERFITTING (train AUC vs OOS AUC; train exp@thr vs OOS exp) ===")
print(m.groupby(["model"]).agg(train_auc=("train_auc", "mean"), val_auc=("val_auc", "mean"), oos_auc=("auc", "mean"),
                               train_exp_at_thr=("train_exp_bps_at_thr", "mean"), val_exp=("val_exp_bps", "mean"),
                               oos_exp=("exp_bps", "mean")).to_string())

print("\n=== PHASE 19: STABILITY — FINAL OOS split into 4 chronological slices (selected thresholds) ===")
oo["slice"] = pd.qcut(oo.signal_bar.rank(method="first"), 4, labels=["OOS-1", "OOS-2", "OOS-3", "OOS-4"])
print(oo.groupby("slice", observed=True).signal_ts.agg(["min", "max"]).to_string())
rows = []
def slice_rows(name, keep):
    for s, g in oo[keep].groupby("slice", observed=True):
        x = g.net_pnl
        rows.append(dict(model=name, slice=s, n=len(g), wr=(x > 0).mean(), pf=x[x > 0].sum() / -x[x <= 0].sum() if (x <= 0).any() else np.nan,
                         exp_bps=g.net_bps.mean(), net=x.sum()))
slice_rows("BASELINE", np.ones(len(oo), bool))
for _, r in f.iterrows():
    key = ("FINAL", "V1") if r.model.startswith("V1") else ("FINAL", r.model, r.fset, r.target)
    if key in preds:
        slice_rows(f"{r.model}|{r.fset}|{r.target}", preds[key] >= r.thr)
sl = pd.DataFrame(rows)
print(sl.pivot_table(index="model", columns="slice", values="exp_bps").assign(
    slices_pos=lambda d: (d > 0).sum(axis=1)).to_string())
print(sl.pivot_table(index="model", columns="slice", values="n").to_string())
print(sl.pivot_table(index="model", columns="slice", values="wr").to_string())

print("\n=== PHASE 21: INTERACTIONS — OOS AUC (t1) of each FINAL ext model + V1 within subgroups ===")
oo["volstate"] = np.where(oo.atr_pctile > 0.7, "HIGH_VOL", "NORMAL_VOL")
oo["momstate"] = np.where(oo.rsi_extreme > 15, "MOM_EXTREME", "MOM_NORMAL")
oo["trendrange"] = np.where(oo.regime.isin(["TREND_UP", "TREND_DOWN", "BREAKOUT", "BREAKDOWN"]), "TREND", "RANGE")
keys = {"V1": ("FINAL", "V1"), **{k: ("FINAL", k, "ext", "t1") for k in ("LR", "RF", "HGB", "XGB")}}
rows = []
for grp in ["side", "trendrange", "family", "regime", "volstate", "momstate"]:
    for g, d in oo.groupby(grp):
        if len(d) < 300 or d.win.nunique() < 2:
            continue
        row = dict(group=grp, value=g, n=len(d), base_exp=d.net_bps.mean())
        for k, kk in keys.items():
            p = preds[kk][oo.index.get_indexer(d.index)] if False else pd.Series(preds[kk], index=oo.index)[d.index]
            ok = p.notna()
            row[f"auc_{k}"] = roc_auc_score(d.win[ok], p[ok])
            row[f"rho_exp_{k}"] = spearmanr(p[ok], d.net_bps[ok]).correlation
        rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== PHASE 26: PERMUTATION IMPORTANCE (OOS, avg-precision drop) — ext/t1 ===")
imp["rank"] = imp.groupby(["fold", "model"]).imp.rank(ascending=False)
top = imp.groupby(["model", "feature"]).agg(mean_imp=("imp", "mean"), min_imp=("imp", "min"), mean_rank=("rank", "mean")).reset_index()
for mdl in ["LR", "RF", "HGB", "XGB"]:
    t = top[top.model == mdl].sort_values("mean_imp", ascending=False).head(10)
    print(f"\n{mdl}:"); print(t.to_string(index=False))
print("\nFeatures with positive permutation importance in ALL 3 folds for >=3 of 4 models:")
pos = imp.assign(p=imp.imp > 0).groupby(["model", "feature"]).p.all().reset_index()
cnt = pos[pos.p].groupby("feature").size()
print(cnt[cnt >= 3].sort_values(ascending=False).to_dict())
print("\nImportance rank stability across folds (Spearman of importance vectors):")
for mdl in ["LR", "RF", "HGB", "XGB"]:
    pv = imp[imp.model == mdl].pivot_table(index="feature", columns="fold", values="imp")
    print(f"  {mdl}: WF1-WF2={spearmanr(pv.WF1, pv.WF2).correlation:.2f}  WF2-FINAL={spearmanr(pv.WF2, pv.FINAL).correlation:.2f}  WF1-FINAL={spearmanr(pv.WF1, pv.FINAL).correlation:.2f}")
print("\nTop-1 feature share of total positive importance (concentration):")
for (fold, mdl), g in imp.groupby(["fold", "model"]):
    p = g.imp.clip(lower=0)
    print(f"  {fold:5s} {mdl}: top={g.loc[g.imp.idxmax(), 'feature']} share={p.max() / p.sum() if p.sum() > 0 else float('nan'):.2f}")

print("\n=== PHASE 25: XGB dependence on one regime/generation/family (FINAL OOS, selected threshold) ===")
rx = f[(f.model == "XGB") & (f.fset == "ext") & (f.target == "t1")].iloc[0]
keep = preds[("FINAL", "XGB", "ext", "t1")] >= rx.thr
sel = oo[keep]
for g in ["regime", "generation", "family", "side"]:
    print(f"  by {g}:", sel.groupby(g).agg(n=("net_bps", "size"), exp=("net_bps", "mean")).round(2).to_dict("index"))
