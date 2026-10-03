"""Phase 2 sections 2-6, 9-12: integrity, clean baseline, effective sample size, horizon, costs,
strategy/regime/direction, entry quality. Writes CSVs next to this file."""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "entry_quality_2026-10-02"))
from p2lib import (D, OUT, HORIZONS, COSTS, candles, add_forward, cluster_t, econ, block2h, T)
import lib as eqlib  # phase-1 loader (anomaly flags, bps columns)

eqlib.D = D
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 300)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
c = candles()
idx = pd.Series(np.arange(len(c)), index=c.open_time)
END = pd.Timestamp(int(c.open_time.max()) + 60_000, unit="ms", tz="UTC")

# ---------------------------------------------------------------- 2. integrity
t_all = eqlib.load_trades()
ag = pd.read_parquet(f"{D}/agents.parquet")
print("=== 2. DATA INTEGRITY (backup is a static snapshot: anomalies are present in it by definition) ===")
stale = t_all[t_all.flag_stale_rollover]
print(f"stale-rollover trades: {len(stale)}  closed<opened: {(t_all.closed_at < t_all.opened_at).sum()}  net distortion ${stale.net_pnl.sum():.2f}")
print("stale-rollover by rollover time:", stale.groupby(stale.closed_at.dt.floor('min')).size().to_dict())
print("other rollovers (clean):", t_all[t_all.is_rollover & ~t_all.flag_stale_rollover].groupby(t_all.closed_at.dt.floor('min')).size().to_dict())
print("missing analytics rows:", t_all.family.isna().sum(), " of which rollover:", (t_all.family.isna() & t_all.is_rollover).sum())
rp = t_all.groupby("agent_id").net_pnl.sum()
ag["d_real"] = ag.realized_pnl - ag.agent_id.map(rp).fillna(0)
ag["d_bal"] = ag.balance - (ag.starting_balance + ag.realized_pnl)
ag["has_stale"] = ag.agent_id.isin(stale.agent_id)
print("ledger mismatches realized!=sum(net):", (ag.d_real.abs() > 1e-4).sum(), " all with stale trade:", ag[ag.d_real.abs() > 1e-4].has_stale.all())
drift = ag[ag.d_bal.abs() > 1e-4]
print("balance drift agents:", len(drift), " by gen:", drift.generation.value_counts().sort_index().to_dict(),
      " total $", round(drift.d_bal.sum(), 4), " max |$|", round(drift.d_bal.abs().max(), 4))
# does drift relate to funding or entry fee of open-at-retire position?
print("research population impact: stale trades are", f"{len(stale)/len(t_all):.2%}", "of trades; excluded from all research below")

# ---------------------------------------------------------------- 3. clean dataset & effective sample size
t = t_all[~t_all.is_rollover & t_all.family.notna()].copy()
t["bar"] = t.signal_bar_open_time_ms.astype("int64")
print("\n=== 3. CLEAN RESEARCH DATASET ===")
print(f"candles: {len(c)}  {pd.to_datetime(c.open_time.min(), unit='ms', utc=True)} -> {pd.to_datetime(c.open_time.max(), unit='ms', utc=True)}")
print(f"trades raw {len(t_all)} | removed: stale-rollover {len(stale)}, clean rollover {(t_all.is_rollover & ~t_all.flag_stale_rollover).sum()}, "
      f"no analytics {(t_all.family.isna() & ~t_all.is_rollover).sum()} | usable {len(t)}")
