"""Phase 11-13: leak-free research dataset.

Row = one closed, non-rollover trade with analytics. Decision time = close of the signal bar
(signal_bar_open_time_ms + 60s); the fill happens at the NEXT bar's open. Every market feature is
read from the signal bar's row of a purely trailing feature frame (no shift(-n), no center=True,
no resample of incomplete bars). V1 features come from the PRODUCTION module unchanged.
"""
import sys
import numpy as np
import pandas as pd
from lib import load_trades, D

sys.path.insert(0, r"C:\Users\LENOVO\Desktop\Ftspl\reserch model\reserch_model\backend")
from app.analytics.entry_quality_features import compute_features as v1_compute  # noqa: E402
from app.analytics.entry_quality_model import (FEATURE_COLUMNS as V1_COLS, DIRECTION_SIGNED_FEATURES as V1_SIGNED,  # noqa: E402
                                               predict_proba as v1_predict)

# feature_name -> (source, as_of, direction_signed)
FEATURE_REGISTRY: dict[str, tuple[str, str, bool]] = {}


def reg(name, source, signed):
    FEATURE_REGISTRY[name] = (source, "signal_bar_close (<= decision time)", signed)


for col in V1_COLS:
    reg(col, "candles via production entry_quality_features", col in V1_SIGNED)


