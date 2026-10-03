"""Phase 5/22: entry vs exit forensics. Exit-independent entry edge via signed forward returns."""
import numpy as np
import pandas as pd
from lib import load_trades, D, table

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
t = load_trades()
t = t[~t.is_rollover & t.family.notna()].copy()
c = pd.read_parquet(f"{D}/candles.parquet").reset_index(drop=True)
idx = pd.Series(np.arange(len(c)), index=c.open_time)
eb = t.opened_at.astype("int64") // 10**6
t["ebi"] = eb.map(idx).astype(int)
op, cl, hi, lo = c.open.to_numpy(), c.close.to_numpy(), c.high.to_numpy(), c.low.to_numpy()
sgn = np.where(t.side == "LONG", 1.0, -1.0)
e0 = op[t.ebi]  # mid-ish reference price: entry bar open
print("entry fill vs bar open (bps, signed adverse):", ((t.entry_price / e0 - 1) * 1e4 * sgn).describe().round(2).to_dict())
print("slippage_cost bps of notional:", (t.slippage_cost / t.notional * 1e4).describe().round(2).to_dict())
H = [1, 3, 5, 10, 15, 30, 60]
for h in H:
    j = np.minimum(t.ebi + h - 1, len(c) - 1)
    t[f"fwd_{h}"] = (cl[j] / e0 - 1) * 1e4 * sgn
print("\nSIGNED FORWARD RETURN FROM ENTRY-BAR OPEN (bps, frictionless, exit-independent)")
rows = []
for h in H:
    x = t[f"fwd_{h}"]
    rows.append(dict(h_min=h, mean=x.mean(), median=x.median(), se=x.std() / np.sqrt(len(x)), pct_pos=(x > 0).mean(),
                     pct_gt_cost=(x > 13.4).mean()))
print(pd.DataFrame(rows).to_string(index=False))
# Unconditional benchmark: random direction has mean 0 by construction; show abs move to compare with cost
for h in H:
    j = np.minimum(np.arange(len(c)) + h - 1, len(c) - 1)
    m = np.abs(cl[j] / op - 1) * 1e4
    if h in (5, 10, 30):
        print(f"  unconditional median |move| over {h}m: {np.median(m):.2f} bps (round-trip cost ~13.4 bps)")
print("\nFWD return by family (bps) ")
print(t.groupby("family")[[f"fwd_{h}" for h in H]].mean().assign(n=t.groupby("family").size()).to_string())
print("\nFWD return by side")
print(t.groupby("side")[[f"fwd_{h}" for h in H]].mean().to_string())

print("\nMFE / MAE (bps)")
print(t[["mfe_bps", "mae_bps", "time_to_mfe_seconds", "time_to_mae_seconds", "net_bps", "gross_bps"]].describe().round(2).to_string())
print("share MFE >= 13.4bps (could cover costs):", (t.mfe_bps >= 13.4).mean().round(3),
      " share MFE>=planned TP:", (t.mfe_bps >= t.planned_tp_bps).mean().round(3))
print("share mfe_before_mae:", t.mfe_before_mae.mean().round(3))
first_bar_adverse = t.mae_bps.abs() >= t.planned_stop_bps * 0.5
print("\nBY EXIT REASON: MFE, MAE, giveback")
t["giveback_bps"] = t.mfe_bps - t.gross_bps
print(t.groupby("exit_reason").agg(n=("net_bps", "size"), net_bps=("net_bps", "mean"), gross_bps=("gross_bps", "mean"),
      mfe=("mfe_bps", "mean"), mae=("mae_bps", "mean"), giveback=("giveback_bps", "mean"), hold_min=("holding_seconds", lambda s: s.mean() / 60),
      t_mfe=("time_to_mfe_seconds", "median"), t_mae=("time_to_mae_seconds", "median")).to_string())
sl = t[t.exit_reason == "stop_loss"]
print("\nSTOP LOSSES: n=", len(sl), " median hold min", sl.holding_seconds.median() / 60,
      " stopped within 1 bar:", (sl.holding_seconds <= 60).mean().round(3), " within 3 bars:", (sl.holding_seconds <= 180).mean().round(3))
print(" stop-loss trades with MFE>=13.4bps (were in profit > costs first):", (sl.mfe_bps >= 13.4).mean().round(3),
      " MFE>=half TP:", (sl.mfe_bps >= sl.planned_tp_bps / 2).mean().round(3), " MFE<5bps (never worked):", (sl.mfe_bps < 5).mean().round(3))
print("\nLOSERS with strong MFE (>= 20bps) — exit-giveback candidates")
los = t[t.net_pnl <= 0]
gb = los[los.mfe_bps >= 20]
print(f" {len(gb)} of {len(los)} losers ({len(gb)/len(los):.3f}); their net sum={gb.net_pnl.sum():.2f} vs all losers {los.net_pnl.sum():.2f}")
print(gb.exit_reason.value_counts().to_dict())
print("\nMFE distribution deciles (bps):", t.mfe_bps.quantile(np.linspace(.1, .9, 9)).round(1).to_list())
print("MAE distribution deciles (bps):", t.mae_bps.quantile(np.linspace(.1, .9, 9)).round(1).to_list())
print("\nquality class:", t.trade_quality_class.value_counts(normalize=True).round(3).to_dict())
# Exit-policy oracle-free alternatives: fixed-horizon exits (frictional) to see if ANY simple exit is positive
print("\nFIXED-HORIZON EXIT (minus 13.4bps cost) mean net bps:", {h: round(t[f'fwd_{h}'].mean() - 13.4, 2) for h in H})
t[["trade_id"] + [f"fwd_{h}" for h in H]].to_parquet(f"{D}/fwd.parquet")