print(f"trade range {t.opened_at.min()} -> {t.closed_at.max()} | agents {t.agent_id.nunique()} | generations {t.generation.nunique()}")
print(f"unique signal bars {t.bar.nunique()} | unique (bar,side) {t.groupby(['bar','side']).ngroups} | unique (bar,family,side) {t.groupby(['bar','family','side']).ngroups}")
tpb = t.groupby("bar").size()
print("trades per signal bar: mean %.1f median %d p90 %d max %d" % (tpb.mean(), tpb.median(), tpb.quantile(.9), tpb.max()))
# ICC of net_bps within (bar, side) clusters -> Kish design effect
g = t.groupby(["bar", "side"]).net_bps
k = g.transform("size"); mu = t.net_bps.mean()
ss_b = (g.transform("mean") - mu).pow(2).groupby([t.bar, t.side]).first().mul(g.size()).sum()
ss_w = (t.net_bps - g.transform("mean")).pow(2).sum()
G, N = g.ngroups, len(t)
msb, msw = ss_b / (G - 1), ss_w / (N - G)
m0 = (N - (g.size() ** 2).sum() / N) / (G - 1)
icc = (msb - msw) / (msb + (m0 - 1) * msw)
deff = 1 + (m0 - 1) * icc
print(f"ICC(net_bps | bar,side)={icc:.3f}  avg cluster size m0={m0:.1f}  design effect={deff:.1f}  Kish effective n={N/deff:.0f}")
hrs = t.bar // 3600_000
print(f"distinct trading hours {hrs.nunique()} | distinct 2h blocks {block2h(t.bar).__len__() and pd.Series(block2h(t.bar)).nunique()}")
fam_hr = t.groupby(["family", hrs]).net_bps.mean().unstack(0)
print("autocorr of hourly mean net_bps (lag1):", round(t.groupby(hrs).net_bps.mean().autocorr(1), 3))
print("between-generation sd of mean net_bps:", round(t.groupby("generation").net_bps.mean().std(), 2),
      " between-family sd:", round(t.groupby("family").net_bps.mean().std(), 2))
ess = dict(trades=N, unique_bars=t.bar.nunique(), unique_bar_side=G, icc=icc, design_effect=deff, kish_ess=N / deff,
           hours=hrs.nunique(), blocks_2h=pd.Series(block2h(t.bar)).nunique())

# ---------------------------------------------------------------- 4. baseline
print("\n=== 4. BASELINE (clean, trade-level, $ and bps) ===")
t["slip_bps"] = t.slippage_cost / t.notional * 1e4
t["mid_bps"] = t.gross_bps + t.slip_bps
K = ["trades", "win_rate", "pf", "exp", "exp_bps", "gross_exp_bps", "net", "gross_profit", "gross_loss", "fees", "funding",
     "avg_win", "avg_loss", "payoff", "be_wr", "max_dd", "hold_avg_min", "hold_med_min"]
rows = []
def base_row(name, d, window):
    m = eqlib.metrics(d)
    rows.append(dict(segment=name, window=window, slippage=d.slippage_cost.sum(), gross_pnl=d.gross_pnl.sum(),
                     **{k: m.get(k) for k in K}))
first, last = t.signal_ts.min(), t.signal_ts.max()
base_row("ALL", t, f"{first} -> {last}")
for h in (72, 48, 24):
    s = END - pd.Timedelta(hours=h); base_row(f"LAST_{h}h", t[t.closed_at > s], f"closed > {s}")
g6 = t[t.generation == 6]; base_row("GEN_6", g6, f"{g6.opened_at.min()} -> {g6.closed_at.max()}")
for f_, d in t.groupby("family"): base_row(f"family={f_}", d, "all")
for r_, d in t.groupby("regime"): base_row(f"regime={r_}", d, "all")
for s_, d in t.groupby("side"): base_row(f"side={s_}", d, "all")
baseline = pd.DataFrame(rows)
print(baseline.to_string(index=False))
baseline.to_csv(f"{OUT}/baseline_analysis.csv", index=False)

# ---------------------------------------------------------------- signal tables
rg = pd.read_parquet(f"{D}/regimes.parquet").sort_values("candle_open_time")
feat = pd.read_parquet(f"{D}/feature_frame.parquet")
dec = pd.read_parquet(f"{D}/decisions.parquet")
dec = dec[dec.bar.notna()].copy(); dec["bar"] = dec.bar.astype("int64"); dec["side"] = dec.sig
def sig_table(df, extra):
    s = df.groupby(["bar", "family", "side"]).agg(n_agents=("side", "size"), **extra).reset_index()
    s = pd.merge_asof(s.sort_values("bar"), rg[["candle_open_time", "regime"]].rename(columns={"candle_open_time": "rbar"}),
                      left_on="bar", right_on="rbar", direction="backward")
    s = s.merge(feat[["open_time", "atr_14", "atr_pctile", "rsi_14", "ret_10", "volume_ratio", "bb_width"]].rename(columns={"open_time": "bar"}), on="bar", how="left")
    return add_forward(s, c, idx)
