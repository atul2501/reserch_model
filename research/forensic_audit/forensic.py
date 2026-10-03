"""Forensic audit — independent reconstruction of the trading pipeline from the restored backup.

Read-only. Connects ONLY to the isolated research DB (127.0.0.1:55432). Production code is imported solely to
REPLAY features/signals for parity checks; P&L, fees, slippage and exits are recomputed independently here.
Run from backend/ with DATABASE_URL pointing at the research DB (see FORENSIC_AUDIT_REPORT.md).
"""
import json, os, sys
import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(OUT, "..", "phase2_signal_horizon"))
sys.path.insert(0, os.path.abspath(os.path.join(OUT, "..", "..", "backend")))
from p2lib import cluster_t, block2h, add_forward, HORIZONS  # noqa: E402
from app.market.feature_engine import compute_features, FEATURE_WINDOW  # noqa: E402
from app.strategies.engine import build_feature_view, compute_population_features, evaluate_signal  # noqa: E402
from app.schemas.strategy_dna import StrategyDNA  # noqa: E402

pd.set_option("display.width", 260); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 200)
pd.set_option("display.float_format", lambda v: f"{v:.4f}")
TAKER, MAKER, SLIP, IMPACT, STOP_MULT = 0.00045, 0.00015, 2.0, 0.5, 2.0
conn = psycopg2.connect(host="127.0.0.1", port=55432, user="postgres", dbname="trading_lab_research_20261002")
conn.set_session(readonly=True)
q = lambda s: pd.read_sql(s, conn)

C = q("select open_time, open, high, low, close, volume, funding_rate, open_interest from market_candles "
      "where symbol='SOL' and timeframe='1m' and is_final order by open_time")
CI = C.set_index("open_time")
IDX = pd.Series(np.arange(len(C)), index=C.open_time)

T = q("""
select t.id::text trade_id, t.agent_id::text agent_id, a.generation, t.side::text side, t.quantity, t.entry_price, t.exit_price,
       t.gross_pnl, t.fees, t.funding, t.slippage_cost, t.net_pnl, t.opened_at, t.closed_at, t.holding_seconds, t.exit_reason,
       t.entry_regime, sv.dna::text dna, sv.dna->>'strategy_family' family,
       eo.requested_price e_req, eo.filled_price e_fill, eo.fee e_fee, eo.slippage_cost e_slip, eo.latency_ms e_lat,
       eo.signal_candle_open_time sig_bar, eo.approved_notional, eo.requested_notional, eo.intent::text intent, eo.status::text e_status,
       eo.quantity e_qty, eo.filled_quantity e_fqty, eo.raw_venue_response::text e_raw, eo.submitted_at e_sub, eo.filled_at e_filled,
       xo.order_kind x_kind, xo.requested_price x_req, xo.filled_price x_fill, xo.fee x_fee, xo.slippage_cost x_slip,
       xo.raw_venue_response::text x_raw,
       p.stop_loss_price, p.take_profit_price, p.trailing_stop_distance, p.entry_fee p_entry_fee, p.entry_candle_open_time,
       p.funding_accrued, p.peak_price, p.trough_price, p.trailing_active, p.leverage,
       d.agent_signal::text d_sig, d.agent_signal_confidence d_conf, d.agent_signal_reasoning::text d_reason,
       d.council_bias d_cbias, d.council_confidence d_cconf, d.risk_reasoning::text d_risk, d.created_at d_created,
       (select coalesce(sum(payment),0) from funding_payments fp where fp.position_id=t.position_id) fund_sum
from trades t join agents a on a.id=t.agent_id join strategy_versions sv on sv.id=a.strategy_version_id
left join orders eo on eo.id=t.entry_order_id left join orders xo on xo.id=t.exit_order_id
left join positions p on p.id=t.position_id left join decisions d on d.id=eo.decision_id
""")
T["sgn"] = np.where(T.side == "LONG", 1.0, -1.0)
T["notional"] = T.entry_price * T.quantity
T["bps"] = lambda: None
T = T.drop(columns="bps")
T["stale_rollover"] = (T.exit_reason == "generation_rollover") & ((T.closed_at < T.opened_at) |
    ((T.exit_price / T.closed_at.astype("int64").floordiv(10**6 * 60000).mul(60000).map(CI.close) - 1).abs() > 0.002))
print(f"trades loaded: {len(T)}")

