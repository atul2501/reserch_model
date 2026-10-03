"""Phase 2 sections 7, 8, 13, 14, 15, 17: order flow, minimum expected move, trade frequency, offline exits,
walk-forward rule selection (VALIDATION picks, OOS reports), success criteria. Needs p2_main.py outputs."""
import itertools, os
import numpy as np
import pandas as pd
from p2lib import (D, OUT, HORIZONS, COSTS, FOLDS, candles, add_forward, cluster_t, econ, block2h, fold_parts, T)

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 400)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
c = candles(); idx = pd.Series(np.arange(len(c)), index=c.open_time)
allsig = pd.read_parquet(f"{D}/p2_allsig.parquet"); trsig = pd.read_parquet(f"{D}/p2_trsig.parquet")
S1 = COSTS["S1_current"]

# ------------------------------------------------------------ market drift (direction bias of the sample period)
o = c.open.to_numpy()
mkt = {}
for h in HORIZONS:
    j = np.minimum(np.arange(len(c)) + h, len(c) - 1)
    mkt[h] = pd.Series((c.close.to_numpy()[np.minimum(np.arange(len(c)) + h - 1, len(c) - 1)] / o - 1) * 1e4, index=c.open_time)
tstart = T("2026-09-27 08:11"); tend = int(c.open_time.max())
p0, p1 = c.set_index("open_time").open[tstart], c.set_index("open_time").close[tend]
print(f"SOL {p0:.2f} -> {p1:.2f} ({(p1/p0-1)*1e4:+.0f} bps) over the trading window; "
      f"unconditional mean LONG fwd_60 per bar = {mkt[60][mkt[60].index >= tstart].mean():+.2f} bps (shorts get the negative of this for free)")


def drift_adj(df, h):
    """Signed fwd minus what the same side earns unconditionally at that bar's horizon window (market drift)."""
    sgn = np.where(df.side == "LONG", 1.0, -1.0)
    m = df.bar.map(lambda b: np.nan) if False else (df.bar + 60_000).map(mkt[h])  # entry bar = signal bar + 1
    return df[f"fwd_{h}"] - 0.0 * m  # placeholder (pointwise drift == the move itself); use period-mean below


def period_drift(df, h):
    """Side x mean unconditional market return at horizon h within the df's own time span."""
    lo, hi = df.bar.min(), df.bar.max()
    mu = mkt[h][(mkt[h].index >= lo) & (mkt[h].index <= hi)].mean()
    return np.where(df.side == "LONG", 1.0, -1.0) * mu


# ------------------------------------------------------------ 8. ORDER FLOW (bar-level, deterministic, all bars)
print("\n=== 8. ORDER FLOW — bar-level proxy flow_imbalance_p (volume-weighted candle direction) ===")
bars = c[["open_time", "open", "high", "low", "close", "volume"]].copy()
sv = np.sign(bars.close - bars.open) * bars.volume
for p in (5, 10, 20):
    bars[f"fi{p}"] = (sv.rolling(p).sum() / bars.volume.rolling(p).sum().replace(0, np.nan))
bars["vr20"] = bars.volume / bars.volume.rolling(20).mean()
bars["ret10"] = bars.close.pct_change(10)
tr_ = pd.concat([bars.high - bars.low, (bars.high - bars.close.shift()).abs(), (bars.low - bars.close.shift()).abs()], axis=1).max(axis=1)
bars["atr_bps"] = tr_.ewm(alpha=1 / 14, adjust=False).mean() / bars.close * 1e4
bars["atr_pct"] = bars.atr_bps.expanding(100).rank(pct=True)
rg = pd.read_parquet(f"{D}/regimes.parquet").sort_values("candle_open_time")
bars = pd.merge_asof(bars, rg[["candle_open_time", "regime"]].rename(columns={"candle_open_time": "rb"}), left_on="open_time", right_on="rb", direction="backward")
bars = bars[(bars.open_time >= tstart)].copy()
bars["bar"] = bars.open_time
for p in (5, 10, 20):
    bars[f"fi{p}_prev"] = bars[f"fi{p}"].shift(1)


def of_frame(p):
    f = bars.copy()
    f["side"] = np.where(f[f"fi{p}"] >= 0, "LONG", "SHORT")
    return add_forward(f, c, idx)


