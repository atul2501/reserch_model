"""Historical SHADOW replay: OLD architecture (as recorded) vs NEW pre-computed / fast-path architecture, for every
candidate entry signal in the backup. Writes shadow_comparison.csv, decision_freshness.csv, price_drift.csv,
latency_after.csv. Read-only.

WHAT IS MEASURED vs MODELLED
  measured : old decision/order wall-clock time per signal (decisions/orders created_at), per-cycle wait for the
             confirmed bar and feature time (worker_cycles, market_features), council run/complete times,
             fast-path compute (bench_fast_path.py), bar-K+1 OHLC.
  modelled : the SOL price at a sub-minute instant (no tick history exists in the backup or from the exchange API).
             Estimated by a Brownian bridge from bar K+1 open to close with Parkinson volatility from the bar's
             high/low, clamped to [low, high], seeded. An EXACT bound is also reported: inside bar K+1 the price can
             never be further from the open than max(high-open, open-low), so "guaranteed within tolerance" is exact.
  Information boundary: both architectures decide from bar K (cutoff = K close). Bar K+1 data is used ONLY to
  measure what the price did after the decision (evaluation), never as a decision input.
"""
import json, os, sys
import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(OUT, "..", "phase2_signal_horizon"))
from p2lib import cluster_t, block2h  # noqa: E402

AGE_GRID_S = [1, 2, 5, 10, 15, 30]
DRIFT_GRID_BPS = [2, 5, 10, 15, 20]
COUNCIL_AGE_GRID_S = [30, 60, 120, 300]
DEFAULT_AGE_S, DEFAULT_DRIFT = 5, 10                     # research defaults for the gate verdict column only
rng = np.random.default_rng(20261002)
conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
q = lambda s: pd.read_sql(s, conn)

C = q("select open_time, open, high, low, close from market_candles where symbol='SOL' and timeframe='1m' and is_final order by open_time")
CI = C.set_index("open_time")
cyc = q("select candle_timestamp bar, cycle_started_at, council_required from worker_cycles where status='COMPLETED'")
mf = q("select candle_open_time bar, extract(epoch from created_at) feat_at from market_features where symbol='SOL'")
cd = q("select market_candle_open_time bar, council_start, council_completed_at, final_bias::text cbias, final_confidence cconf from council_decisions")
for d in (cyc, mf, cd):
    d["bar"] = d.bar.astype("int64")
bench = pd.read_csv(f"{OUT}/latency_after_bench_raw.csv")
fast_compute_ms = bench.fast_path_total_ms.to_numpy()

# ---- candidates: every directional decision that reached sizing (ordered) + council vetoes
cand = q("""
select d.id::text decision_id, d.agent_id::text agent_id, d.market_candle_open_time bar, d.agent_signal::text side,
       extract(epoch from d.created_at) decision_at, d.risk_reasoning->'council'->>'reason' council_reason,
       d.risk_reasoning->>'skipped' skipped, o.id is not null as ordered, o.status::text order_status,
       t.net_pnl, t.entry_price * t.quantity notional, t.exit_reason
from decisions d
left join orders o on o.id = d.order_id and o.reduce_only = false
left join trades t on t.entry_order_id = o.id
where d.agent_signal::text in ('LONG','SHORT') and (d.agent_signal_reasoning->>'protective_only') is null
  and (o.id is not null or d.risk_reasoning->>'skipped' = 'council_directional_conflict')
""")
cand["bar"] = cand.bar.astype("int64")
cand = cand.merge(cyc, on="bar", how="left").merge(mf, on="bar", how="left").merge(cd, on="bar", how="left")
cand["event_at"] = cand.bar / 1000 + 60                                    # bar K close = information cutoff
cand["sgn"] = np.where(cand.side == "LONG", 1.0, -1.0)
cand["ref_price"] = cand.bar.map(CI.close)
nxt = cand.bar + 60_000
cand["o1"], cand["h1"], cand["l1"], cand["c1"] = nxt.map(CI.open), nxt.map(CI.high), nxt.map(CI.low), nxt.map(CI.close)
cand = cand.dropna(subset=["o1", "ref_price"]).reset_index(drop=True)