allsig = sig_table(dec, dict(conf=("conf", "mean"), setup=("setup_strength", "mean"), traded_any=("traded", "max"),
                             approved_share=("risk", lambda x: (x != "REJECTED").mean())))
trsig = sig_table(t, dict(net_bps=("net_bps", "mean"), mid_bps=("mid_bps", "mean"), gross_bps=("gross_bps", "mean"),
                          fee_bps=("fee_bps", "mean"), slip_bps=("slip_bps", "mean"), hold=("holding_seconds", "mean"),
                          conf=("signal_confidence", "mean"), setup=("setup_strength", "mean")))
allsig.to_parquet(f"{D}/p2_allsig.parquet"); trsig.to_parquet(f"{D}/p2_trsig.parquet")
print(f"\nSIGNAL UNIVERSE: all directional decisions {len(dec)} -> unique (bar,family,side) {len(allsig)}; traded unique signals {len(trsig)}")

# ---------------------------------------------------------------- 5/6. horizon + costs
def horizon_rows(sig, label):
    out = []
    blk = block2h(sig.bar)
    for h in HORIZONS:
        x = sig[f"fwd_{h}"].to_numpy()
        tt, n, nb = cluster_t(x, blk)
        r = dict(universe=label, horizon_min=h, n=n, blocks=nb, mean_bps=np.nanmean(x), median_bps=np.nanmedian(x),
                 sd_bps=np.nanstd(x), dir_accuracy=np.nanmean(x > 0), t_cluster=tt,
                 p05=np.nanpercentile(x, 5), p25=np.nanpercentile(x, 25), p75=np.nanpercentile(x, 75), p95=np.nanpercentile(x, 95),
                 mean_abs_move=np.nanmean(np.abs(x)), mfe_mean=np.nanmean(sig[f"mfe_{h}"]), mae_mean=np.nanmean(sig[f"mae_{h}"]),
                 flipped_mean=-np.nanmean(x))
        for sc, cost in COSTS.items():
            e = econ(x - cost)
            r[f"{sc}_exp"] = e["exp_bps"]; r[f"{sc}_pf"] = e["pf"]; r[f"{sc}_wr"] = e["win_rate"]
        out.append(r)
    return out
hz = pd.DataFrame(horizon_rows(allsig, "ALL_SIGNALS") + horizon_rows(trsig, "TRADED_SIGNALS")
                  + sum([horizon_rows(d, f"TRADED|{f_}") for f_, d in trsig.groupby("family") if len(d) > 100], []))
hz.to_csv(f"{OUT}/horizon_analysis.csv", index=False)
print("\n=== 5. SIGNAL HORIZON (signed fwd return from next-bar open, bps; t clustered on 2h blocks) ===")
print(hz[hz.universe.isin(["ALL_SIGNALS", "TRADED_SIGNALS"])][["universe", "horizon_min", "n", "blocks", "mean_bps", "median_bps", "sd_bps",
      "dir_accuracy", "t_cluster", "mean_abs_move", "mfe_mean", "mae_mean", "S1_current_exp", "S6_plausible_maker_exp", "S3_maker_both_exp", "S0_frictionless_pf"]].to_string(index=False))
print("\nTRADED by family, mean fwd bps (t):")
pv = hz[hz.universe.str.startswith("TRADED|")]
print(pv.pivot_table(index="universe", columns="horizon_min", values="mean_bps").round(2).to_string())
print(pv.pivot_table(index="universe", columns="horizon_min", values="t_cluster").round(2).to_string())

print("\n=== 6. COST SENSITIVITY on ACTUAL trades (mid-price outcome minus scenario cost; $ via notional) ===")
crow = []
for sc, cost in {"S1_current(actual fills)": None, "S2_lower_slippage": "fee+2", "S3_maker_both": 3.0, "S4_zero_slippage": "fee",
                 "S5_zero_fee": "slip", "S6_plausible_maker": 8.0, "S0_frictionless": 0.0}.items():
    if cost is None: x = t.net_bps
    elif cost == "fee+2": x = t.mid_bps - t.fee_bps - 2.0
    elif cost == "fee": x = t.mid_bps - t.fee_bps
    elif cost == "slip": x = t.mid_bps - t.slip_bps
    else: x = t.mid_bps - cost
    order = np.argsort(t.closed_at.to_numpy())
    usd = (x * t.notional / 1e4).to_numpy()[order]
    e = econ(x.to_numpy()[order])
    eq = np.cumsum(usd); dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    tq = cluster_t(x, block2h(t.bar))[0]
    crow.append(dict(scenario=sc, level="trade", trades=len(x), exp_bps=e["exp_bps"], t_cluster=tq, pf=e["pf"], win_rate=e["win_rate"],
                     net_usd=usd.sum(), max_dd_usd=dd, avg_win_bps=e["avg_win"], avg_loss_bps=e["avg_loss"], be_wr=e["be_wr"]))