# =========================================================== 1. P&L / FEE / SLIPPAGE RECONCILIATION (all trades)
R = pd.DataFrame({"trade_id": T.trade_id})
R["gross_indep"] = (T.exit_price - T.entry_price) * T.quantity * T.sgn
R["gross_db"] = T.gross_pnl
R["gross_diff"] = R.gross_indep - R.gross_db
exit_rate = np.where(T.x_kind == "take_profit", MAKER, TAKER)
R["entry_fee_indep"] = T.entry_price * T.quantity * TAKER
R["exit_fee_indep"] = np.where(T.exit_reason == "generation_rollover", T.exit_price * T.quantity * TAKER, T.exit_price * T.quantity * exit_rate)
liq = T.x_kind == "liquidation"
R["fees_indep"] = R.entry_fee_indep + R.exit_fee_indep
R["fees_db"] = T.fees
R["fees_diff"] = R.fees_indep - R.fees_db
R["funding_indep"] = T.fund_sum
R["funding_db"] = T.funding
R["net_indep"] = R.gross_indep - R.fees_indep - R.funding_indep
R["net_db"] = T.net_pnl
R["net_diff"] = R.net_indep - R.net_db
ent_open = T.entry_candle_open_time.map(CI.open)
R["entry_fill_bar_is_next_bar"] = (T.entry_candle_open_time == T.sig_bar + 60000)
R["entry_slip_bps_indep"] = (T.entry_price / ent_open - 1) * 1e4 * T.sgn
R["entry_slip_bps_model"] = SLIP + IMPACT * (T.notional / 10_000)
R["exit_slip_bps_vs_ref"] = -(T.exit_price / T.x_req - 1) * 1e4 * T.sgn
R["exit_kind"] = T.x_kind.fillna("rollover(no order)")
R["stale_rollover"] = T.stale_rollover
R["exit_reason"] = T.exit_reason
R.to_csv(f"{OUT}/pnl_reconciliation.csv", index=False)
ok = ~T.stale_rollover
print("\n=== P&L RECONCILIATION (independent vs DB) ===")
for col, tol in [("gross_diff", 1e-9), ("fees_diff", 1e-7), ("net_diff", 1e-7)]:
    print(f"{col}: |diff|>{tol}: {(R[col].abs() > tol).sum()} of {len(R)} (max {R[col].abs().max():.2e}); excluding stale rollovers: {(R[ok][col].abs() > tol).sum()}")
print("funding indep (sum of payments) vs trade.funding mismatches:", int(((R.funding_indep - R.funding_db).abs() > 1e-9).sum()))
print("entry reference == open of bar after signal:", f"{(T.entry_candle_open_time == T.sig_bar + 60000).mean():.4f}",
      " entry filled vs that open (bps adverse): ", R.entry_slip_bps_indep.describe().round(3).to_dict())
print("entry slippage indep - model (bps):", (R.entry_slip_bps_indep - R.entry_slip_bps_model).describe().round(3).to_dict())
print("exit slippage vs reference by kind (bps):", R.groupby("exit_kind").exit_slip_bps_vs_ref.agg(["count", "mean", "min", "max"]).round(3).to_dict("index"))
fee_bps = (T.fees / T.notional * 1e4)
print("fee bps by exit kind:", fee_bps.groupby(R.exit_kind).mean().round(3).to_dict())

