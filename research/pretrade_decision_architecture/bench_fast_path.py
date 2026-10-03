"""latency_after.csv — MEASURED compute latency of the proposed fast path on this research machine, using the real
production feature/strategy code and the real generation-6 population (497 DNAs) on real stored bars.

Fast path per confirmed bar (no LLM):  features -> population indicators -> 497 x evaluate_signal ->
PreTradeDecision for every signal -> ExecutionGate.validate.  Each stage timed with perf_counter.
Run from backend/ with DATABASE_URL pointing at the isolated research DB.
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(OUT, "..", "..", "backend")))
from app.market.feature_engine import compute_features, FEATURE_WINDOW  # noqa: E402
from app.schemas.strategy_dna import StrategyDNA  # noqa: E402
from app.strategies.engine import build_feature_view, compute_population_features, evaluate_signal  # noqa: E402
from app.pretrade import ExecutionGate, GateConfig, MarketSnapshot, new_decision  # noqa: E402

conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
C = pd.read_sql("select open_time, open, high, low, close, volume, funding_rate, open_interest from market_candles "
                "where symbol='SOL' and timeframe='1m' and is_final order by open_time", conn)
dnas = [StrategyDNA.model_validate(json.loads(d)) for d in pd.read_sql(
    "select sv.dna::text d from agents a join strategy_versions sv on sv.id=a.strategy_version_id where a.generation=6", conn).d]
gate = ExecutionGate(GateConfig())
rng = np.random.default_rng(7)
bars = sorted(rng.choice(np.arange(FEATURE_WINDOW + 5, len(C) - 2), 150, replace=False))
rows = []
for k in bars:
    win = C.iloc[k - FEATURE_WINDOW + 1: k + 1]
    t0 = time.perf_counter()
    ctx = compute_features(win, symbol="SOL", timeframe="1m")
    prev = compute_features(win.iloc[:-1], symbol="SOL", timeframe="1m")
    t1 = time.perf_counter()
    cur, prv = compute_population_features(win, dnas)
    t2 = time.perf_counter()
    view = build_feature_view(ctx, prev, cur, prv)
    sigs = [evaluate_signal(d, view) for d in dnas]
    t3 = time.perf_counter()
    bar = int(C.open_time.iat[k]); now = bar + 60_000 + 2_500
    decs = [new_decision(agent_id=str(i), symbol="SOL", direction=s.bias.value, signal_bar_open_time_ms=bar,
                         reference_price=ctx.close_price, strategy=d.strategy_family.value, feature_version="fe_v2",
                         now_ms=now, regime=ctx.regime.regime.value, confidence=s.confidence)
            for i, (d, s) in enumerate(zip(dnas, sigs)) if s.matched_entry]
    t4 = time.perf_counter()
    m = MarketSnapshot(now_ms=now + 5, current_signal_bar_ms=bar, current_price=float(C.open.iat[k + 1]))
    res = [gate.validate(d, m) for d in decs]
    t5 = time.perf_counter()
    rows.append(dict(bar=bar, signals=len(decs), features_ms=(t1 - t0) * 1e3, population_indicators_ms=(t2 - t1) * 1e3,
                     strategy_eval_497_ms=(t3 - t2) * 1e3, decision_records_ms=(t4 - t3) * 1e3,
                     gate_all_ms=(t5 - t4) * 1e3, gate_per_decision_us=(np.mean([r.validation_us for r in res]) if res else np.nan),
                     fast_path_total_ms=(t5 - t0) * 1e3))
B = pd.DataFrame(rows)
B.to_csv(f"{OUT}/latency_after_bench_raw.csv", index=False)
summ = B.drop(columns="bar").describe(percentiles=[.5, .9, .99]).T[["mean", "50%", "90%", "99%", "max"]]
summ.to_csv(f"{OUT}/latency_after_bench_summary.csv")
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
print(f"population: {len(dnas)} DNAs; bars benchmarked: {len(B)}")
print(summ.to_string())
