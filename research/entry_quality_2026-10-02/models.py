"""Phase 9/10/14-19/25-27: chronological model comparison. Thresholds chosen on VALIDATION only."""
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier
from features import FEATURE_REGISTRY, V1_COLS
from lib import D, max_dd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
pd.set_option("display.float_format", lambda v: f"{v:.4f}")
SEED = 20261002
ds = pd.read_parquet(f"{D}/dataset.parquet")
ds["closed_ms"] = ds.closed_at.astype("int64") // 10**6
ds["t1"] = (ds.net_pnl > 0).astype(int)            # original V1 target
ds["t2"] = (ds.net_bps >= 10).astype(int)          # 'sufficiently positive' target
T = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
EMB = 2 * 3600_000  # 2h embargo (max hold ~2h) between splits
FOLDS = {
    "WF1": (T("2026-09-28 20:00"), T("2026-09-29 16:00"), T("2026-09-30 12:00")),
    "WF2": (T("2026-09-29 16:00"), T("2026-09-30 12:00"), T("2026-10-01 08:00")),
    "FINAL": (T("2026-09-30 14:00"), T("2026-10-01 14:00"), T("2026-10-02 16:00")),
}
CAT = ["family", "regime", "side"]
EXT_NUM = [f for f in FEATURE_REGISTRY]  # includes V1 cols + ext + context numeric
FSETS = {"v1": (list(V1_COLS), []), "ext": (EXT_NUM, CAT)}


def split(fold):
    a, b, c = FOLDS[fold]
    tr = ds[(ds.signal_bar < a - EMB) & (ds.closed_ms < a)]                       # purge: outcome known before val
    va = ds[(ds.signal_bar >= a) & (ds.signal_bar < b - EMB) & (ds.closed_ms < b)]
    oo = ds[(ds.signal_bar >= b) & (ds.signal_bar < c)]
    return tr, va, oo