ofr = []
for p in (5, 10, 20):
    f = of_frame(p)
    f["bucket"] = pd.cut(f[f"fi{p}"], [-1.01, -0.45, -0.2, 0.2, 0.45, 1.01], labels=["strong_neg", "weak_neg", "neutral", "weak_pos", "strong_pos"])
    f["persist3"] = (np.sign(f[f"fi{p}"]) == np.sign(f[f"fi{p}_prev"])) & (np.sign(f[f"fi{p}"]) == np.sign(f[f"fi{p}"].shift(2)))
    f["accel"] = np.sign(f.fi5) == np.sign(f.fi20)
    f["accel"] &= f.fi5.abs() > f.fi20.abs()
    f["mom_agree"] = np.sign(f.ret10) == np.sign(f[f"fi{p}"])
    f["highvol"] = f.atr_pct > 0.7
    f["vol_spike"] = f.vr20 > 1.4
    conds = {"all": slice(None)}
    for name, m in [("bucket", "bucket"), ("persist3", "persist3"), ("accel", "accel"), ("mom_agree", "mom_agree"),
                    ("highvol", "highvol"), ("vol_spike", "vol_spike"), ("regime", "regime")]:
        for k, d in f.groupby(m, observed=True):
            r = dict(p=p, condition=name, value=str(k), n_bars=len(d))
            for h in (1, 5, 10, 30, 60):
                x = d[f"fwd_{h}"]  # continuation direction = sign(flow)
                r[f"cont_fwd{h}"] = x.mean(); r[f"t{h}"] = cluster_t(x, block2h(d.bar))[0]
            r["cont_fwd30_S1"] = r["cont_fwd30"] - S1
            r["drift_part30"] = np.mean(period_drift(d, 30))
            d4 = pd.qcut(d.bar.rank(method="first"), 4, labels=False) if len(d) >= 40 else None
            if d4 is not None:
                q = d.groupby(d4).fwd_30.mean()
                r.update({f"Q{i+1}_fwd30": q.get(i) for i in range(4)}); r["quarters_pos"] = int((q > 0).sum())
            ofr.append(r)
of = pd.DataFrame(ofr)
of.to_csv(f"{OUT}/order_flow_analysis.csv", index=False)
show = of[(of.p == 10) | ((of.condition == "bucket"))]
print(show[["p", "condition", "value", "n_bars", "cont_fwd1", "cont_fwd5", "cont_fwd10", "cont_fwd30", "t30", "cont_fwd60", "t60", "drift_part30",
            "Q1_fwd30", "Q2_fwd30", "Q3_fwd30", "Q4_fwd30", "quarters_pos"]].to_string(index=False))
print("\nOrder-flow STRATEGY (traded signals) by flow at signal bar (p=10 bucket):")
ofs = trsig[trsig.family == "order_flow"].merge(bars[["bar", "fi10", "vr20", "atr_pct"]], on="bar", how="left")
ofs["fi_signed"] = ofs.fi10 * np.where(ofs.side == "LONG", 1, -1)
ofs["mag"] = pd.cut(ofs.fi_signed, [-1, 0.2, 0.45, 0.7, 1.01], labels=["<0.2", "0.2-0.45", "0.45-0.7", ">0.7"])
print(ofs.groupby("mag", observed=True).agg(n=("fwd_30", "size"), fwd10=("fwd_10", "mean"), fwd30=("fwd_30", "mean"), fwd60=("fwd_60", "mean"),
                                           net=("net_bps", "mean"), mid=("mid_bps", "mean")).to_string())
print(ofs.groupby("side").agg(n=("fwd_30", "size"), fwd30=("fwd_30", "mean"), fwd60=("fwd_60", "mean"), net=("net_bps", "mean")).to_string())

# ------------------------------------------------------------ 13. OFFLINE EXIT SIMULATION (only meaningful if entries have edge)
print("\n=== 13. OFFLINE EXITS on traded signals (ATR-based SL/TP, max 60m; stop-first if both in one bar) ===")
H = 60
hi, lo, cl = c.high.to_numpy(), c.low.to_numpy(), c.close.to_numpy()