# =========================================================== 2. EXECUTION AUDIT
print("\n=== EXECUTION AUDIT ===")
ex = []
xb = (T.closed_at.astype("int64") // 10**6 // 60000) * 60000
xbar = pd.DataFrame({"o": xb.map(CI.open), "h": xb.map(CI.high), "l": xb.map(CI.low), "c": xb.map(CI.close)})
tp = T.x_kind == "take_profit"
tp_overshoot_bps = np.where(T.side == "LONG", (xbar.h / T.take_profit_price - 1), (T.take_profit_price / xbar.l - 1)) * 1e4
touch = tp & (tp_overshoot_bps < 1.0)
ex.append(dict(check="TP exits filled at exact TP level, zero slippage, maker fee", n=int(tp.sum()),
               value=f"{(T[tp].exit_price == T[tp].take_profit_price).mean():.4f} exact"))
ex.append(dict(check="TP exits where bar only TOUCHED the level (<1 bp through) - fill not guaranteed live", n=int(touch.sum()),
               value=f"{touch.sum() / max(1, tp.sum()):.3f} of TP exits"))
st = T.x_kind == "stop"
gap = st & np.where(T.side == "LONG", xbar.o <= T.x_req + 1e-9, xbar.o >= T.x_req - 1e-9) & (T.x_req == xbar.o)
ex.append(dict(check="stop exits filled at gapped OPEN (worse than level)", n=int(gap.sum()), value=f"{gap.sum() / max(1, st.sum()):.4f} of stops"))
ex.append(dict(check="stop exit slippage bps (model 4 + impact)", n=int(st.sum()), value=f"{R[st].exit_slip_bps_vs_ref.mean():.3f}"))
sig = T.exit_reason.isin(["exit_rules", "signal_reversal"])
ref_is_open = sig & np.isclose(T.x_req, xbar.o)
ex.append(dict(check="signal exits referenced at OPEN of exit bar (decided prior close)", n=int(sig.sum()), value=f"{ref_is_open.sum() / max(1, sig.sum()):.4f}"))
ts_label = sig & (T.closed_at.dt.second == 59)
ex.append(dict(check="signal exits executed at bar OPEN but closed_at stamped at bar CLOSE (+59.999s) - timestamp label bug", n=int(ts_label.sum()),
               value=f"{ts_label.sum() / max(1, sig.sum()):.4f} of signal exits"))
# decision latency vs fill reference time (entry fills at open of bar N+1 = signal close time)
lag = (T.d_created - pd.to_datetime(T.sig_bar + 60000, unit="ms", utc=True)).dt.total_seconds()
ex.append(dict(check="decision written AFTER the price it is filled at (seconds, p50/p90/p99)", n=int(lag.notna().sum()),
               value=f"{lag.quantile(.5):.2f} / {lag.quantile(.9):.2f} / {lag.quantile(.99):.2f}"))
ex.append(dict(check="partial fills (entry filled_qty < qty)", n=int((T.e_fqty < T.e_qty - 1e-12).sum()), value=""))
pd.DataFrame(ex).to_csv(f"{OUT}/execution_audit.csv", index=False)
print(pd.DataFrame(ex).to_string(index=False))
# Value of TP touch-fill optimism: TP exit costs maker 1.5 + 0 slip vs a taker market exit 4.5 + 2
print(f"TP touch-only fills: {touch.sum()} trades; their mean net bps {T[touch].net_pnl.div(T[touch].notional).mul(1e4).mean():.2f}; "
      f"share of all trades {touch.mean():.4f}; if they had NOT filled, the system loses their +bps (upper bound of optimism "
      f"{(T[touch].net_pnl.sum() / T[~T.stale_rollover].notional.sum()) * 1e4:.3f} bps per average trade)")

# =========================================================== 3. TRADE TRACES (production replay)
print("\n=== TRADE TRACES ===")
rng = np.random.default_rng(20261002)
clean = T[~T.stale_rollover & T.sig_bar.notna()].copy()
clean["win"] = clean.net_pnl > 0
picks = []
strata = [("exit_reason", v) for v in ["stop_loss", "take_profit", "exit_rules", "signal_reversal", "trailing_stop", "generation_rollover"]]
for col, v in strata:
    pool = clean[clean[col] == v]
    for side in ("LONG", "SHORT"):
        p2 = pool[pool.side == side]
        if len(p2):
            picks.append(p2.iloc[rng.integers(len(p2))].trade_id)
for fam in clean.family.unique():
    p2 = clean[(clean.family == fam) & ~clean.trade_id.isin(picks)]
    if len(p2):
        picks.append(p2.iloc[rng.integers(len(p2))].trade_id)
for g in sorted(clean.generation.unique()):
    p2 = clean[(clean.generation == g) & ~clean.trade_id.isin(picks)]
    picks.append(p2.iloc[rng.integers(len(p2))].trade_id)
longest = clean.sort_values("holding_seconds").iloc[-1].trade_id
stale_one = T[T.stale_rollover].iloc[0].trade_id
picks = list(dict.fromkeys(picks + [longest, stale_one]))
tr_rows = []
stored = {}
def stored_features(bar):
    if bar not in stored:
        d = q(f"select features::text f from market_features where symbol='SOL' and candle_open_time={int(bar)}")
        stored[bar] = json.loads(d.f.iat[0]) if len(d) else None
    return stored[bar]
def replay(row):
    """Production replay: features from candles <= signal bar ONLY, then DNA signal."""
    k = IDX[int(row.sig_bar)]
    win = C.iloc[max(0, k - FEATURE_WINDOW + 1): k + 1]
    ctx = compute_features(win, symbol="SOL", timeframe="1m")
    prev = compute_features(win.iloc[:-1], symbol="SOL", timeframe="1m")
    dna = StrategyDNA.model_validate(json.loads(row.dna))
    cur, prv = compute_population_features(win, [dna])
    sig = evaluate_signal(dna, build_feature_view(ctx, prev, cur, prv))
    return ctx, dna, sig
for tid in picks:
    r = T[T.trade_id == tid].iloc[0]
    ctx, dna, sig = replay(r)
    sf = stored_features(int(r.sig_bar))
    intent = json.loads(r.intent) if r.intent else {}
    atr = intent.get("atr")
    # independent stop / tp from DNA
    if dna.stop_loss.enabled and dna.stop_loss.method == "atr_multiple":
        sl_ind = r.entry_price - r.sgn * atr * dna.stop_loss.value
    elif dna.stop_loss.enabled and dna.stop_loss.method == "structure_based":
        lvl = intent.get("swing_low") if r.side == "LONG" else intent.get("swing_high")
        sl_ind = lvl if lvl is not None and ((lvl < r.entry_price) if r.side == "LONG" else (lvl > r.entry_price)) else r.entry_price - r.sgn * atr * dna.stop_loss.value
    elif dna.stop_loss.enabled:
        sl_ind = r.entry_price * (1 - r.sgn * dna.stop_loss.value / 100)
    else:
        sl_ind = np.nan
    if dna.take_profit.enabled and dna.take_profit.method == "risk_reward_multiple":
        tp_ind = r.entry_price + r.sgn * abs(r.entry_price - sl_ind) * dna.take_profit.value
    elif dna.take_profit.enabled and dna.take_profit.method == "atr_multiple":
        tp_ind = r.entry_price + r.sgn * atr * dna.take_profit.value
    elif dna.take_profit.enabled:
        tp_ind = r.entry_price * (1 + r.sgn * dna.take_profit.value / 100)
    else:
        tp_ind = np.nan
    # independent bar-path replay of protective exits (stop first; ignores trailing & signal exits)
    e = IDX[int(r.entry_candle_open_time)]
    first_hit, first_ref = None, None
    for j in range(e, min(e + 400, len(C))):
        b = C.iloc[j]
        adverse = (b.low <= r.stop_loss_price) if r.side == "LONG" else (b.high >= r.stop_loss_price) if r.stop_loss_price == r.stop_loss_price and r.stop_loss_price is not None else False
        fav = (b.high >= r.take_profit_price) if r.side == "LONG" else (b.low <= r.take_profit_price) if r.take_profit_price == r.take_profit_price and r.take_profit_price is not None else False
        if adverse:
            first_hit, first_ref = ("stop_loss", int(b.open_time)), (b.open if ((b.open <= r.stop_loss_price) if r.side == "LONG" else (b.open >= r.stop_loss_price)) else r.stop_loss_price)
            break
        if fav:
            first_hit, first_ref = ("take_profit", int(b.open_time)), r.take_profit_price
            break
    exit_bar = int(xb[T.trade_id == tid].iat[0])
    risk = json.loads(r.d_risk) if r.d_risk else {}
    reason = json.loads(r.d_reason) if r.d_reason else {}
    gross_i = (r.exit_price - r.entry_price) * r.quantity * r.sgn
    fees_i = r.entry_price * r.quantity * TAKER + r.exit_price * r.quantity * (MAKER if r.x_kind == "take_profit" else TAKER)
    tr_rows.append(dict(
        trade_id=tid, generation=r.generation, family=r.family, side=r.side, exit_reason=r.exit_reason,
        signal_bar_utc=pd.to_datetime(int(r.sig_bar), unit="ms", utc=True), candle_close_available_utc=pd.to_datetime(int(r.sig_bar) + 60000, unit="ms", utc=True),
        decision_written_utc=r.d_created, decision_lag_s=(r.d_created - pd.to_datetime(int(r.sig_bar) + 60000, unit="ms", utc=True)).total_seconds(),
        stored_close=sf["close_price"] if sf else None, replay_close=ctx.close_price,
        stored_rsi=sf["momentum"]["rsi_14"] if sf else None, replay_rsi=ctx.momentum.rsi_14,
        stored_atr=sf["volatility"]["atr_14"] if sf else None, replay_atr=ctx.volatility.atr_14, order_intent_atr=atr,
        stored_regime=sf["regime"]["regime"] if sf else None, replay_regime=ctx.regime.regime.value, trade_regime=r.entry_regime,
        db_signal=r.d_sig, replay_signal=sig.bias.value, db_conf=r.d_conf, replay_conf=round(sig.confidence, 6),
        setup_strength=reason.get("setup_strength"), direction_source=reason.get("direction_source"),
        council_bias=r.d_cbias, council_conf=r.d_cconf, council_reason=(risk.get("council") or {}).get("reason"),
        size_modifier=(risk.get("council") or {}).get("size_modifier"), requested_notional=r.requested_notional, approved_notional=r.approved_notional,
        expected_entry_price=r.e_req, next_open=CI.open.get(int(r.entry_candle_open_time)), actual_entry=r.entry_price,
        entry_slip_bps=(r.entry_price / CI.open.get(int(r.entry_candle_open_time)) - 1) * 1e4 * r.sgn, quantity=r.quantity, notional=r.notional,
        entry_fee_db=r.e_fee, entry_fee_indep=r.entry_price * r.quantity * TAKER,
        stop_db=r.stop_loss_price, stop_indep=sl_ind, tp_db=r.take_profit_price, tp_indep=tp_ind, trailing_dist=r.trailing_stop_distance,
        stop_bps=abs(r.entry_price - r.stop_loss_price) / r.entry_price * 1e4 if r.stop_loss_price else None,
        exit_kind=r.x_kind, exit_reference=r.x_req, actual_exit=r.exit_price, exit_bar_utc=pd.to_datetime(exit_bar, unit="ms", utc=True),
        replay_first_protective=(first_hit[0] if first_hit else None), replay_first_bar_utc=(pd.to_datetime(first_hit[1], unit="ms", utc=True) if first_hit else None),
        replay_ref=first_ref, exit_fee_db=r.x_fee, funding_db=r.funding, funding_payments=r.fund_sum,
        gross_db=r.gross_pnl, gross_indep=gross_i, fees_db=r.fees, fees_indep=fees_i, net_db=r.net_pnl, net_indep=gross_i - fees_i - r.fund_sum,
        net_bps=r.net_pnl / r.notional * 1e4, hold_s=r.holding_seconds,
    ))
TR = pd.DataFrame(tr_rows)
TR.to_csv(f"{OUT}/trade_trace_examples.csv", index=False)
chk = pd.DataFrame({
    "features_replay==stored(close,rsi,atr,regime)": np.isclose(TR.stored_close, TR.replay_close) & np.isclose(TR.stored_rsi, TR.replay_rsi) & np.isclose(TR.stored_atr, TR.replay_atr) & (TR.stored_regime == TR.replay_regime),
    "order_atr==replay_atr": np.isclose(TR.order_intent_atr, TR.replay_atr),
    "signal_replay==db": TR.db_signal == TR.replay_signal,
    "conf_replay==db": np.isclose(TR.db_conf, TR.replay_conf, atol=1e-6),
    "order_requested_price==signal_close": np.isclose(TR.expected_entry_price.astype(float), TR.replay_close),
    "stop_indep==db": np.isclose(TR.stop_indep, TR.stop_db, rtol=1e-9) | TR.stop_db.isna(),
    "tp_indep==db": np.isclose(TR.tp_indep, TR.tp_db, rtol=1e-9) | TR.tp_db.isna(),
    "net_indep==db": np.isclose(TR.net_indep, TR.net_db, atol=1e-7),
})
print(f"{len(TR)} traces. Check pass rates:"); print(chk.mean().round(3).to_string())
print(TR[["generation", "family", "side", "exit_reason", "decision_lag_s", "db_signal", "replay_signal", "council_reason", "entry_slip_bps", "stop_bps",
          "exit_kind", "replay_first_protective", "exit_bar_utc", "replay_first_bar_utc", "net_bps", "hold_s"]].to_string(index=False))

# =========================================================== 3b. PARITY ON A LARGER RANDOM SAMPLE OF DECISIONS (signal replay)
print("\n=== SIGNAL REPLAY PARITY on 400 random directional decisions (incl. untraded) ===")
D = q("""select d.market_candle_open_time bar, d.agent_signal::text sig, d.agent_signal_confidence conf, sv.dna::text dna
         from decisions d join strategy_versions sv on sv.id=d.strategy_version_id
         where d.agent_signal::text in ('LONG','SHORT') and (d.agent_signal_reasoning->>'protective_only') is null
         order by md5(d.id::text) limit 400""")
match = []
for _, r in D.iterrows():
    k = IDX.get(int(r.bar))
    if k is None or k < FEATURE_WINDOW:
        continue
    win = C.iloc[k - FEATURE_WINDOW + 1: k + 1]
    ctx = compute_features(win, symbol="SOL", timeframe="1m"); prev = compute_features(win.iloc[:-1], symbol="SOL", timeframe="1m")
    dna = StrategyDNA.model_validate(json.loads(r.dna)); cur, prv = compute_population_features(win, [dna])
    s = evaluate_signal(dna, build_feature_view(ctx, prev, cur, prv))
    match.append((s.bias.value == r.sig, abs(s.confidence - r.conf) < 1e-6))
m = np.array(match)
print(f"replayed {len(m)}: direction match {m[:, 0].mean():.4f}, confidence match {m[:, 1].mean():.4f}")

# =========================================================== 4. STRATEGY SIGNAL AUDIT (lateness, persistence, predictiveness)
print("\n=== STRATEGY SIGNAL AUDIT ===")
S = q("""select d.market_candle_open_time bar, d.agent_signal::text side, sv.dna->>'strategy_family' family,
                sv.dna->>'direction_mode' dmode, count(*) n
         from decisions d join strategy_versions sv on sv.id=d.strategy_version_id
         where d.agent_signal::text in ('LONG','SHORT') and (d.agent_signal_reasoning->>'protective_only') is null
         group by 1,2,3,4""")
S["bar"] = S.bar.astype("int64")
S = add_forward(S, C.rename(columns={}), IDX)
cl = C.close.to_numpy()
k = S.bar.map(IDX).to_numpy()
sg = np.where(S.side == "LONG", 1.0, -1.0)
for h in (1, 5, 10, 30):
    S[f"pre_{h}"] = np.where(k - h >= 0, (cl[k] / cl[np.maximum(k - h, 0)] - 1) * 1e4 * sg, np.nan)  # move ALREADY happened, signal direction
S["gap_bps"] = (C.open.to_numpy()[np.minimum(k + 1, len(C) - 1)] / cl[k] - 1) * 1e4 * sg       # signal close -> fill bar open
rows = []
nbars = C.open_time.between(S.bar.min(), S.bar.max()).sum()
for fam, g in S.groupby("family"):
    u = g.groupby(["bar", "side"]).size().reset_index()
    netdir = g.groupby("bar").apply(lambda x: np.sign((x.side == "LONG").sum() - (x.side == "SHORT").sum())).reindex(
        C.open_time[C.open_time.between(S.bar.min(), S.bar.max())], fill_value=0)
    gs = g.drop_duplicates(["bar", "side"]).sort_values("bar")
    same_prev = gs.apply(lambda r: ((gs.bar == r.bar - 60000) & (gs.side == r.side)).any(), axis=1).mean() if len(gs) < 6000 else np.nan
    rev10 = np.mean([((gs.bar > r.bar) & (gs.bar <= r.bar + 600000) & (gs.side != r.side)).any() for r in gs.itertuples()]) if len(gs) < 6000 else np.nan
    row = dict(family=family if (family := fam) else fam, unique_signals=len(gs), signal_bar_share=gs.bar.nunique() / nbars,
               direction_modes=",".join(sorted(g.dmode.fillna("auto").unique())), long_share=(gs.side == "LONG").mean(),
               persistence_prev_bar_same=same_prev, reversal_within_10m=rev10, netdir_autocorr_lag1=pd.Series(netdir.to_numpy()).autocorr(1),
               pre1=gs.pre_1.mean(), pre5=gs.pre_5.mean(), pre10=gs.pre_10.mean(), pre30=gs.pre_30.mean(), gap_to_fill=gs.gap_bps.mean())
    for h in (1, 5, 10, 30, 60):
        row[f"post{h}"] = gs[f"fwd_{h}"].mean()
    row["t_post30"] = cluster_t(gs.fwd_30, block2h(gs.bar))[0]
    row["character"] = ("trend-chasing (enters after move)" if row["pre10"] > 3 else "fading (enters against move)" if row["pre10"] < -3 else "neutral entry") + \
                       (" / no follow-through" if abs(row["post30"]) < 3 or abs(row["t_post30"]) < 2 else (" / continuation" if row["post30"] > 0 else " / reversal"))
    rows.append(row)
SA = pd.DataFrame(rows).sort_values("unique_signals", ascending=False)
SA.to_csv(f"{OUT}/strategy_signal_audit.csv", index=False)
print(SA.to_string(index=False))
allg = S.drop_duplicates(["bar", "family", "side"])
print("ALL families: pre10 %.2f pre30 %.2f | post10 %.2f post30 %.2f | gap signal-close->fill-open %.3f bps" % (
      allg.pre_10.mean(), allg.pre_30.mean(), allg.fwd_10.mean(), allg.fwd_30.mean(), allg.gap_bps.mean()))
DM = q("select sv.dna->>'direction_mode' m, sv.dna->'stop_loss'->>'method' slm, count(*) from agents a join strategy_versions sv on sv.id=a.strategy_version_id group by 1,2 order by 3 desc")
print("DNA direction_mode / stop method census (agents):", DM.to_dict("records"))

# =========================================================== 5. COUNCIL / LLM EFFECT
print("\n=== COUNCIL (LLM) EFFECT ===")
CD = q("select market_candle_open_time bar, final_bias::text side, final_confidence conf, council_status, successful_analysts from council_decisions")
CD["bar"] = CD.bar.astype("int64")
dirc = CD[CD.side.isin(["LONG", "SHORT"])].copy()
dirc = add_forward(dirc, C, IDX)
for h in (5, 30, 60):
    x = dirc[f"fwd_{h}"]
    print(f"council directional calls (n={len(dirc)}): fwd{h} mean {x.mean():+.2f} bps, dir.acc {np.nanmean(x > 0):.3f}, cluster t {cluster_t(x, block2h(dirc.bar))[0]:+.2f}")
hi = dirc[dirc.conf >= 0.6]
print(f"  high-confidence (>=0.6, i.e. would veto) n={len(hi)}: fwd30 {hi.fwd_30.mean():+.2f}, t {cluster_t(hi.fwd_30, block2h(hi.bar))[0]:+.2f}")
CR = q("""select d.market_candle_open_time bar, d.agent_signal::text side, d.risk_reasoning->'council'->>'reason' reason,
                 (d.risk_reasoning->>'skipped') skipped, d.order_id is not null as ordered
          from decisions d where d.agent_signal::text in ('LONG','SHORT') and d.risk_reasoning->'council' is not null""")
CR["bar"] = CR.bar.astype("int64")
CR = add_forward(CR.drop_duplicates(["bar", "side", "reason", "ordered"]), C, IDX)
print(CR.groupby(["reason"]).agg(n=("fwd_30", "size"), fwd10=("fwd_10", "mean"), fwd30=("fwd_30", "mean"), fwd60=("fwd_60", "mean")).round(2).to_string())
V = q("""select d.market_candle_open_time bar, d.agent_signal::text side from decisions d
         where d.risk_reasoning->>'skipped'='council_directional_conflict'""")
V["bar"] = V.bar.astype("int64"); V = add_forward(V.drop_duplicates(), C, IDX)
print(f"VETOED signals (unique bar,side) n={len(V)}: their fwd30 {V.fwd_30.mean():+.2f} (t {cluster_t(V.fwd_30, block2h(V.bar))[0]:+.2f}) "
      f"-> a positive value means the veto removed winners")
tx = clean.copy()
tx["council_reason"] = tx.d_risk.map(lambda s: (json.loads(s).get("council") or {}).get("reason") if s else None)
tx["net_bps"] = tx.net_pnl / tx.notional * 1e4
print(tx.groupby("council_reason").agg(trades=("net_bps", "size"), net_bps=("net_bps", "mean"), wr=("win", "mean")).round(3).to_string())

# =========================================================== 6. SKILL PERSISTENCE (does selection pick real edge?)
print("\n=== STRATEGY SKILL PERSISTENCE across generations (same strategy_version carried as elite) ===")
A = q("select a.id::text agent_id, a.generation, a.strategy_version_id::text sv, a.fitness from agents a")
tg = clean.merge(A[["agent_id", "sv"]], on="agent_id")
tg["net_bps"] = tg.net_pnl / tg.notional * 1e4
per = tg.groupby(["sv", "generation"]).agg(n=("net_bps", "size"), e=("net_bps", "mean")).reset_index()
per = per[per.n >= 5]
pairs = per.merge(per, on="sv", suffixes=("_g", "_next"))
pairs = pairs[pairs.generation_next == pairs.generation_g + 1]
from scipy.stats import spearmanr
print(f"versions traded in consecutive generations: {len(pairs)}; Spearman(exp gen g, exp gen g+1) = "
      f"{spearmanr(pairs.e_g, pairs.e_next).correlation:.3f}")
af = A.merge(tg.groupby("agent_id").net_bps.mean().rename("own_exp"), on="agent_id")
print("Spearman(agent.fitness, agent's own realized exp) =", round(spearmanr(af.fitness, af.own_exp, nan_policy="omit").correlation, 3))
print("mean net bps by generation:", tg.groupby("generation").net_bps.mean().round(2).to_dict())

# =========================================================== 7. SIZING
print("\n=== SIZING ===")
print("notional $ quantiles:", clean.notional.quantile([.05, .25, .5, .75, .95]).round(2).to_dict())
print("leverage:", clean.leverage.value_counts().head(5).to_dict())
risk_amt = (clean.entry_price - clean.stop_loss_price).abs() * clean.quantity
rt_cost = clean.notional * (2 * TAKER) + clean.notional * 6 / 1e4
print("round-trip cost / risk-at-stop: median %.2f, p90 %.2f" % ((rt_cost / risk_amt).median(), (rt_cost / risk_amt).quantile(.9)))
print("stop distance bps: median %.1f p10 %.1f p90 %.1f" % tuple((clean.entry_price - clean.stop_loss_price).abs().div(clean.entry_price).mul(1e4).quantile([.5, .1, .9])))
print("TP distance bps: median %.1f" % (clean.entry_price - clean.take_profit_price).abs().div(clean.entry_price).mul(1e4).median())
DR = q("select risk_reasoning->'reasons'->>0 r, count(*) from decisions where agent_signal::text in ('LONG','SHORT') group by 1 order by 2 desc")
print("risk outcome of directional decisions:", DR.to_dict("records"))

# =========================================================== 8. LOSS WATERFALL (per average clean, non-rollover trade; bps of entry notional)
print("\n=== LOSS WATERFALL ===")
W = clean[clean.exit_reason != "generation_rollover"].copy()
n0 = W.entry_price * W.quantity
sc = W.sig_bar.map(CI.close); eo = W.entry_candle_open_time.map(CI.open)
xbw = (W.closed_at.astype("int64") // 10**6 // 60000) * 60000
xclose = xbw.map(CI.close)
comp = pd.DataFrame({
    "raw_move_signal_close_to_exit_reference": (W.x_req / sc - 1) * 1e4 * W.sgn,
    "signal_latency_close_to_fill_bar_open": (eo / sc - 1) * 1e4 * W.sgn,
    "hold_same_duration_exit_at_bar_close": (xclose / eo - 1) * 1e4 * W.sgn,
    "exit_logic_vs_same_duration_close": (W.x_req / eo - 1) * 1e4 * W.sgn - (xclose / eo - 1) * 1e4 * W.sgn,
    "entry_slippage": -(W.entry_price / eo - 1) * 1e4 * W.sgn,
    "entry_fee": -W.e_fee / n0 * 1e4,
    "exit_slippage": (W.exit_price / W.x_req - 1) * 1e4 * W.sgn,
    "exit_fee": -W.x_fee / n0 * 1e4,
    "funding": -W.funding / n0 * 1e4,
    "net_db": W.net_pnl / n0 * 1e4,
})
# fixed 10m reference edge for the same trades (exit-independent)
k10 = np.minimum(W.entry_candle_open_time.map(IDX).to_numpy() + 9, len(C) - 1)
comp["fixed10m_mid_edge"] = (C.close.to_numpy()[k10] / eo.to_numpy() - 1) * 1e4 * W.sgn
m = comp.mean()
recon = m.signal_latency_close_to_fill_bar_open + m.hold_same_duration_exit_at_bar_close + m.exit_logic_vs_same_duration_close + \
        m.entry_slippage + m.entry_fee + m.exit_slippage + m.exit_fee + m.funding
wf = pd.DataFrame([
    ("Signal latency (signal close -> fill-bar open)", m.signal_latency_close_to_fill_bar_open),
    ("Raw directional move over the actual hold (fill-bar open -> exit-bar close, mid)", m.hold_same_duration_exit_at_bar_close),
    ("Exit logic (actual exit reference vs exit-bar close)", m.exit_logic_vs_same_duration_close),
    ("= Gross edge at reference prices", m.signal_latency_close_to_fill_bar_open + m.hold_same_duration_exit_at_bar_close + m.exit_logic_vs_same_duration_close - m.signal_latency_close_to_fill_bar_open),
    ("Entry slippage", m.entry_slippage), ("Entry fee", m.entry_fee), ("Exit slippage", m.exit_slippage), ("Exit fee", m.exit_fee),
    ("Funding", m.funding), ("= Final expectancy (sum of components from fill-bar open)", recon - m.signal_latency_close_to_fill_bar_open),
    ("Final expectancy (DB net_pnl / notional)", m.net_db),
    ("Memo: fixed 10m hold, mid (exit-independent signal edge)", m.fixed10m_mid_edge),
], columns=["component", "bps_per_trade"])
wf["t_cluster"] = [np.nan] * len(wf)
for i, col in [(0, "signal_latency_close_to_fill_bar_open"), (1, "hold_same_duration_exit_at_bar_close"), (2, "exit_logic_vs_same_duration_close"), (11, "fixed10m_mid_edge")]:
    wf.loc[i, "t_cluster"] = cluster_t(comp[col], block2h(W.sig_bar))[0]
wf.to_csv(f"{OUT}/loss_waterfall.csv", index=False)
print(wf.to_string(index=False))
print("waterfall by exit reason (bps):")
print(comp.groupby(W.exit_reason.values).mean()[["hold_same_duration_exit_at_bar_close", "exit_logic_vs_same_duration_close", "entry_slippage",
      "entry_fee", "exit_slippage", "exit_fee", "net_db"]].round(2).assign(n=W.exit_reason.value_counts()).to_string())
