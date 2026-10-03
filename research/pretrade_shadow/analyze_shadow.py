"""Analyse a PRETRADE_MODE=shadow run. Read-only.

Inputs
  raw/*.jsonl                      shadow records written by app.pretrade.shadow (candidate / bar_summary / old_path_point)
  shadow_smoke DB (127.0.0.1:55432) the EXISTING path's own decisions/orders from the same run (old vs new on same bars)
  trading_lab_research_20261002     restored production backup: real council history for the LLM comparison
Outputs: shadow_decisions.csv, shadow_latency.csv, shadow_drift.csv, shadow_gate_rejections.csv, council_comparison.csv
"""
import glob, json, os, sys
import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
COLD_START_BARS = 1     # the first processed bar includes the initial history sync (excluded from steady-state stats)

rows = [json.loads(l) for p in sorted(glob.glob(f"{OUT}/raw/*.jsonl")) for l in open(p, encoding="utf-8") if l.strip()]
R = pd.DataFrame(rows)
cand = R[R.record_type == "candidate"].copy()
bars = R[R.record_type == "bar_summary"].copy()
old = R[R.record_type == "old_path_point"].copy()
bar_order = sorted(bars.signal_bar_open_time_ms.unique())
cold = set(bar_order[:COLD_START_BARS])
cand["cold_start_bar"] = cand.signal_bar_open_time_ms.isin(cold)
bars["cold_start_bar"] = bars.signal_bar_open_time_ms.isin(cold)
print(f"records: {len(R)} | bars: {len(bars)} ({pd.to_datetime(min(bar_order), unit='ms')} -> {pd.to_datetime(max(bar_order), unit='ms')} UTC) "
      f"| candidates: {len(cand)} | old_path_points: {len(old)}")

# ---- safety (shadow side)
assert (cand.orders_created == 0).all()
print("shadow rows with orders_created != 0:", int((cand.orders_created != 0).sum()))

# ---- old path from the same run (scratch DB)
sm = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="shadow_smoke"); sm.set_session(readonly=True)
od = pd.read_sql("""select d.agent_id::text agent_id, d.market_candle_open_time bar, d.agent_signal::text sig, d.risk_decision::text risk,
                           extract(epoch from d.created_at)*1000 old_decision_ms, o.id is not null ordered, o.requested_price
                    from decisions d left join orders o on o.id=d.order_id and o.reduce_only=false
                    where d.agent_signal::text in ('LONG','SHORT')""", sm)
od["bar"] = od.bar.astype("int64")
m = cand.merge(od, left_on=["agent_id", "signal_bar_open_time_ms"], right_on=["agent_id", "bar"], how="left")
cand["old_path_signal"] = m.sig.values
cand["old_path_ordered"] = m.ordered.fillna(False).values
cand["old_path_decision_ms"] = m.old_decision_ms.values
cand["old_path_decision_age_ms"] = cand.old_path_decision_ms - cand.information_cutoff_ms
cand.to_csv(f"{OUT}/shadow_decisions.csv", index=False)

# ---- latency (per bar, measured wall clock; ms after the bar's information cutoff unless noted)
b = bars.copy()
b["event_to_features_start_ms"] = b.features_started_ms - b.market_event_ms
b["feature_ms"] = b.features_completed_ms - b.features_started_ms
b["features_to_signal_ms"] = b.signal_created_ms - b.features_completed_ms
b["signal_to_decision_ms"] = b.decision_ms - b.signal_created_ms
b["decision_to_shadow_execution_ms"] = b.validation_ms - b.decision_ms          # incl. the one public l2Book read
b["signal_to_decision_total_ms"] = b.decision_ms - b.market_event_ms              # bar close -> decision ready
b = b.drop(columns=["old_path_completed_ms"], errors="ignore").merge(old[["signal_bar_open_time_ms", "old_path_completed_ms"]], on="signal_bar_open_time_ms", how="left")
b["old_path_done_ms_after_event"] = b.old_path_completed_ms - b.market_event_ms
lat_cols = ["event_to_features_start_ms", "feature_ms", "features_to_signal_ms", "signal_to_decision_ms",
            "decision_to_shadow_execution_ms", "signal_to_decision_total_ms", "old_path_done_ms_after_event"]