for h in (5, 10, 30, 60):
    for sc, cost in COSTS.items():
        e = econ(trsig[f"fwd_{h}"] - cost)
        crow.append(dict(scenario=sc, level=f"traded_signal_fixed_{h}m_exit", trades=e["n"], exp_bps=e["exp_bps"],
                         t_cluster=cluster_t(trsig[f"fwd_{h}"] - cost, block2h(trsig.bar))[0], pf=e["pf"], win_rate=e["win_rate"],
                         net_usd=np.nan, max_dd_usd=np.nan, avg_win_bps=e["avg_win"], avg_loss_bps=e["avg_loss"], be_wr=e["be_wr"]))
cost_df = pd.DataFrame(crow); cost_df.to_csv(f"{OUT}/cost_analysis.csv", index=False)
print(cost_df[cost_df.level == "trade"].to_string(index=False))
print(cost_df[cost_df.level != "trade"].pivot_table(index="scenario", columns="level", values="exp_bps").round(2).to_string())

# ---------------------------------------------------------------- 9. strategy families
print("\n=== 9. STRATEGY FAMILIES ===")
t["quarter"] = pd.cut(t.bar, np.linspace(t.bar.min(), t.bar.max() + 1, 5), labels=["Q1", "Q2", "Q3", "Q4"])
qb = np.linspace(t.bar.min(), t.bar.max() + 1, 5)
for s_ in (allsig, trsig):
    s_["quarter"] = pd.cut(s_.bar, qb, labels=["Q1", "Q2", "Q3", "Q4"])
print("quarters:", [str(pd.to_datetime(int(x), unit='ms', utc=True)) for x in qb])
srow = []
for f_, d in t.groupby("family"):
    sg = trsig[trsig.family == f_]; asg = allsig[allsig.family == f_]
    m = eqlib.metrics(d)
    order = d.sort_values("closed_at")
    r = dict(family=f_, signals_all=len(asg), signals_traded=len(sg), trades=len(d), win_rate=m["win_rate"], gross_exp_bps=d.gross_bps.mean(),
             mid_exp_bps=d.mid_bps.mean(), net_exp_bps=d.net_bps.mean(), pf=m["pf"], net_usd=m["net"], avg_abs_move30=np.nanmean(np.abs(sg.fwd_30)),
             hold_min=d.holding_seconds.mean() / 60, fee_bps=d.fee_bps.mean(), slip_bps=d.slip_bps.mean(), max_dd_usd=m["max_dd"],
             t_mid=cluster_t(d.mid_bps, block2h(d.bar))[0], allsig_fwd30=asg.fwd_30.mean(), allsig_fwd30_t=cluster_t(asg.fwd_30, block2h(asg.bar))[0])
    for q, dq in d.groupby("quarter", observed=True):
        r[f"{q}_net_bps"] = dq.net_bps.mean(); r[f"{q}_mid_bps"] = dq.mid_bps.mean(); r[f"{q}_n"] = len(dq)
    for q, dq in asg.groupby("quarter", observed=True):
        r[f"{q}_allsig_fwd30"] = dq.fwd_30.mean()
    r["quarters_mid_pos"] = sum(1 for q in "1234" if r.get(f"Q{q}_mid_bps", -1) > 0)
    r["quarters_net_pos"] = sum(1 for q in "1234" if r.get(f"Q{q}_net_bps", -1) > 0)
    srow.append(r)
strat = pd.DataFrame(srow).sort_values("mid_exp_bps", ascending=False)
strat.to_csv(f"{OUT}/strategy_analysis.csv", index=False)
print(strat[["family", "signals_all", "signals_traded", "trades", "win_rate", "gross_exp_bps", "mid_exp_bps", "t_mid", "net_exp_bps", "pf", "net_usd",
             "hold_min", "fee_bps", "slip_bps", "max_dd_usd", "Q1_mid_bps", "Q2_mid_bps", "Q3_mid_bps", "Q4_mid_bps", "quarters_mid_pos", "quarters_net_pos",
             "allsig_fwd30", "allsig_fwd30_t"]].to_string(index=False))

