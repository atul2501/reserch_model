import pandas as pd, numpy as np
from lib import D
ds=pd.read_parquet(f"{D}/dataset.parquet")
ds["slip_bps"]=ds.slippage_cost/ds.notional*1e4
ds["mid_bps"]=ds.gross_bps+ds.slip_bps   # P&L at bar prices before slippage & fees
print("per-trade means (bps): gross(after slip)=%.2f slip=%.2f fees=%.2f net=%.2f  MID (no slip,no fee)=%.2f"%(ds.gross_bps.mean(),ds.slip_bps.mean(),ds.fee_bps.mean(),ds.net_bps.mean(),ds.mid_bps.mean()))
print("cost share of |avg loss|:", round((ds.slip_bps+ds.fee_bps).mean()/abs(ds[ds.net_pnl<=0].net_bps.mean()),3))
sc={"actual":ds.net_bps,"maker both sides (3bps fee), same slip":ds.mid_bps-ds.slip_bps-3.0,"taker fees, zero slippage":ds.mid_bps-ds.fee_bps,
    "maker both sides, zero slippage":ds.mid_bps-3.0,"frictionless":ds.mid_bps}
for k,v in sc.items(): print(f"  {k:42s} exp={v.mean():+6.2f} bps  win_rate={(v>0).mean():.3f}  PF={v[v>0].sum()/-v[v<=0].sum():.3f}")
print("\nMID bps by family (frictionless edge) with hour-block t-stat:")
for fam,g in ds.groupby("family"):
    hb=g.groupby(g.signal_bar//3600000).mid_bps.mean()
    print(f"  {fam:17s} n={len(g):6d} mid={g.mid_bps.mean():+6.2f}  t={hb.mean()/(hb.std()/np.sqrt(len(hb))) if len(hb)>2 else float('nan'):+5.2f}  hours={len(hb)}")
print("\nTrades/day:", round(len(ds)/5.3), " median hold min:", ds.holding_seconds.median()/60, " stop bps median:", ds.planned_stop_bps.median(), " round-trip cost as % of stop:", round(((ds.slip_bps+ds.fee_bps)/ds.planned_stop_bps).median(),2))