rows = []
for lab, d in [("steady_state", b[~b.cold_start_bar]), ("cold_start_bar", b[b.cold_start_bar])]:
    for c in lat_cols:
        x = d[c].dropna()
        if len(x):
            rows.append(dict(subset=lab, stage=c, n=len(x), mean=x.mean(), p50=x.median(), p90=x.quantile(.9),
                             p99=x.quantile(.99), max=x.max()))
cs = cand[~cand.cold_start_bar]
for c, lab in [("decision_age_ms", "candidate decision age at gate (new path)"),
               ("old_path_decision_age_ms", "old path decision age for the same agent+bar")]:
    x = cs[c].dropna()
    if len(x):
        rows.append(dict(subset="steady_state", stage=lab, n=len(x), mean=x.mean(), p50=x.median(), p90=x.quantile(.9),
                         p99=x.quantile(.99), max=x.max()))
gv = cs.gate_validation_us.dropna()
rows.append(dict(subset="steady_state", stage="gate_validation_us (per decision)", n=len(gv), mean=gv.mean(), p50=gv.median(),
                 p90=gv.quantile(.9), p99=gv.quantile(.99), max=gv.max()))
LAT = pd.DataFrame(rows); LAT.to_csv(f"{OUT}/shadow_latency.csv", index=False)

# ---- drift & spread (real book)
d = cs.dropna(subset=["price_at_shadow_execution_point"])
drift_rows = [dict(metric="candidates_with_book_price", value=len(d), of=len(cs))]
for q in ("signed_drift_bps", "absolute_drift_bps", "spread_bps"):
    x = d[q].dropna()
    drift_rows += [dict(metric=f"{q}_{k}", value=v) for k, v in
                   dict(mean=x.mean(), p50=x.median(), p90=x.quantile(.9), p99=x.quantile(.99), max=x.max(), min=x.min()).items()]
lag = (d.book_received_ms - d.price_at_shadow_execution_point_ts_ms)
drift_rows += [dict(metric="book_exchange_time_lag_ms_vs_receipt_" + k, value=v) for k, v in
               dict(p50=lag.median(), p90=lag.quantile(.9), max=lag.max()).items()]
drift_rows.append(dict(metric="book_price_ts_before_decision_share", value=(d.price_at_shadow_execution_point_ts_ms < d.decision_ms).mean()))
for t in (2, 5, 10, 15, 20):
    drift_rows.append(dict(metric=f"reject_share_if_max_drift_{t}bps", value=(d.absolute_drift_bps > t).mean()))
# decision-time price vs old-path price (same bar), signed in each candidate's direction
op = old.set_index("signal_bar_open_time_ms").price
d2 = d.assign(old_price=d.signal_bar_open_time_ms.map(op)).dropna(subset=["old_price"])
sgn = np.where(d2.direction == "LONG", 1, -1)
delta = (d2.old_price / d2.price_at_shadow_execution_point - 1) * 1e4 * sgn     # + = old path would pay MORE (worse)
drift_rows += [dict(metric="old_path_price_vs_new_decision_price_bps_" + k, value=v) for k, v in
               dict(n=len(delta), mean=delta.mean(), p50=delta.median(), abs_mean=delta.abs().mean()).items()]
DR = pd.DataFrame(drift_rows); DR.to_csv(f"{OUT}/shadow_drift.csv", index=False)

# ---- gate rejections
ex = cs.explode("gate_rejection_reasons")
GR = (ex.gate_rejection_reasons.fillna("<allowed>").value_counts().rename_axis("reason").reset_index(name="count"))
GR["share_of_candidates"] = GR["count"] / len(cs)
GR = pd.concat([GR, pd.DataFrame([dict(reason="<total candidates>", count=len(cs), share_of_candidates=1.0),
                                  dict(reason="<would_trade>", count=int(cs.would_trade.sum()), share_of_candidates=cs.would_trade.mean())])])