# ---------------------------------------------------------------- 10. regimes + strategy x regime x side
print("\n=== 10. REGIMES (traded signals; fwd at 10/30/60m frictionless & S1) ===")
rrow = []
def seg_rows(keys, df_sig, df_tr, level):
    for k, d in df_sig.groupby(keys):
        if len(d) < 30: continue
        k = k if isinstance(k, tuple) else (k,)
        trd = df_tr.set_index(keys).loc[[k if len(k) > 1 else k[0]]] if False else None
        r = dict(level=level, **dict(zip(keys, k)), signals=len(d), bars=d.bar.nunique())
        for h in (10, 30, 60):
            x = d[f"fwd_{h}"]
            r[f"fwd{h}"] = x.mean(); r[f"fwd{h}_t"] = cluster_t(x, block2h(d.bar))[0]; r[f"fwd{h}_S1"] = (x - 13.5).mean()
            r[f"mfe{h}"] = d[f"mfe_{h}"].mean(); r[f"mae{h}"] = d[f"mae_{h}"].mean()
        if "net_bps" in d:
            r["actual_net_bps"] = d.net_bps.mean(); r["actual_mid_bps"] = d.mid_bps.mean(); r["trades"] = int(d.n_agents.sum())
            r["actual_wr"] = np.nan
        for q, dq in d.groupby("quarter", observed=True):
            r[f"{q}_fwd30"] = dq.fwd_30.mean(); r[f"{q}_n"] = len(dq)
        r["quarters_fwd30_pos"] = sum(1 for q in "1234" if r.get(f"Q{q}_fwd30", -1) > 0)
        r["quarters_fwd30_gt_cost"] = sum(1 for q in "1234" if r.get(f"Q{q}_fwd30", -1) > 13.5)
        rrow.append(r)
seg_rows(["regime"], trsig, t, "regime|traded")
seg_rows(["regime"], allsig, t, "regime|all_signals")
seg_rows(["family", "regime", "side"], trsig, t, "fam_regime_side|traded")
seg_rows(["family", "regime", "side"], allsig, t, "fam_regime_side|all_signals")
reg = pd.DataFrame(rrow); reg.to_csv(f"{OUT}/regime_analysis.csv", index=False)
print(reg[reg.level.str.startswith("regime")][["level", "regime", "signals", "bars", "fwd10", "fwd30", "fwd30_t", "fwd60", "fwd60_t", "fwd30_S1", "mfe30", "mae30",
      "actual_net_bps", "Q1_fwd30", "Q2_fwd30", "Q3_fwd30", "Q4_fwd30"]].to_string(index=False))
frs = reg[reg.level.str.startswith("fam_regime_side")]
for lv in ["fam_regime_side|traded", "fam_regime_side|all_signals"]:
    d = frs[(frs.level == lv) & (frs.bars >= 30)]
    print(f"\n{lv}: combos(bars>=30)={len(d)}  fwd30>cost(13.5) overall={int((d.fwd30 > 13.5).sum())}  "
          f"positive fwd30 in all 4 quarters={int((d.quarters_fwd30_pos == 4).sum())}  >cost in >=3 quarters={int((d.quarters_fwd30_gt_cost >= 3).sum())}  |t|>2.5 & fwd30>0: {int(((d.fwd30_t > 2.5)).sum())}")
    print(d.sort_values("fwd30", ascending=False).head(12)[["family", "regime", "side", "signals", "bars", "fwd30", "fwd30_t", "fwd60", "fwd60_t",
          "Q1_fwd30", "Q2_fwd30", "Q3_fwd30", "Q4_fwd30", "quarters_fwd30_pos"]].to_string(index=False))