def sim_exit(sig, sl_k, tp_k, trail_k=None, max_h=H, flip=False):
    e = sig.bar.map(idx).to_numpy() + 1
    sgn = np.where(sig.side.to_numpy() == "LONG", 1.0, -1.0) * (-1 if flip else 1)
    atrb = sig.bar.map(bars.set_index("bar").atr_bps).to_numpy()
    out = np.full(len(sig), np.nan); kind = np.empty(len(sig), object)
    for i in range(len(sig)):
        if e[i] + max_h >= len(c) or not np.isfinite(atrb[i]):
            continue
        p0 = o[e[i]]; a = atrb[i]
        stop = -sl_k * a if sl_k else -1e9; tp = tp_k * a if tp_k else 1e9
        peak = 0.0; res = None
        for j in range(max_h):
            k = e[i] + j
            fav = ((hi[k] if sgn[i] > 0 else lo[k]) / p0 - 1) * 1e4 * sgn[i]
            adv = ((lo[k] if sgn[i] > 0 else hi[k]) / p0 - 1) * 1e4 * sgn[i]
            if adv <= stop: res = (stop, "stop"); break
            if fav >= tp: res = (tp, "tp"); break
            peak = max(peak, fav)
            if trail_k and peak >= trail_k * a:
                stop = max(stop, peak - trail_k * a)
        if res is None:
            res = ((cl[e[i] + max_h - 1] / p0 - 1) * 1e4 * sgn[i], "time")
        # costs: entry taker 4.5 + 2 slip; stop exit taker 4.5 + 4 slip; tp maker 1.5; time exit taker 4.5 + 2
        cost = 6.5 + {"stop": 8.5, "tp": 1.5, "time": 6.5}[res[1]]
        out[i] = res[0] - cost; kind[i] = res[1]
    return out, kind


EXIT_GRID = [(f"fixed_{h}m", None, None, None, h) for h in (5, 10, 30, 60)]
EXIT_GRID += [(f"sl{s}_tp{t}", s, t, None, H) for s in (1, 2, 4) for t in (1, 2, 4, 8)]
EXIT_GRID += [(f"sl{s}_trail{tr}", s, None, tr, H) for s in (2, 4) for tr in (1, 2)]
ex_rows, ex_store = [], {}
for name, s, t, tr, mh in EXIT_GRID:
    x, kind = sim_exit(trsig, s, t, tr, mh)
    xf, _ = sim_exit(trsig, s, t, tr, mh, flip=True)
    ex_store[name] = x
    e = econ(x); ef = econ(xf)
    ex_rows.append(dict(exit=name, n=e["n"], exp_bps_S1like=e["exp_bps"], pf=e["pf"], win_rate=e["win_rate"], avg_win=e["avg_win"],
                        avg_loss=e["avg_loss"], be_wr=e["be_wr"], t_cluster=cluster_t(x, block2h(trsig.bar))[0],
                        flipped_direction_exp=ef["exp_bps"], edge_vs_flipped=e["exp_bps"] - ef["exp_bps"],
                        frictionless_exp=np.nanmean(x + 6.5 + np.array([{"stop": 8.5, "tp": 1.5, "time": 6.5}.get(k, np.nan) for k in kind])),
                        share_tp=np.mean(kind == "tp"), share_stop=np.mean(kind == "stop")))
exits = pd.DataFrame(ex_rows)
exits = pd.concat([pd.DataFrame([dict(exit="EXISTING (actual production exits, real fills)", n=len(trsig), exp_bps_S1like=trsig.net_bps.mean(),
                                      frictionless_exp=trsig.mid_bps.mean())]), exits])
print(exits.to_string(index=False))

# ------------------------------------------------------------ WALK-FORWARD RULE SELECTION (sections 7, 14, 15)
print("\n=== 15. WALK-FORWARD RULE SELECTION — chosen on VALIDATION (max mean net S1, >=30 signals & >=20 bars), reported on OOS ===")
for df in (allsig, trsig):
    df["atr_bps"] = df.atr_14 * 1e4
of_sig = {}
for p, thr, v in itertools.product((5, 10, 20), (0.2, 0.45), (1.0, 1.4)):
    f = bars[(bars[f"fi{p}"].abs() > thr) & (bars.vr20 > v)].copy()
    f["side"] = np.where(f[f"fi{p}"] > 0, "LONG", "SHORT"); f["family"] = f"OF_bar_p{p}_t{thr}_v{v}"
    f["atr_bps"] = f.atr_bps; f["conf"] = f[f"fi{p}"].abs()
    of_sig[f.family.iat[0] if len(f) else f"OF{p}"] = add_forward(f[["bar", "side", "family", "atr_bps", "conf", "regime"]].copy(), c, idx)


def cooldown(df, minutes):
    if minutes == 0:
        return df
    keep = []
    for _, g in df.sort_values("bar").groupby(["family", "side"]):
        last = -10**18
        for b, i in zip(g.bar.to_numpy(), g.index):
            if b - last >= minutes * 60_000:
                keep.append(i); last = b
    return df.loc[keep]


