"""Phase 6/7/21/24: strategy, regime, direction — with clustered effective-N and chronological stability."""
import numpy as np
import pandas as pd
from lib import load_trades, D, metrics

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 400)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
t = load_trades()
t = t[~t.is_rollover & t.family.notna()].copy()
t = t.merge(pd.read_parquet(f"{D}/fwd.parquet"), on="trade_id")
# 4 chronological periods of equal trade count (by signal time)
t = t.sort_values("signal_bar_open_time_ms")
t["period"] = pd.qcut(np.arange(len(t)), 4, labels=["P1", "P2", "P3", "P4"])
print("period ranges:", t.groupby("period", observed=True).signal_ts.agg(["min", "max"]).to_string())


def seg(g):
    m = metrics(g)
    bars = g.signal_bar_open_time_ms.nunique()
    # cluster-robust SE of net_bps: aggregate by signal bar+side first
    cb = g.groupby(["signal_bar_open_time_ms", "side"]).net_bps.mean()
    se = cb.std() / np.sqrt(len(cb)) if len(cb) > 1 else np.nan
    return pd.Series(dict(n=m["trades"], bars=bars, wr=m["win_rate"], pf=m["pf"], exp_bps=g.net_bps.mean(),
                          t_stat=g.net_bps.mean() / se if se and se > 0 else np.nan, gross_bps=g.gross_bps.mean(),
                          net=m["net"], avg_win=m["avg_win"], avg_loss=m["avg_loss"], mfe=g.mfe_bps.mean(),
                          mae=g.mae_bps.mean(), hold=g.holding_seconds.mean() / 60, fwd30=g.fwd_30.mean()))


print("\n=== STRATEGY (all periods) ===")
print(t.groupby("family").apply(seg).sort_values("exp_bps", ascending=False).to_string())
print("\n=== STRATEGY x PERIOD exp_bps (n) ===")
pv = t.groupby(["family", "period"], observed=True).agg(e=("net_bps", "mean"), n=("net_bps", "size")).unstack()
print(pv.to_string())
print("\n=== STRATEGY x PERIOD gross_bps ===")
print(t.groupby(["family", "period"], observed=True).gross_bps.mean().unstack().to_string())
print("\n=== REGIME ===")
print(t.groupby("regime").apply(seg).sort_values("exp_bps", ascending=False).to_string())
print("\n=== DIRECTION ===")
print(t.groupby("side").apply(seg).to_string())
print("\n=== STRATEGY x REGIME x SIDE (n>=150, ranked by exp_bps) with per-period exp_bps ===")
g3 = t.groupby(["family", "regime", "side"])
res = g3.apply(seg)
res = res[res.n >= 150]
per = t.groupby(["family", "regime", "side", "period"], observed=True).net_bps.mean().unstack()
perN = t.groupby(["family", "regime", "side", "period"], observed=True).size().unstack()
res = res.join(per).join(perN.add_suffix("_n"))
res["periods_pos"] = (per.reindex(res.index) > 0).sum(axis=1)
res["periods_gross_pos"] = (t.groupby(["family", "regime", "side", "period"], observed=True).gross_bps.mean().unstack().reindex(res.index) > 0).sum(axis=1)
print(res.sort_values("exp_bps", ascending=False)[["n", "bars", "wr", "pf", "exp_bps", "t_stat", "gross_bps", "net", "mfe", "mae", "hold",
      "P1", "P2", "P3", "P4", "P1_n", "P2_n", "P3_n", "P4_n", "periods_pos", "periods_gross_pos"]].to_string())
print("\nCombos with net exp>0 in >=3 of 4 periods:", int((res.periods_pos >= 3).sum()), " in all 4:", int((res.periods_pos == 4).sum()),
      " of", len(res))
print("Combos with GROSS exp>0 in all 4 periods:", int((res.periods_gross_pos == 4).sum()))
print("\n=== Overall net exp by period ===")
print(t.groupby("period", observed=True).agg(n=("net_bps", "size"), wr=("win", "mean"), exp=("net_bps", "mean"), gross=("gross_bps", "mean"), fwd10=("fwd_10", "mean")).to_string())
