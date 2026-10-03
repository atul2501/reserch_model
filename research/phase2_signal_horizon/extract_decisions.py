"""Phase 2: extract every directional agent signal (approved, reduced AND rejected) — read-only."""
import os, pandas as pd, psycopg2
D = os.path.join(os.path.dirname(__file__), "data")
conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
SQL = """
select d.agent_id::text agent_id, a.generation, d.market_candle_open_time bar, d.agent_signal::text sig,
       d.final_signal fsig, d.risk_decision::text risk, d.agent_signal_confidence conf,
       (d.agent_signal_reasoning->>'setup_strength')::float setup_strength,
       d.risk_reasoning->'reasons'->>0 reason0, d.council_bias, d.trade_id is not null as traded,
       sv.dna->>'strategy_family' family
from decisions d join agents a on a.id=d.agent_id join strategy_versions sv on sv.id=d.strategy_version_id
where d.agent_signal::text in ('LONG','SHORT')
"""
df = pd.read_sql(SQL, conn)
df.to_parquet(f"{D}/decisions.parquet")
print(len(df)); print(df.groupby(["risk"]).size().to_dict()); print(df.reason0.value_counts().head(10).to_dict())