UNIVERSES = {"TRADED_ALL": trsig, "ALLSIG_ALL": allsig}
for fam in trsig.family.unique():
    if (trsig.family == fam).sum() >= 100:
        UNIVERSES[f"TRADED_{fam}"] = trsig[trsig.family == fam]
UNIVERSES.update({k: v for k, v in of_sig.items()})


def rules():
    for uni in UNIVERSES:
        for h in HORIZONS:
            for mm in (0, 5, 10, 15, 20, 30, 50):
                for topq in (1.0, 0.75, 0.5, 0.25, 0.1):
                    for cd in (0, 15, 60):
                        yield dict(universe=uni, horizon=h, min_move=mm, top_conf=topq, cooldown=cd)


def apply(rule, part_df, conf_thr):
    d = part_df
    if rule["min_move"]:
        d = d[d.atr_bps * np.sqrt(rule["horizon"]) >= rule["min_move"] + 0]  # expected |move| over horizon (ATR*sqrt(h))
    if rule["top_conf"] < 1.0 and conf_thr is not None:
        d = d[d.conf >= conf_thr]
    d = cooldown(d, rule["cooldown"])
    return d


wf_rows, sel_rows = [], []
for fold in FOLDS:
    best = {sc: None for sc in ("S1_current", "S6_plausible_maker")}
    cache = {}
    for rule in rules():
        uni = UNIVERSES[rule["universe"]]
        tr, va, oo = fold_parts(uni, fold)
        conf_thr = tr.conf.quantile(1 - rule["top_conf"]) if rule["top_conf"] < 1.0 and tr.conf.notna().any() else None
        dv = apply(rule, va, conf_thr)
        x = dv[f"fwd_{rule['horizon']}"].dropna()
        if len(x) < 30 or dv.bar.nunique() < 20:
            continue
        for sc in best:
            v = x.mean() - COSTS[sc]
            if best[sc] is None or v > best[sc][0]:
                best[sc] = (v, rule, conf_thr)
    for sc, (vexp, rule, conf_thr) in best.items():
        uni = UNIVERSES[rule["universe"]]
        tr, va, oo = fold_parts(uni, fold)
        do = apply(rule, oo, conf_thr)
        x = do[f"fwd_{rule['horizon']}"].dropna() - COSTS[sc]
        e = econ(x.to_numpy())
        drift = np.mean(period_drift(do, rule["horizon"])) if len(do) else np.nan
        q = pd.qcut(do.bar.rank(method="first"), 4, labels=False) if len(do) >= 8 else None
        qs = (do[f"fwd_{rule['horizon']}"] - COSTS[sc]).groupby(q).mean() if q is not None else pd.Series(dtype=float)
        sel_rows.append(dict(fold=fold, cost_scenario=sc, **rule, val_exp=vexp, oos_n=e.get("n", 0), oos_bars=do.bar.nunique(),
                             oos_exp=e.get("exp_bps"), oos_pf=e.get("pf"), oos_wr=e.get("win_rate"), oos_sum_bps=e.get("net_bps_sum"),
                             oos_dd_bps=e.get("max_dd_bps"), oos_avg_win=e.get("avg_win"), oos_avg_loss=e.get("avg_loss"),
                             oos_t=cluster_t(x, block2h(do.bar.loc[x.index]))[0] if len(x) > 2 else np.nan,
                             oos_drift_part=drift, oos_exp_ex_drift=(e.get("exp_bps", np.nan) - drift) if len(do) else np.nan,
                             oos_quarters_pos=int((qs > 0).sum()), oos_exp_at_S1=(do[f"fwd_{rule['horizon']}"].dropna() - S1).mean()))
sel = pd.DataFrame(sel_rows)
print(sel.to_string(index=False))