# ---- OLD timing (measured): decision written at decision_at; a live order would be sent then.
cand["old_decision_age_s"] = cand.decision_at - cand.event_at
# ---- NEW timing: the same cycle's measured wait-for-confirmed-bar + measured feature time + benchmarked fast path.
wait_s = (cand.cycle_started_at - cand.event_at).clip(lower=0)
feat_s = (cand.feat_at - cand.cycle_started_at).clip(lower=0, upper=1.0).fillna(0.024)
cand["new_decision_age_s"] = wait_s + feat_s + rng.choice(fast_compute_ms, len(cand)) / 1e3 - 0.024  # bench includes features
cand["new_decision_age_s"] = cand.new_decision_age_s.clip(lower=wait_s)
# ---- Option B (async council): freshest COMPLETED council available at the new decision instant
cdone = cd.dropna(subset=["council_completed_at"]).sort_values("council_completed_at")
done_t, done_cut = cdone.council_completed_at.to_numpy(), (cdone.bar / 1000 + 60).to_numpy()
idx = np.searchsorted(done_t, (cand.event_at + cand.new_decision_age_s).to_numpy(), side="right") - 1
cand["async_council_age_s"] = np.where(idx >= 0, cand.event_at.to_numpy() + cand.new_decision_age_s.to_numpy() - done_cut[np.maximum(idx, 0)], np.nan)


def bridge_price(tau_s, o, h, l, c):
    """Estimated price tau_s seconds into bar K+1 (0..60): Brownian bridge open->close, Parkinson sigma, clamped."""
    tau = np.clip(tau_s, 0, 60) / 60.0
    sig = np.sqrt(np.maximum(np.log(h / l), 0) ** 2 / (4 * np.log(2)))     # per-bar log-vol (Parkinson)
    mean = np.log(o) + (np.log(c) - np.log(o)) * tau
    sd = sig * np.sqrt(tau * (1 - tau))
    p = np.exp(mean + sd * rng.standard_normal(len(o)))
    return np.clip(p, l, h)


o1, h1, l1, c1 = (cand[k].to_numpy() for k in ("o1", "h1", "l1", "c1"))
cand["old_price_est"] = bridge_price(cand.old_decision_age_s.to_numpy(), o1, h1, l1, c1)
cand["new_price_est"] = bridge_price(cand.new_decision_age_s.to_numpy(), o1, h1, l1, c1)
cand["paper_fill_ref"] = o1                                                # what paper actually filled at (pre-slippage)
sg = cand.sgn.to_numpy(); ref = cand.ref_price.to_numpy()
cand["old_drift_bps"] = (cand.old_price_est / ref - 1) * 1e4 * sg          # + = moved in the trade's favour
cand["new_drift_bps"] = (cand.new_price_est / ref - 1) * 1e4 * sg
cand["drift_bound_bps"] = np.maximum(h1 - o1, o1 - l1) / ref * 1e4 + np.abs(o1 / ref - 1) * 1e4   # exact bound inside bar K+1
# entry improvement of NEW vs OLD (live-equivalent), signed: + = NEW buys cheaper / sells higher
cand["new_vs_old_entry_bps"] = (cand.old_price_est / cand.new_price_est - 1) * 1e4 * sg
cand["paper_optimism_vs_old_live_bps"] = (cand.old_price_est / cand.paper_fill_ref - 1) * 1e4 * sg   # + = paper fill better than live
cand["old_would_trade"] = cand.ordered & (cand.skipped.isna())
cand["new_gate_reasons"] = [
    ";".join(r for r, bad in [("decision_too_old", a > DEFAULT_AGE_S), ("price_moved_too_far", abs(dr) > DEFAULT_DRIFT)] if bad)
    for a, dr in zip(cand.new_decision_age_s, cand.new_drift_bps)]
cand["new_would_trade"] = cand.new_gate_reasons == ""                      # council veto removed: LLM off the path
cand["net_bps_actual"] = cand.net_pnl / cand.notional * 1e4
cand["council_bar"] = cand.council_required.fillna(False).astype(bool)

cols = ["decision_id", "agent_id", "bar", "side", "council_bar", "council_reason", "skipped", "old_would_trade", "new_would_trade",
        "new_gate_reasons", "old_decision_age_s", "new_decision_age_s", "async_council_age_s", "ref_price", "paper_fill_ref",
        "old_price_est", "new_price_est", "old_drift_bps", "new_drift_bps", "drift_bound_bps", "new_vs_old_entry_bps",
        "paper_optimism_vs_old_live_bps", "order_status", "exit_reason", "net_bps_actual"]
cand[cols].to_csv(f"{OUT}/shadow_comparison.csv", index=False)
print(f"candidates: {len(cand)} (ordered {int(cand.ordered.sum())}, council-vetoed {int((cand.skipped == 'council_directional_conflict').sum())}); "
      f"on council bars {cand.council_bar.mean():.3f}")

# ---- decision_freshness.csv
fr = []
for lab, d in [("ALL", cand), ("council_bar", cand[cand.council_bar]), ("non_council_bar", cand[~cand.council_bar])]:
    for s in AGE_GRID_S:
        fr.append(dict(subset=lab, max_decision_age_s=s, n=len(d), old_stale_share=(d.old_decision_age_s > s).mean(),
                       new_stale_share=(d.new_decision_age_s > s).mean()))
    for s in COUNCIL_AGE_GRID_S:
        fr.append(dict(subset=lab, max_decision_age_s=f"async_council<= {s}", n=len(d), old_stale_share=np.nan,
                       new_stale_share=(d.async_council_age_s > s).mean()))