# ---------------------------------------------------------------- 11. direction
print("\n=== 11. DIRECTION (all signals, mean fwd bps by horizon; cluster t at 30m) ===")
allsig["volstate"] = np.where(allsig.atr_pctile > 0.7, "HIGH_VOL", np.where(allsig.atr_pctile < 0.3, "LOW_VOL", "MID_VOL"))
allsig["momstate"] = np.where(np.sign(allsig.ret_10) == np.where(allsig.side == "LONG", 1, -1), "WITH_10m_MOMENTUM", "AGAINST_10m_MOMENTUM")
drow = []
for cond in [None, "family", "regime", "volstate", "momstate"]:
    for k, d in (allsig.groupby(["side"] if cond is None else [cond, "side"])):
        k = k if isinstance(k, tuple) else (k,)
        r = dict(condition=cond or "none", value=k[0] if cond else "-", side=k[-1], signals=len(d))
        for h in HORIZONS: r[f"fwd{h}"] = d[f"fwd_{h}"].mean()
        r["t30"] = cluster_t(d.fwd_30, block2h(d.bar))[0]
        for q, dq in d.groupby("quarter", observed=True): r[f"{q}_fwd30"] = dq.fwd_30.mean()
        drow.append(r)
dirdf = pd.DataFrame(drow); dirdf.to_csv(f"{OUT}/direction_analysis.csv", index=False)
print(dirdf[dirdf.condition.isin(["none", "volstate", "momstate", "regime"])].to_string(index=False))

# ---------------------------------------------------------------- 12. entry quality A/B/C/D
print("\n=== 12. ENTRY QUALITY (traded signals; mid prices; 30m window; cost 13.5) ===")
def classify(d, cost=13.5, flip=False):
    mfe, mae, fwd = (d.mae_30.abs() if flip else d.mfe_30), (d.mfe_30 if flip else d.mae_30.abs()), (-d.fwd_30 if flip else d.fwd_30)
    cls = np.select([mfe < 5, mfe < cost, fwd < cost], ["A_bad_direction", "B_insufficient_magnitude", "C_poor_persistence"], "G_reached_cost_and_held")
    return pd.Series(cls, index=d.index)
trsig["eq_class"] = classify(trsig); trsig["eq_class_flipped"] = classify(trsig, flip=True)
erow = []
for col, lab in [("eq_class", "actual_direction"), ("eq_class_flipped", "OPPOSITE_direction_benchmark")]:
    vc = trsig[col].value_counts(normalize=True)
    for k_, v in vc.items(): erow.append(dict(view=lab, cls=k_, share=v))
ent = pd.DataFrame(erow).pivot_table(index="cls", columns="view", values="share")
print(ent.to_string())
# D: theoretical edge exists but execution destroys it
d_share = ((trsig.mid_bps > 0) & (trsig.net_bps <= 0)).mean()
print(f"D_execution: signals with mid-price P&L > 0 but net <= 0: {d_share:.3f} | mean mid {trsig.mid_bps.mean():.2f} vs net {trsig.net_bps.mean():.2f} bps")
print("first-bar adverse (mae_1 < -mfe_1):", round((trsig.mae_1.abs() > trsig.mfe_1).mean(), 3),
      " | flipped benchmark:", round((trsig.mfe_1 > trsig.mae_1.abs()).mean(), 3))
print("median bars to MFE60 / MAE60:", trsig.bars_to_mfe_60.median(), "/", trsig.bars_to_mae_60.median())
eq_rows = []
for h in HORIZONS:
    eq_rows.append(dict(horizon=h, mfe=trsig[f"mfe_{h}"].mean(), mae=trsig[f"mae_{h}"].mean(), fwd=trsig[f"fwd_{h}"].mean(),
                        share_mfe_gt_cost=(trsig[f"mfe_{h}"] > 13.5).mean(), share_mae_gt_cost=(trsig[f"mae_{h}"] < -13.5).mean(),
                        mfe_minus_abs_mae=(trsig[f"mfe_{h}"] + trsig[f"mae_{h}"]).mean()))
eqd = pd.DataFrame(eq_rows)
print(eqd.to_string(index=False))
pd.concat([eqd.assign(table="excursion_by_horizon"), ent.reset_index().assign(table="class_shares_30m"),
           pd.DataFrame([dict(table="D_execution", share=d_share, mid=trsig.mid_bps.mean(), net=trsig.net_bps.mean())])]).to_csv(f"{OUT}/entry_analysis.csv", index=False)
pd.Series(ess).to_csv(f"{OUT}/effective_sample_size.csv")
print("\nDONE")