def make(model, num, cat, params):
    pre = ColumnTransformer([("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num)]
                            + ([("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat)] if cat else []))
    if model == "LR":
        clf = LogisticRegression(C=params["C"], class_weight="balanced", max_iter=2000)
    elif model == "RF":
        clf = RandomForestClassifier(n_estimators=200, min_samples_leaf=params["leaf"], max_features="sqrt",
                                     class_weight="balanced_subsample", n_jobs=-1, random_state=SEED)
    elif model == "HGB":
        clf = HistGradientBoostingClassifier(learning_rate=0.05, max_iter=params["it"], max_leaf_nodes=params["leaves"],
                                             min_samples_leaf=200, l2_regularization=1.0, class_weight="balanced",
                                             early_stopping=False, random_state=SEED)
    else:
        clf = XGBClassifier(n_estimators=params["n"], max_depth=params["depth"], learning_rate=0.05, subsample=0.8,
                            colsample_bytree=0.8, min_child_weight=50, reg_lambda=5.0, tree_method="hist",
                            random_state=SEED, n_jobs=-1, eval_metric="logloss", scale_pos_weight=params["spw"])
    return Pipeline([("pre", pre), ("clf", clf)])


GRID = {"LR": [{"C": 0.01}, {"C": 0.1}, {"C": 1.0}],
        "RF": [{"leaf": 50}, {"leaf": 200}],
        "HGB": [{"it": 100, "leaves": 15}, {"it": 300, "leaves": 31}],
        "XGB": [{"n": 200, "depth": 3}, {"n": 400, "depth": 5}]}


def trade_stats(df):
    if len(df) == 0:
        return dict(trades=0, bars=0, win_rate=np.nan, pf=np.nan, exp_usd=np.nan, exp_bps=np.nan, net=0.0,
                    avg_win=np.nan, avg_loss=np.nan, payoff=np.nan, max_dd=0.0, hold_min=np.nan)
    x = df.net_pnl.to_numpy(); w, l = x[x > 0], x[x <= 0]
    aw, al = (w.mean() if len(w) else np.nan), (l.mean() if len(l) else np.nan)
    return dict(trades=len(df), bars=df.signal_bar.nunique(), win_rate=len(w) / len(x),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.nan, exp_usd=x.mean(), exp_bps=df.net_bps.mean(),
                net=x.sum(), avg_win=aw, avg_loss=al, payoff=aw / -al if len(w) and len(l) else np.nan,
                max_dd=max_dd(df.sort_values("closed_at").net_pnl.to_numpy()), hold_min=df.holding_seconds.mean() / 60)


def ece(y, p, bins=10):
    e = 0.0
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo) & (p <= hi)
        if m.sum():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return e


def cls_stats(y, p, thr):
    yhat = (p >= thr).astype(int)
    tp, fp = int(((yhat == 1) & (y == 1)).sum()), int(((yhat == 1) & (y == 0)).sum())
    fn, tn = int(((yhat == 0) & (y == 1)).sum()), int(((yhat == 0) & (y == 0)).sum())
    return dict(auc=roc_auc_score(y, p) if len(set(y)) > 1 else np.nan, pr_auc=average_precision_score(y, p),
                base_rate=y.mean(), brier=brier_score_loss(y, p), ece=ece(y, p),
                precision=tp / (tp + fp) if tp + fp else np.nan, recall=tp / (tp + fn) if tp + fn else np.nan,
                cm=[tn, fp, fn, tp])


def candidates(p_val):
    c = [("abs", x) for x in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)]
    c += [(f"top{int(q*100)}%", float(np.quantile(p_val, 1 - q))) for q in (0.5, 0.3, 0.2, 0.1, 0.05)]
    return c


def pick_threshold(va, p_val):
    """VALIDATION-ONLY rule (fixed a priori): max validation net expectancy (bps) among thresholds that keep
    >=100 trades and >=30 distinct signal bars. 'keep all' (threshold 0) is always a candidate."""
    best = ("keep_all", 0.0, va.net_bps.mean())
    for name, thr in candidates(p_val):
        sel = va[p_val >= thr]
        if len(sel) >= 100 and sel.signal_bar.nunique() >= 30 and sel.net_bps.mean() > best[2]:
            best = (name, thr, sel.net_bps.mean())
    return best


def block_boot_diff(oo, keep, n=2000, seed=SEED):
    """Hour-block bootstrap of (exp_bps selected - exp_bps all) on OOS."""
    rng = np.random.default_rng(seed)
    hrs = (oo.signal_bar // 3600_000).to_numpy()
    u = np.unique(hrs)
    groups = {h: np.where(hrs == h)[0] for h in u}
    nb, kb = oo.net_bps.to_numpy(), keep.astype(bool)
    diffs = []
    for _ in range(n):
        idx = np.concatenate([groups[h] for h in rng.choice(u, len(u))])
        s = idx[kb[idx]]
        if len(s):
            diffs.append(nb[s].mean() - nb[idx].mean())
    d = np.array(diffs)
    return float(np.mean(d)), float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975)), float((d <= 0).mean())


results, preds_store, imps = [], {}, []
for fold in FOLDS:
    tr, va, oo = split(fold)
    rng_txt = lambda d: f"{pd.to_datetime(d.signal_bar.min(), unit='ms')} -> {pd.to_datetime(d.signal_bar.max(), unit='ms')} (n={len(d)}, bars={d.signal_bar.nunique()})"
    print(f"\n######## {fold}\n TRAIN {rng_txt(tr)}\n VALID {rng_txt(va)}\n OOS   {rng_txt(oo)}")
    base = trade_stats(oo)
    results.append(dict(fold=fold, model="BASELINE (all trades)", fset="-", target="-", hp="-", thr_rule="keep_all", thr=0.0,
                        **base, auc=np.nan, pr_auc=np.nan, brier=np.nan, ece=np.nan))
    # ---- V1 production (frozen). Only fair where V1 never saw the data (FINAL fold val+oos).
    if fold == "FINAL":
        for rule, thr in [("val-selected",) + pick_threshold(va, va.p_v1.to_numpy())[1:2], ("prod_default", 0.60)]:
            keep = oo.p_v1.to_numpy() >= thr
            cs = cls_stats(oo.t1.to_numpy(), oo.p_v1.to_numpy(), thr)
            results.append(dict(fold=fold, model=f"V1 frozen ({rule})", fset="v1", target="t1", hp="frozen", thr_rule=rule,
                                thr=thr, **trade_stats(oo[keep]), **{k: cs[k] for k in ("auc", "pr_auc", "brier", "ece", "precision", "recall")},
                                cm=cs["cm"], boot=block_boot_diff(oo, keep)))
        preds_store[("FINAL", "V1")] = oo.p_v1.to_numpy()
    for fs_name, (num, cat) in FSETS.items():
        for target in (["t1", "t2"] if fs_name == "ext" else ["t1"]):
            ytr, yva, yoo = tr[target].to_numpy(), va[target].to_numpy(), oo[target].to_numpy()
            for model, grid in GRID.items():
                best = None
                for hp in grid:
                    hp = dict(hp)
                    if model == "XGB":
                        hp["spw"] = (1 - ytr.mean()) / ytr.mean()
                    m = make(model, num, cat, hp).fit(tr[num + cat], ytr)
                    pv = m.predict_proba(va[num + cat])[:, 1]
                    ll = log_loss(yva, np.clip(pv, 1e-6, 1 - 1e-6))
                    if best is None or ll < best[0]:
                        best = (ll, hp, m, pv)
                _, hp, m, pv = best
                rule, thr, vexp = pick_threshold(va, pv)
                po = m.predict_proba(oo[num + cat])[:, 1]
                ptr = m.predict_proba(tr[num + cat])[:, 1]
                keep = po >= thr
                cs = cls_stats(yoo, po, thr)
                trk = ptr >= thr
                results.append(dict(fold=fold, model=model, fset=fs_name, target=target, hp=json.dumps({k: v for k, v in hp.items() if k != "spw"}),
                                    thr_rule=rule, thr=thr, val_exp_bps=vexp, **trade_stats(oo[keep]),
                                    **{k: cs[k] for k in ("auc", "pr_auc", "brier", "ece", "precision", "recall")}, cm=cs["cm"],
                                    train_auc=roc_auc_score(ytr, ptr), val_auc=roc_auc_score(yva, pv),
                                    train_exp_bps_at_thr=tr[trk].net_bps.mean() if trk.any() else np.nan,
                                    boot=block_boot_diff(oo, keep)))
                preds_store[(fold, model, fs_name, target)] = po
                # Permutation importance (ext/t1 tree models + LR) on OOS, scoring = average precision
                if fs_name == "ext" and target == "t1":
                    pi = permutation_importance(m, oo[num + cat], yoo, scoring="average_precision", n_repeats=3,
                                                random_state=SEED, n_jobs=1)
                    for f, v in zip(num + cat, pi.importances_mean):
                        imps.append(dict(fold=fold, model=model, feature=f, imp=v))
                print(f"  {fold} {model:4s} {fs_name:3s} {target}: hp={hp.get('C', hp.get('leaf', hp.get('it', hp.get('n'))))} thr={rule}:{thr:.3f} "
                      f"val_exp={vexp:+.2f}  OOS: n={keep.sum()} exp_bps={oo[keep].net_bps.mean() if keep.any() else float('nan'):+.2f} "
                      f"(base {oo.net_bps.mean():+.2f}) auc={cs['auc']:.3f} trainAUC={roc_auc_score(ytr, ptr):.3f}", flush=True)

res = pd.DataFrame(results)
res.to_pickle(f"{D}/model_results.pkl")
pd.to_pickle(preds_store, f"{D}/preds.pkl")
pd.DataFrame(imps).to_pickle(f"{D}/importances.pkl")
cols = ["fold", "model", "fset", "target", "thr_rule", "thr", "trades", "bars", "win_rate", "pf", "exp_bps", "exp_usd", "net", "max_dd",
        "avg_win", "avg_loss", "payoff", "auc", "pr_auc", "brier", "ece", "train_auc", "val_auc", "val_exp_bps", "train_exp_bps_at_thr"]
print("\n\n==================== RESULTS ====================")
print(res[cols].to_string(index=False))
print("\nBootstrap (OOS exp_bps selected minus baseline): mean, 2.5%, 97.5%, P(diff<=0)")
for _, r in res.iterrows():
    if isinstance(r.get("boot"), tuple):
        print(f"  {r.fold:5s} {r.model:28s} {r.fset:3s} {r.target:2s}: " + "  ".join(f"{x:+.2f}" for x in r.boot))