def ext_features(c: pd.DataFrame) -> pd.DataFrame:
    """Additional trailing features. c sorted by open_time, contiguous 1m bars."""
    o, h, l, cl, v = c.open, c.high, c.low, c.close, c.volume
    f = pd.DataFrame(index=c.index)
    f["open_time"] = c.open_time
    ret1 = cl.pct_change()
    for n in (30, 60):
        f[f"ret_{n}"] = cl.pct_change(n); reg(f"ret_{n}", "candles", True)
    delta = cl.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    f["rsi_accel"] = rsi.diff(3).diff(3); reg("rsi_accel", "candles", True)
    f["rsi_extreme"] = (rsi - 50).abs(); reg("rsi_extreme", "candles", False)
    ema12, ema50 = cl.ewm(span=12, adjust=False).mean(), cl.ewm(span=50, adjust=False).mean()
    ema200 = cl.ewm(span=200, adjust=False).mean()
    hist = (ema12 - ema50) - (ema12 - ema50).ewm(span=9, adjust=False).mean()
    f["macd_hist_accel"] = hist.diff(3).diff(3) / cl; reg("macd_hist_accel", "candles", True)
    f["mom_accel"] = cl.pct_change(5) - cl.pct_change(5).shift(5); reg("mom_accel", "candles", True)
    f["ema_slow_slope"] = ema50.pct_change(10); reg("ema_slow_slope", "candles", True)
    f["price_dist_ema200"] = (cl - ema200) / ema200; reg("price_dist_ema200", "candles", True)
    f["htf_trend_60"] = (cl.rolling(60).mean() - cl.rolling(60).mean().shift(30)) / cl; reg("htf_trend_60", "candles", True)
    f["htf_trend_240"] = (cl.rolling(240).mean() - cl.rolling(240).mean().shift(60)) / cl; reg("htf_trend_240", "candles", True)
    hh60, ll60 = h.rolling(60).max(), l.rolling(60).min()
    f["pos_in_range60"] = (cl - ll60) / (hh60 - ll60).replace(0, np.nan) - 0.5; reg("pos_in_range60", "candles", True)
    f["vol_10"] = ret1.rolling(10).std(); reg("vol_10", "candles", False)
    f["vol_60"] = ret1.rolling(60).std(); reg("vol_60", "candles", False)
    f["vol_ratio_10_60"] = f.vol_10 / f.vol_60.replace(0, np.nan); reg("vol_ratio_10_60", "candles", False)
    tr = pd.concat([h - l, (h - cl.shift()).abs(), (l - cl.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f["range_expansion"] = (h - l) / atr14.replace(0, np.nan); reg("range_expansion", "candles", False)
    f["extension_atr"] = (cl - ema12) / atr14.replace(0, np.nan); reg("extension_atr", "candles", True)
    d = np.sign(cl - o)
    run = d.groupby((d != d.shift()).cumsum()).cumcount() + 1
    f["consec_dir"] = run * d; reg("consec_dir", "candles", True)
    vma = v.rolling(20).mean()
    f["vol_accel"] = (v.rolling(3).mean() / vma.replace(0, np.nan)); reg("vol_accel", "candles", False)
    lv = np.log1p(v)
    f["vol_z60"] = (lv - lv.rolling(60).mean()) / lv.rolling(60).std().replace(0, np.nan); reg("vol_z60", "candles", False)
    f["body_signed"] = (cl - o) / (h - l).replace(0, np.nan); reg("body_signed", "candles", True)
    return f


def build():
    t = load_trades()
    t = t[~t.is_rollover & t.family.notna() & t.signal_bar_open_time_ms.notna()].copy()
    c = pd.read_parquet(f"{D}/candles.parquet")
    c = c[c.is_final].sort_values("open_time").reset_index(drop=True)
    v1f = v1_compute(c[["open_time", "open", "high", "low", "close", "volume"]])
    ef = ext_features(c)
    feat = v1f.merge(ef, on="open_time")
    feat.to_parquet(f"{D}/feature_frame.parquet")
    t["signal_bar"] = t.signal_bar_open_time_ms.astype("int64")
    t = t.merge(feat.rename(columns={"open_time": "signal_bar"}), on="signal_bar", how="left")
    sgn = np.where(t.side == "LONG", 1.0, -1.0)
    raw_v1 = t[list(V1_COLS)].copy()  # keep unsigned for production V1 scoring
    for name, (_, _, signed) in FEATURE_REGISTRY.items():
        if signed:
            t[name] = t[name] * sgn
    # Production V1 probability (it applies its own sign internally -> pass RAW values)
    probs = []
    for i, row in enumerate(raw_v1.itertuples(index=False)):
        d = dict(zip(V1_COLS, row))
        if any(x is None or (isinstance(x, float) and not np.isfinite(x)) for x in d.values()):
            probs.append(np.nan); continue
        p = v1_predict(d, side=t.side.iat[i])
        probs.append(p.probability if p else np.nan)
    t["p_v1"] = probs
    # Regime as-of signal bar from market_regimes (independent of trade.entry_regime)
    rg = pd.read_parquet(f"{D}/regimes.parquet").sort_values("candle_open_time")
    t = t.sort_values("signal_bar")
    t = pd.merge_asof(t, rg[["candle_open_time", "regime", "confidence"]].rename(
        columns={"candle_open_time": "rg_bar", "regime": "regime_asof", "confidence": "regime_conf"}),
        left_on="signal_bar", right_on="rg_bar", direction="backward")
    reg("regime_conf", "market_regimes as-of signal bar", False)
    # Context: council alignment, signal confidence, setup strength (decision row)
    t["council_aligned"] = np.where(t.council_bias.isna() | (t.council_bias == "NEUTRAL"), 0.0,
                                    np.where(((t.council_bias == "BULLISH") & (t.side == "LONG")) | ((t.council_bias == "BEARISH") & (t.side == "SHORT")), 1.0, -1.0))
    reg("council_aligned", "decisions.council_bias vs side", False)
    t["council_confidence"] = t.council_confidence.fillna(0); reg("council_confidence", "decisions", False)
    t["signal_confidence"] = t.signal_confidence.astype(float); reg("signal_confidence", "decisions", False)
    t["setup_strength"] = t.setup_strength.astype(float); reg("setup_strength", "decisions.agent_signal_reasoning", False)
    # Strategy-recent-performance: family's mean net_bps over trades CLOSED strictly before decision time, last 6h
    t["decision_ms"] = t.signal_bar + 60_000
    allt = load_trades()
    allt = allt[allt.family.notna() & ~allt.flag_stale_rollover]
    allt["closed_ms"] = allt.closed_at.astype("int64") // 10**6
    out = np.full(len(t), np.nan); outn = np.zeros(len(t))
    for fam, g in allt.groupby("family"):
        g = g.sort_values("closed_ms")
        cm = g.closed_ms.to_numpy(); cs = np.concatenate([[0], np.cumsum(g.net_bps.to_numpy())])
        mask = (t.family == fam).to_numpy()
        dm = t.decision_ms.to_numpy()[mask]
        hi = np.searchsorted(cm, dm, side="left")  # strictly closed before decision
        lo = np.searchsorted(cm, dm - 6 * 3600_000, side="left")
        n = hi - lo
        out[mask] = np.where(n >= 20, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)
        outn[mask] = n
    t["fam_recent_exp_6h"] = out; reg("fam_recent_exp_6h", "trades closed_at < decision time (6h)", False)
    t["fam_recent_n_6h"] = outn; reg("fam_recent_n_6h", "trades closed_at < decision time (6h)", False)
    t["hour_utc"] = pd.to_datetime(t.signal_bar, unit="ms", utc=True).dt.hour
    t = t.sort_values(["signal_bar", "trade_id"]).reset_index(drop=True)
    t.to_parquet(f"{D}/dataset.parquet")
    pd.DataFrame([(k, *v) for k, v in FEATURE_REGISTRY.items()],
                 columns=["feature_name", "source", "as_of", "direction_signed"]).assign(
        availability_at_entry=True).to_csv(f"{D}/feature_registry.csv", index=False)
    return t, c, feat


if __name__ == "__main__":
    t, c, feat = build()
    print("rows", len(t), " V1 scorable", t.p_v1.notna().sum())
    print("regime(trade.entry_regime) == regime as-of signal bar:", (t.regime == t.regime_asof).mean().round(4))
    print("features registered:", len(FEATURE_REGISTRY))
    print("NaN share per feature (top):", t[list(FEATURE_REGISTRY)].isna().mean().sort_values(ascending=False).head(6).round(3).to_dict())
