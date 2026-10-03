"""Phase 2 data-integrity audit of the restored backup (read-only, parquet extracts)."""
import os
import numpy as np
import pandas as pd

D = os.path.join(os.path.dirname(__file__), "data")
t = pd.read_parquet(f"{D}/trades.parquet")
c = pd.read_parquet(f"{D}/candles.parquet")
ag = pd.read_parquet(f"{D}/agents.parquet")
pos = pd.read_parquet(f"{D}/positions.parquet")
fund = pd.read_parquet(f"{D}/funding.parquet")
orders = pd.read_parquet(f"{D}/orders.parquet")
BACKUP_TS = pd.Timestamp("2026-10-02 16:27:28", tz="UTC")

def p(k, v):
    print(f"{k:<55} {v}")

print("=== ORPHANS / DUPLICATES ===")
p("trades without agent", t.generation.isna().sum())
p("trades without position", t.stop_loss_price.isna().sum() if False else (~t.position_id.isin(pos.position_id)).sum())
p("trades without trade_analytics", t.family.isna().sum())
p("trades without entry order", t.entry_order_fee.isna().sum())
p("trades without exit order", t.exit_order_fee.isna().sum())
p("duplicate trade ids", t.trade_id.duplicated().sum())
p("positions with >1 trade", t.position_id.duplicated().sum())
p("dup (agent,opened_at,side) trades", t.duplicated(["agent_id", "opened_at", "side"]).sum())
p("dup position ids", pos.position_id.duplicated().sum())
p("closed positions without a trade", ((~pos.is_open) & ~pos.position_id.isin(t.position_id)).sum())
p("open positions", pos.is_open.sum())
print(pos[pos.is_open][["agent_id", "side", "opened_at"]].merge(ag[["agent_id", "generation", "status"]]).to_string())

