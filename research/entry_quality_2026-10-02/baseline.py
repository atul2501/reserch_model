"""Phase 3/4/23: baseline performance & economics."""
import numpy as np
import pandas as pd
from lib import load_trades, metrics, fmt, table, END_TS

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
pd.set_option("display.float_format", lambda v: f"{v:.4f}")
t = load_trades()
closed = t  # all trades in table are closed (open positions have no trade row)
clean = t[~t.flag_stale_rollover]
K = ["trades", "wins", "losses", "win_rate", "gross_profit", "gross_loss", "net", "pf", "exp", "avg_win", "avg_loss",
     "med_win", "med_loss", "payoff", "be_wr", "max_dd", "fees", "funding", "hold_avg_min", "hold_med_min",
     "exp_bps", "gross_exp_bps"]
print("ALL (raw)        ", fmt(metrics(closed), K))
print("ALL (ex 202 stale-rollover)", fmt(metrics(clean), K))
print("ALL ex ALL rollover", fmt(metrics(t[~t.is_rollover]), K))
for h in (72, 48, 24):
    w = clean[clean.closed_at > END_TS - pd.Timedelta(hours=h)]
    print(f"LAST {h}h (clean)   ", fmt(metrics(w), K))
print("\nBY GENERATION (clean)")
print(table(clean, "generation", K).to_string(index=False))
print("\nBY DAY (UTC, clean)")
clean = clean.assign(day=clean.closed_at.dt.strftime("%m-%d"))
print(table(clean, "day", ["trades", "win_rate", "pf", "exp", "net", "payoff", "be_wr", "exp_bps", "gross_exp_bps"]).to_string(index=False))

print("\nCOSTS (clean, ex rollover)")
nr = clean[~clean.is_rollover]
g = nr.gross_pnl.sum(); f = nr.fees.sum(); fu = nr.funding.sum()
print(f"gross={g:.2f}  fees={f:.2f}  funding(cost)={fu:.2f}  net={nr.net_pnl.sum():.2f}")
print(f"gross exp/trade={nr.gross_pnl.mean():.5f}  net exp/trade={nr.net_pnl.mean():.5f}  gross bps={nr.gross_bps.mean():.2f}  fee bps={nr.fee_bps.mean():.2f}  net bps={nr.net_bps.mean():.2f}")
print(f"gross win rate={(nr.gross_pnl>0).mean():.4f}  net win rate={(nr.net_pnl>0).mean():.4f}")
print(f"gross PF={nr.gross_pnl.clip(lower=0).sum()/-nr.gross_pnl.clip(upper=0).sum():.4f}")
print(f"entry slippage bps mean={nr.entry_slippage_bps.mean():.2f}  exit slippage bps mean={nr.exit_slippage_bps.mean():.2f}  slippage_cost sum={nr.slippage_cost.sum():.2f}")
print("notional quantiles", nr.notional.quantile([.05, .5, .95]).round(2).to_dict(), " risk_amount q", nr.risk_amount.quantile([.05, .5, .95]).round(3).to_dict())
print("planned stop bps q", nr.planned_stop_bps.quantile([.1, .5, .9]).round(1).to_dict(), " planned tp bps q", nr.planned_tp_bps.quantile([.1, .5, .9]).round(1).to_dict())
print("planned RR (tp/stop) median", (nr.planned_tp_bps / nr.planned_stop_bps).median())
print("\nEXIT REASONS (clean)")
print(table(clean, "exit_reason", ["trades", "win_rate", "exp", "net", "avg_win", "avg_loss", "exp_bps"]).to_string(index=False))
print("\nWin-rate candidates for user's 37.2%:")
for nm, d in {"all raw": t, "clean": clean, "last24h": clean[clean.closed_at > END_TS - pd.Timedelta(hours=24)],
              "gen6": clean[clean.generation == 6], "gen5": clean[clean.generation == 5]}.items():
    print(f"  {nm}: {d.win.mean():.4f}")
