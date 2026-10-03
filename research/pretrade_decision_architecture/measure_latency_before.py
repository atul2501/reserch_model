"""Q1/Q3/Q4: measured stage latencies of the CURRENT architecture from wall-clock DB timestamps.

All timestamps are Python-side `utcnow()` at INSERT/UPDATE (models/base.py TimestampMixin) or explicit wall-clock
fields (worker_cycles.cycle_started_at, council_decisions.council_start/council_completed_at). Nothing estimated.
market_event_at = signal-bar close = open_time + 60 s (exchange bar boundary).
"""
import os
import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
q = lambda s: pd.read_sql(s, conn)

cyc = q("""select candle_timestamp bar, cycle_started_at, cycle_completed_at, cycle_latency_seconds, council_required, council_status, agents_processed
           from worker_cycles where status='COMPLETED'""")
mf = q("select candle_open_time bar, extract(epoch from created_at) features_persisted_at from market_features where symbol='SOL'")
cd = q("""select market_candle_open_time bar, council_start, council_completed_at, total_council_latency_seconds council_s, judge_invoked,
                 successful_analysts from council_decisions""")
ca = q("""select c.market_candle_open_time bar, extract(epoch from a.started_at) a_start, extract(epoch from a.completed_at) a_end, a.latency_ms
          from council_analyses a join council_decisions c on c.id=a.council_decision_id""")
ent = q("""select o.signal_candle_open_time bar, extract(epoch from d.created_at) decision_at, extract(epoch from o.created_at) order_created_at,
                  extract(epoch from o.updated_at) order_filled_at, o.status::text status, o.latency_ms sim_latency_ms,
                  o.requested_price ref_price, o.filled_price, o.side::text side
           from orders o join decisions d on d.id=o.decision_id
           where o.reduce_only=false and o.signal_candle_open_time is not null""")
for df in (cyc, mf, cd, ca, ent):
    df["bar"] = df.bar.astype("int64")
cyc["market_event_at"] = cyc.bar / 1000 + 60
c = cyc.merge(mf, on="bar", how="left").merge(cd, on="bar", how="left")
an = ca.groupby("bar").agg(first_analyst_start=("a_start", "min"), last_analyst_end=("a_end", "max"),
                           analyst_p50_ms=("latency_ms", "median"), analyst_max_ms=("latency_ms", "max")).reset_index()
c = c.merge(an, on="bar", how="left")
dec = ent.groupby("bar").agg(first_decision_at=("decision_at", "min"), last_decision_at=("decision_at", "max"),
                             entry_orders=("decision_at", "size")).reset_index()
c = c.merge(dec, on="bar", how="left")
c["wait_for_confirmed_bar_ms"] = (c.cycle_started_at - c.market_event_at) * 1e3
c["feature_latency_ms"] = (c.features_persisted_at - c.cycle_started_at) * 1e3
c["llm_council_latency_ms"] = c.council_s * 1e3
c["llm_slowest_analyst_ms"] = c.analyst_max_ms
c["strategy_risk_to_first_order_ms"] = (c.first_decision_at - np.fmax(c.features_persisted_at, c.council_completed_at.fillna(0))) * 1e3
c["all_agents_decided_ms_after_event"] = (c.last_decision_at - c.market_event_at) * 1e3
c["first_order_ms_after_event"] = (c.first_decision_at - c.market_event_at) * 1e3
c["cycle_total_ms"] = c.cycle_latency_seconds * 1e3
c["cycle_done_ms_after_event"] = (c.cycle_completed_at - c.market_event_at) * 1e3
c.to_csv(f"{OUT}/latency_before_cycles.csv", index=False)

# Per entry order timeline
e = ent.copy()
e["market_event_at"] = e.bar / 1000 + 60
e = e.merge(cd[["bar", "council_start", "council_completed_at"]], on="bar", how="left")
e["council_bar"] = e.council_start.notna()
e["decision_ms_after_event"] = (e.decision_at - e.market_event_at) * 1e3
e["order_created_ms_after_event"] = (e.order_created_at - e.market_event_at) * 1e3
e["fill_processed_ms_after_event"] = (e.order_filled_at - e.market_event_at) * 1e3
# The paper fill PRICE is the open of bar K+1, i.e. the price AT market_event_at. It is therefore this many ms
# OLDER than the decision that "used" it -> optimistic look-ahead of the paper fill vs a live order.
e["paper_fill_price_age_at_decision_ms"] = e.decision_ms_after_event
e.to_csv(f"{OUT}/latency_before_orders.csv", index=False)

def summ(s):
    s = s.dropna()
    return dict(n=len(s), mean=s.mean(), p10=s.quantile(.1), p50=s.median(), p90=s.quantile(.9), p99=s.quantile(.99), max=s.max())
rows = []
for lab, d in [("council_bar", c[c.council_required]), ("non_council_bar", c[~c.council_required])]:
    for col in ["wait_for_confirmed_bar_ms", "feature_latency_ms", "llm_council_latency_ms", "llm_slowest_analyst_ms",
                "strategy_risk_to_first_order_ms", "first_order_ms_after_event", "all_agents_decided_ms_after_event",
                "cycle_total_ms", "cycle_done_ms_after_event"]:
        if d[col].notna().any():
            rows.append(dict(bar_type=lab, stage=col, **summ(d[col])))
for lab, d in [("council_bar", e[e.council_bar]), ("non_council_bar", e[~e.council_bar])]:
    for col in ["decision_ms_after_event", "order_created_ms_after_event", "fill_processed_ms_after_event"]:
        rows.append(dict(bar_type=f"{lab}|entry_orders", stage=col, **summ(d[col])))
    rows.append(dict(bar_type=f"{lab}|entry_orders", stage="simulated_exchange_latency_ms (paper RNG, not real)", **summ(d.sim_latency_ms)))
L = pd.DataFrame(rows)
L.to_csv(f"{OUT}/latency_before.csv", index=False)
pd.set_option("display.width", 220); pd.set_option("display.float_format", lambda v: f"{v:,.0f}")
print(L.to_string(index=False))
print("\ncouncil bars:", int(c.council_required.sum()), " non-council bars:", int((~c.council_required).sum()),
      " councils > 30 s:", int((c.council_s > 30).sum()), " judge invoked:", int(c.judge_invoked.fillna(False).sum()))
print("share of ENTRY ORDERS created on council bars: %.3f" % e.council_bar.mean())