# Marginal experiments (fixed choices, validation-picked parameter per dimension) — answers sections 7 and 14 directly
print("\n=== 7/14. MARGINAL EFFECTS on TRADED_ALL (and order_flow), pooled over the three OOS windows ===")
marg = []
for uni_name in ["TRADED_ALL", "TRADED_order_flow", "ALLSIG_ALL"]:
    uni = UNIVERSES[uni_name]
    oos = pd.concat([fold_parts(uni, f)[2] for f in FOLDS])
    for h in (10, 30, 60):
        for mm in (0, 5, 10, 15, 20, 30, 50):
            d = oos[oos.atr_bps * np.sqrt(h) >= mm]
            e = econ((d[f"fwd_{h}"] - S1).dropna())
            marg.append(dict(universe=uni_name, dim="min_expected_move", horizon=h, param=mm, retained=len(d), pct_retained=len(d) / len(oos),
                             win_rate=e.get("win_rate"), pf=e.get("pf"), exp_S1=e.get("exp_bps"), sum_bps=e.get("net_bps_sum"), dd_bps=e.get("max_dd_bps"),
                             frictionless=d[f"fwd_{h}"].mean()))
        for q in (1.0, 0.75, 0.5, 0.25, 0.1):
            thr = oos.conf.quantile(1 - q) if q < 1 else -np.inf  # NOTE descriptive only (in-window quantile)
            d = oos[oos.conf >= thr]
            e = econ((d[f"fwd_{h}"] - S1).dropna())
            marg.append(dict(universe=uni_name, dim="top_confidence(descriptive)", horizon=h, param=q, retained=len(d), pct_retained=len(d) / len(oos),
                             win_rate=e.get("win_rate"), pf=e.get("pf"), exp_S1=e.get("exp_bps"), sum_bps=e.get("net_bps_sum"), dd_bps=e.get("max_dd_bps"),
                             frictionless=d[f"fwd_{h}"].mean()))
        for cd in (0, 5, 15, 30, 60):
            d = cooldown(oos, cd)
            e = econ((d[f"fwd_{h}"] - S1).dropna())
            marg.append(dict(universe=uni_name, dim="cooldown_min", horizon=h, param=cd, retained=len(d), pct_retained=len(d) / len(oos),
                             win_rate=e.get("win_rate"), pf=e.get("pf"), exp_S1=e.get("exp_bps"), sum_bps=e.get("net_bps_sum"), dd_bps=e.get("max_dd_bps"),
                             frictionless=d[f"fwd_{h}"].mean()))
marg = pd.DataFrame(marg)
print(marg.to_string(index=False))

# exit selection walk-forward
print("\n=== 13b. EXIT CONFIG chosen on VALIDATION, OOS result (traded signals) ===")
xr = []
for fold in FOLDS:
    tr, va, oo = fold_parts(trsig.assign(_i=np.arange(len(trsig))), fold)
    bestx = max(ex_store, key=lambda k: np.nanmean(ex_store[k][va._i.to_numpy()]))
    xo = ex_store[bestx][oo._i.to_numpy()]
    e = econ(xo)
    xr.append(dict(fold=fold, exit=bestx, val_exp=np.nanmean(ex_store[bestx][va._i.to_numpy()]), oos_n=e["n"], oos_exp=e["exp_bps"], oos_pf=e["pf"],
                   oos_wr=e["win_rate"], existing_exit_oos=oo.net_bps.mean()))
xdf = pd.DataFrame(xr); print(xdf.to_string(index=False))
exits.to_csv(f"{OUT}/exit_analysis.csv", index=False)
xdf.to_csv(f"{OUT}/exit_walkforward.csv", index=False)
sel.to_csv(f"{OUT}/walkforward_selection.csv", index=False)
marg.to_csv(f"{OUT}/min_move_frequency_analysis.csv", index=False)

# ------------------------------------------------------------ 17. success criteria
print("\n=== 17. SUCCESS CRITERIA on validation-selected rules (S1 realistic cost) ===")
s1 = sel[sel.cost_scenario == "S1_current"]
crit = dict(
    R1_positive_net_all_folds=bool((s1.oos_exp > 0).all()), R1_folds_positive=int((s1.oos_exp > 0).sum()),
    R2_pf_gt1_all_folds=bool((s1.oos_pf > 1).all()),
    R3_pooled_oos_exp=float((s1.oos_exp * s1.oos_n).sum() / s1.oos_n.sum()),
    R4_quarters_positive=list(s1.oos_quarters_pos),
    R5_min_oos_bars=int(s1.oos_bars.min()),
    R7_same_rule_selected_each_fold=s1[["universe", "horizon", "min_move", "top_conf", "cooldown"]].drop_duplicates().shape[0] == 1,
)
print(crit)
s6 = sel[sel.cost_scenario == "S6_plausible_maker"]
print("S6 (plausible maker) selected rules: folds positive", int((s6.oos_exp > 0).sum()), " pooled",
      round(float((s6.oos_exp * s6.oos_n).sum() / max(1, s6.oos_n.sum())), 2), " same rules evaluated at S1:", list(s6.oos_exp_at_S1.round(2)))