FR = pd.DataFrame(fr); FR.to_csv(f"{OUT}/decision_freshness.csv", index=False)

# ---- price_drift.csv
pdft = []
for lab, d in [("ALL", cand), ("council_bar", cand[cand.council_bar]), ("non_council_bar", cand[~cand.council_bar])]:
    for b in DRIFT_GRID_BPS:
        pdft.append(dict(subset=lab, max_entry_drift_bps=b, n=len(d), old_reject_share_est=(d.old_drift_bps.abs() > b).mean(),
                         new_reject_share_est=(d.new_drift_bps.abs() > b).mean(),
                         guaranteed_within_tolerance_exact=(d.drift_bound_bps <= b).mean()))
    pdft.append(dict(subset=lab, max_entry_drift_bps="summary", n=len(d),
                     old_abs_drift_mean=d.old_drift_bps.abs().mean(), old_abs_drift_p90=d.old_drift_bps.abs().quantile(.9),
                     new_abs_drift_mean=d.new_drift_bps.abs().mean(), new_abs_drift_p90=d.new_drift_bps.abs().quantile(.9),
                     old_signed_drift_mean=d.old_drift_bps.mean(), new_signed_drift_mean=d.new_drift_bps.mean()))
PD = pd.DataFrame(pdft); PD.to_csv(f"{OUT}/price_drift.csv", index=False)

# ---- latency_after.csv (projected per-signal NEW latencies from measured components)
la = []
for lab, d in [("ALL", cand), ("council_bar", cand[cand.council_bar]), ("non_council_bar", cand[~cand.council_bar])]:
    for col in ("old_decision_age_s", "new_decision_age_s"):
        x = d[col] * 1e3
        la.append(dict(subset=lab, metric=col.replace("_s", "_ms"), mean=x.mean(), p50=x.median(), p90=x.quantile(.9), p99=x.quantile(.99), max=x.max()))
LA = pd.DataFrame(la)
bs = pd.read_csv(f"{OUT}/latency_after_bench_summary.csv", index_col=0)
for stage, r in bs.iterrows():
    LA = pd.concat([LA, pd.DataFrame([dict(subset="fast_path_compute_benchmark", metric=stage, mean=r["mean"], p50=r["50%"], p90=r["90%"], p99=r["99%"], max=r["max"])])])
LA.to_csv(f"{OUT}/latency_after.csv", index=False)

# ---- console summary
pd.set_option("display.width", 220); pd.set_option("display.float_format", lambda v: f"{v:.4f}")
print(LA.to_string(index=False)); print(FR.to_string(index=False)); print(PD.to_string(index=False))
traded = cand[cand.old_would_trade & cand.net_bps_actual.notna()]
x = traded.new_vs_old_entry_bps
print(f"\nNEW vs OLD live-equivalent entry (traded signals, n={len(traded)}): mean {x.mean():+.3f} bps (cluster t {cluster_t(x, block2h(traded.bar))[0]:+.2f}); "
      f"council bars {traded[traded.council_bar].new_vs_old_entry_bps.mean():+.3f}, non-council {traded[~traded.council_bar].new_vs_old_entry_bps.mean():+.3f}")
y = traded.paper_optimism_vs_old_live_bps
print(f"Paper fill (bar K+1 open) vs an OLD live order at decision time: mean {y.mean():+.3f} bps (t {cluster_t(y, block2h(traded.bar))[0]:+.2f}) "
      f"| council bars {traded[traded.council_bar].paper_optimism_vs_old_live_bps.mean():+.3f}")
old_net = traded.net_bps_actual
new_set = traded[traded.new_would_trade]
new_net = new_set.net_bps_actual + new_set.new_vs_old_entry_bps
print(f"Hypothetical economics: OLD traded n={len(traded)} mean net {old_net.mean():+.2f} bps | NEW (gate {DEFAULT_AGE_S}s/{DEFAULT_DRIFT}bps) "
      f"n={len(new_set)} ({len(new_set)/len(traded):.3f} of old) mean net {new_net.mean():+.2f} bps; rejected by NEW gate: {1-len(new_set)/len(traded):.3f} "
      f"(their actual net {traded[~traded.new_would_trade].net_bps_actual.mean():+.2f})")
veto = cand[cand.skipped == "council_directional_conflict"]
print(f"Signals the OLD council vetoed that NEW (no LLM gate) would submit: {len(veto)} ({len(veto)/max(1,len(traded)):.4f} of traded volume); "
      f"their outcome is unknown (never traded) - Phase/forensic estimate: fwd30 mid +4.6 bps, i.e. ~ -9 bps after 13.5 bps cost")
