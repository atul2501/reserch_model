"""Section 19 — minimal INDEPENDENT backtest. No production code, no Phase-2 helpers.
signal -> entry at next bar open -> fixed-horizon exit at bar close -> gross -> realistic cost -> net.
Signals = unique (signal bar, side, family) that the production system actually TRADED, read straight from SQL."""
import numpy as np
import psycopg2

conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("select open_time, open, close from market_candles where symbol='SOL' and timeframe='1m' and is_final order by open_time")
rows = cur.fetchall()
pos = {r[0]: i for i, r in enumerate(rows)}
opens = [r[1] for r in rows]; closes = [r[2] for r in rows]
cur.execute("""select distinct o.signal_candle_open_time, t.side::text, sv.dna->>'strategy_family'
               from trades t join orders o on o.id=t.entry_order_id join agents a on a.id=t.agent_id
               join strategy_versions sv on sv.id=a.strategy_version_id
               where t.exit_reason <> 'generation_rollover' and o.signal_candle_open_time is not null""")
sigs = cur.fetchall()
print(f"independent: {len(sigs)} unique traded signals, {len(rows)} candles")
COST = {"realistic 13.5": 13.5, "taker fees only 9": 9.0, "maker both 3": 3.0, "frictionless 0": 0.0}
for h in (1, 5, 10, 30, 60):
    gross = []
    for bar, side, fam in sigs:
        i = pos.get(bar)
        if i is None or i + h >= len(rows):
            continue
        entry = opens[i + 1]                # next bar open
        exitp = closes[i + h]               # close of the h-th bar after entry bar start
        s = 1 if side == "LONG" else -1
        gross.append((exitp / entry - 1) * 10_000 * s)
    g = np.array(gross)
    line = f"h={h:2d}m n={len(g)} gross mean {g.mean():+.3f} bps  dir.acc {np.mean(g > 0):.3f}"
    for k, c in COST.items():
        net = g - c
        pf = net[net > 0].sum() / -net[net <= 0].sum()
        line += f" | {k}: {net.mean():+.2f} (PF {pf:.3f})"
    print(line)