risk_ex = cs.explode("risk_reasons").risk_reasons.dropna().value_counts().rename_axis("reason").reset_index(name="count")
risk_ex["reason"] = "risk_detail: " + risk_ex.reason
GR = pd.concat([GR, risk_ex.assign(share_of_candidates=risk_ex["count"] / len(cs))])
GR.to_csv(f"{OUT}/shadow_gate_rejections.csv", index=False)

# ---- agreement old vs new (same run)
agree = cs.dropna(subset=["old_path_signal"])
agreement = dict(candidates=len(cs), with_old_path_decision=len(agree),
                 same_direction=(agree.old_path_signal == agree.direction).mean() if len(agree) else np.nan,
                 new_would_trade_and_old_ordered=int((cs.would_trade & cs.old_path_ordered).sum()),
                 new_would_trade_old_not=int((cs.would_trade & ~cs.old_path_ordered).sum()),
                 old_ordered_new_rejected=int((~cs.would_trade & cs.old_path_ordered).sum()))

# ---- LLM comparison: real council history from the production backup (council disabled in the local run)
bk = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002"); bk.set_session(readonly=True)
cdf = pd.read_sql("select market_candle_open_time bar, final_bias::text bias, final_confidence conf, council_status, council_completed_at "
                  "from council_decisions where council_completed_at is not null order by council_completed_at", bk)
sig = pd.read_sql("""select d.market_candle_open_time bar, d.agent_signal::text side, extract(epoch from d.created_at) dec_at,
                            d.risk_reasoning->'council'->>'reason' reason
                     from decisions d where d.agent_signal::text in ('LONG','SHORT') and d.order_id is not null""", bk)
sig["bar"] = sig.bar.astype("int64"); cdf["bar"] = cdf.bar.astype("int64")
# (a) SAME-BAR council (old architecture, available only after waiting for it)
same = sig.merge(cdf[["bar", "bias", "conf"]], on="bar", how="inner")
# (b) ASYNC council: freshest COMPLETED council available at the new path's decision time (~ bar close + 2.7 s)
ct, cb, cconf = cdf.council_completed_at.to_numpy(), cdf.bias.to_numpy(), cdf.conf.to_numpy()
cut = (cdf.bar.to_numpy() + 60_000) / 1000
dec_new = sig.bar.to_numpy() / 1000 + 60 + 2.7
idx = np.searchsorted(ct, dec_new, side="right") - 1
ok = idx >= 0
asy = sig[ok].assign(bias=cb[idx[ok]], conf=cconf[idx[ok]], age_s=dec_new[ok] - cut[idx[ok]])
cc_rows = []
for lab, x in [("same_bar_council (old path, waited for)", same), ("async_latest_council_at_new_decision_time", asy)]:
    directional = x[x.bias.isin(["LONG", "SHORT"])]
    cc_rows.append(dict(view=lab, signals=len(x), council_neutral_share=(x.bias == "NEUTRAL").mean(),
                        agree_share_of_directional=(directional.bias == directional.side).mean(),
                        disagree_share_of_directional=(directional.bias != directional.side).mean(),
                        disagree_share_of_all=((x.bias.isin(["LONG", "SHORT"])) & (x.bias != x.side)).mean(),
                        would_veto_share=((x.bias.isin(["LONG", "SHORT"])) & (x.bias != x.side) & (x.conf >= 0.60)).mean(),
                        council_age_s_p50=x.age_s.median() if "age_s" in x else np.nan))
CC = pd.DataFrame(cc_rows); CC.to_csv(f"{OUT}/council_comparison.csv", index=False)

pd.set_option("display.width", 220); pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
print(LAT.to_string(index=False)); print(DR.to_string(index=False)); print(GR.to_string(index=False))
print("agreement old vs new (same live run):", agreement); print(CC.to_string(index=False))
json.dump({k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in agreement.items()},
          open(f"{OUT}/old_vs_new_agreement.json", "w"), indent=2)
