"""Extract research tables from the ISOLATED restored backup (port 55432) to parquet. Read-only."""
import os
import pandas as pd
import psycopg2

OUT = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(OUT, exist_ok=True)
conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)

def q(sql):
    return pd.read_sql(sql, conn)

trades = q("""
select t.id::text trade_id, t.agent_id::text agent_id, t.position_id::text position_id, t.side::text side,
       t.quantity, t.entry_price, t.exit_price, t.gross_pnl, t.fees, t.funding, t.slippage_cost, t.net_pnl,
       t.bad_debt, t.opened_at, t.closed_at, t.holding_seconds, t.entry_regime, t.exit_regime, t.exit_reason,
       t.stage::text stage, t.entry_order_id::text entry_order_id, t.exit_order_id::text exit_order_id,
       a.generation, a.status::text agent_status, a.death_timestamp, a.identifier,
       p.entry_fee, p.entry_slippage_cost, p.stop_loss_price, p.take_profit_price, p.leverage pos_leverage,
       p.entry_candle_open_time, p.is_open pos_is_open, p.opened_at pos_opened_at, p.closed_at pos_closed_at,
       eo.fee entry_order_fee, xo.fee exit_order_fee, eo.signal_candle_open_time entry_signal_candle,
       ta.family, ta.regime, ta.signal_bar_open_time_ms, ta.signal_close_time_ms, ta.entry_delay_seconds,
       ta.signal_confidence, ta.setup_strength, ta.council_bias, ta.council_confidence, ta.council_status,
       ta.risk_amount, ta.planned_risk_amount, ta.expected_r, ta.planned_stop_bps, ta.planned_tp_bps,
       ta.leverage, ta.position_notional, ta.mfe_r, ta.mae_r, ta.mfe_bps, ta.mae_bps, ta.time_to_mfe_seconds,
       ta.time_to_mae_seconds, ta.mfe_before_mae, ta.left_on_table_r, ta.trade_quality_class,
       ta.post_exit_mfe_bps_30, ta.post_exit_mae_bps_30, ta.entry_slippage_bps, ta.exit_slippage_bps
from trades t
left join agents a on a.id = t.agent_id
left join positions p on p.id = t.position_id
left join orders eo on eo.id = t.entry_order_id
left join orders xo on xo.id = t.exit_order_id
left join trade_analytics ta on ta.trade_id = t.id
""")
trades.to_parquet(f"{OUT}/trades.parquet")
q("select open_time, close_time, open, high, low, close, volume, trade_count, funding_rate, open_interest, is_final "
  "from market_candles where symbol='SOL' and timeframe='1m' order by open_time").to_parquet(f"{OUT}/candles.parquet")
q("select candle_open_time, regime::text regime, confidence, detector_version, created_at from market_regimes "
  "where symbol='SOL' order by candle_open_time").to_parquet(f"{OUT}/regimes.parquet")
q("select id::text agent_id, identifier, generation, status::text status, starting_balance, balance, equity, "
  "realized_pnl, fees_paid, funding_paid, peak_equity, max_drawdown, trade_count, death_timestamp, death_reason, "
  "final_equity, final_pnl, bad_debt, created_at, strategy_version_id::text svid from agents").to_parquet(f"{OUT}/agents.parquet")
q("select id::text position_id, agent_id::text agent_id, side::text side, is_open, opened_at, closed_at, entry_price, "
  "quantity from positions").to_parquet(f"{OUT}/positions.parquet")
q("select agent_id::text agent_id, position_id::text position_id, funding_time_ms, payment from funding_payments"
  ).to_parquet(f"{OUT}/funding.parquet")
q("select o.id::text order_id, o.agent_id::text agent_id, o.status::text status, o.order_kind, o.reduce_only, o.fee, "
  "o.submitted_at, o.filled_at from orders o").to_parquet(f"{OUT}/orders.parquet")
q("select * from generations").to_parquet(f"{OUT}/generations.parquet")
print({f: len(pd.read_parquet(f"{OUT}/{f}")) for f in os.listdir(OUT)})