print("\n=== TIMESTAMPS ===")
p("closed_at < opened_at", (t.closed_at < t.opened_at).sum())
p("closed_at == opened_at", (t.closed_at == t.opened_at).sum())
p("future timestamps (> backup time)", ((t.closed_at > BACKUP_TS) | (t.opened_at > BACKUP_TS)).sum())
hold = (t.closed_at - t.opened_at).dt.total_seconds()
p("holding_seconds mismatch >1s", (abs(hold - t.holding_seconds) > 1).sum())
p("signal bar >= opened_at (lookahead in fill)", (t.signal_bar_open_time_ms >= t.opened_at.astype("int64") // 10**6).sum())
lag = t.opened_at.astype("int64") // 10**6 - t.signal_bar_open_time_ms
p("open - signal_bar_open (ms) quantiles", lag.quantile([0, .5, .99, 1]).to_dict())
p("entry_delay_seconds quantiles", t.entry_delay_seconds.quantile([0, .5, .99, 1]).round(2).to_dict())

print("\n=== P&L IDENTITY ===")
for name, f in {"net = gross - fees + funding": t.gross_pnl - t.fees + t.funding,
                "net = gross - fees - funding": t.gross_pnl - t.fees - t.funding,
                "net = gross - fees - funding - bad_debt?": t.gross_pnl - t.fees - t.funding}.items():
    err = (t.net_pnl - f).abs()
    p(name + "  (violations >1e-6)", int((err > 1e-6).sum()))
sgn = np.where(t.side == "LONG", 1, -1)
g2 = (t.exit_price - t.entry_price) * t.quantity * sgn
p("gross = (exit-entry)*qty*sign violations >1e-6", int(((t.gross_pnl - g2).abs() > 1e-6).sum()))
p("fees != entry_order_fee + exit_order_fee (>1e-6)", int(((t.fees - (t.entry_order_fee + t.exit_order_fee)).abs() > 1e-6).sum()))
fsum = fund.groupby("position_id").payment.sum()
t["fund_paid"] = t.position_id.map(fsum).fillna(0)
for nm, cand in {"funding == +sum(payments)": t.fund_paid, "funding == -sum(payments)": -t.fund_paid}.items():
    p(nm + " violations", int(((t.funding - cand).abs() > 1e-6).sum()))
p("trades with nonzero funding", int((t.funding.abs() > 0).sum()))
p("bad_debt nonzero trades", int((t.bad_debt.fillna(0) != 0).sum()))
p("nonfinite pnl", int((~np.isfinite(t.net_pnl)).sum()))

print("\n=== BALANCES / AGENTS ===")
rp = t.groupby("agent_id").net_pnl.sum()
ag["sum_trade_pnl"] = ag.agent_id.map(rp).fillna(0)
ag["tc"] = ag.agent_id.map(t.groupby("agent_id").size()).fillna(0)
p("agent.realized_pnl != sum(trade.net_pnl) (>1e-4)", int(((ag.realized_pnl - ag.sum_trade_pnl).abs() > 1e-4).sum()))
p("agent.balance != start + realized (>1e-4)", int(((ag.balance - (ag.starting_balance + ag.realized_pnl)).abs() > 1e-4).sum()))
p("agent.trade_count != #trades", int((ag.trade_count != ag.tc).sum()))
p("negative balances", int((ag.balance < 0).sum()))
p("negative equity", int((ag.equity < 0).sum()))
p("agents w/ death_timestamp", int(ag.death_timestamp.notna().sum()))
p("death reasons", ag.death_reason.value_counts(dropna=False).to_dict())
dead = t.merge(ag[["agent_id", "death_timestamp"]].rename(columns={"death_timestamp": "dts"}), on="agent_id")
p("trades OPENED after agent death", int((dead.opened_at > dead.dts).sum()))
pass
fees_agent = t.groupby("agent_id").fees.sum()
p("agent.fees_paid != sum(trade.fees) (>1e-4)", int(((ag.fees_paid - ag.agent_id.map(fees_agent).fillna(0)).abs() > 1e-4).sum()))

print("\n=== OVERLAPPING POSITIONS PER AGENT ===")
tt = t.sort_values(["agent_id", "opened_at"])
prev_close = tt.groupby("agent_id").closed_at.shift(1)
ov = tt[tt.opened_at < prev_close]
p("trades opened before same agent's previous trade closed", len(ov))
# Trades closing at generation boundary with a rollover
p("generation_rollover exits", int((t.exit_reason == "generation_rollover").sum()))

print("\n=== CANDLES ===")
p("candles", len(c))
p("duplicate open_time", int(c.open_time.duplicated().sum()))
p("non-final", int((~c.is_final).sum()))
bad = (c.high < c[["open", "close"]].max(axis=1)) | (c.low > c[["open", "close"]].min(axis=1)) | (c.high < c.low) | (c[["open", "high", "low", "close"]] <= 0).any(axis=1)
p("OHLC violations", int(bad.sum()))
p("close_time != open_time+59999", int((c.close_time != c.open_time + 59999).sum()))
gaps = c.open_time.diff().dropna()
p("gaps (diff != 60000)", int((gaps != 60000).sum()))
if (gaps != 60000).any():
    g = c.loc[gaps[gaps != 60000].index, "open_time"]
    for i in g.index:
        print("   gap before", pd.to_datetime(c.open_time[i], unit="ms", utc=True), "missing bars:", int(gaps[i] / 60000 - 1))
p("zero-volume candles", int((c.volume == 0).sum()))
p("candle range", f"{pd.to_datetime(c.open_time.min(), unit='ms', utc=True)} -> {pd.to_datetime(c.open_time.max(), unit='ms', utc=True)}")
ret = c.close.pct_change().abs()
p("abs 1m return > 2%", int((ret > 0.02).sum()))

print("\n=== TRADE PRICE SANITY vs CANDLES ===")
cm = c.set_index("open_time")
eb = (t.opened_at.astype("int64") // 10**6 // 60000) * 60000
lo, hi = eb.map(cm.low), eb.map(cm.high)
p("entry price outside entry-bar [low,high] (>5bps)", int(((t.entry_price < lo * (1 - 5e-4)) | (t.entry_price > hi * (1 + 5e-4))).sum()))
xb = (t.closed_at.astype("int64") // 10**6 // 60000) * 60000
lo2, hi2 = xb.map(cm.low), xb.map(cm.high)
p("exit price outside exit-bar [low,high] (>5bps)", int(((t.exit_price < lo2 * (1 - 5e-4)) | (t.exit_price > hi2 * (1 + 5e-4))).sum()))
p("trade stage counts", t.stage.value_counts().to_dict())
p("trades w/ zero quantity", int((t.quantity <= 0).sum()))
print("\n=== MFE/MAE sanity ===")
p("mfe_bps < 0", int((t.mfe_bps < 0).sum()))
p("mae_bps > 0 (should be <=0?)", int((t.mae_bps > 0).sum()))
p("mae_bps sign quantiles", t.mae_bps.quantile([0, .5, 1]).to_dict())
p("missing mfe/mae", int(t.mfe_bps.isna().sum()))
