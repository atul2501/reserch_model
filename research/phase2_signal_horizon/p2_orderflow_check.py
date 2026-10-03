"""Pre-specified (not grid-selected) check: order_flow family, fixed 30m/60m hold, no filters."""
import numpy as np, pandas as pd
from p2lib import D, FOLDS, fold_parts, cluster_t, econ, block2h, candles
c = candles(); s = pd.read_parquet(f"{D}/p2_trsig.parquet"); a = pd.read_parquet(f"{D}/p2_allsig.parquet")
o = c.set_index("open_time")
def drift(df, h):  # side-signed mean unconditional h-min return of all bars in df's span
    m = (c.close.shift(-(h - 1)) / c.open - 1) * 1e4; m.index = c.open_time
    mu = m[(m.index >= df.bar.min()) & (m.index <= df.bar.max())].mean()
    return np.where(df.side == "LONG", 1, -1) * mu
rows = []
for uni_name, uni in [("traded order_flow", s[s.family == "order_flow"]), ("ALL order_flow signals", a[a.family == "order_flow"])]:
    for h in (30, 60):
        for fold in FOLDS:
            oo = fold_parts(uni, fold)[2]
            x = oo[f"fwd_{h}"].dropna()
            for sc, cost in [("S1", 13.5), ("S6", 8.0), ("S3", 3.0)]:
                e = econ((x - cost).to_numpy())
                rows.append(dict(universe=uni_name, h=h, window=fold, cost=sc, n=e["n"], bars=oo.bar.nunique(), exp=e["exp_bps"], pf=e["pf"], wr=e["win_rate"],
                                 t=cluster_t(x - cost, block2h(oo.bar.loc[x.index]))[0], drift=np.mean(drift(oo, h))))
        x = uni[f"fwd_{h}"].dropna()
        for sc, cost in [("S1", 13.5), ("S6", 8.0), ("S3", 3.0)]:
            e = econ((x - cost).to_numpy())
            rows.append(dict(universe=uni_name, h=h, window="ALL (in-sample)", cost=sc, n=e["n"], bars=uni.bar.nunique(), exp=e["exp_bps"], pf=e["pf"],
                             wr=e["win_rate"], t=cluster_t(x - cost, block2h(uni.bar.loc[x.index]))[0], drift=np.mean(drift(uni, h))))
r = pd.DataFrame(rows); pd.set_option("display.width", 200); print(r.round(3).to_string(index=False))
r.to_csv("order_flow_prespecified_check.csv", index=False)
