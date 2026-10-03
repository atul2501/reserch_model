"""The research already done (2026-09 / 2026-10), encoded as registry entries so it is never silently repeated.

Every number below is copied from the report named in `evidence`; nothing is re-estimated here. Seeds are marked
`seed: true` and are excluded from the multiple-testing count of NEW experiments (they are the reason the bar is high).
"""
from __future__ import annotations

from app.edge_research.registry import ExperimentRegistry, ExperimentSpec

R1 = "research/entry_quality_2026-10-02/REPORT.md + outputs/models_out.txt, post_out.txt"
R2 = "research/phase2_signal_horizon/PHASE2_REPORT.md + walkforward_selection.csv"
R3 = "research/forensic_audit/FORENSIC_AUDIT_REPORT.md"
R4 = "research/pretrade_decision_architecture/PRETRADE_ARCHITECTURE_REPORT.md"
EF_V1 = ("ret_1", "ret_3", "ret_5", "ret_10", "rsi_14", "rsi_14_slope", "macd_hist", "macd_hist_slope", "ema_fast_slope",
         "price_dist_ema_fast", "price_dist_ema_slow", "atr_14", "atr_pctile", "bb_width", "bb_position", "volume_ratio",
         "trend_strength", "candle_body", "upper_wick", "lower_wick", "dist_from_high20", "dist_from_low20")


def _seed(experiment_id, hypothesis, spec_kwargs, status, decision, oos_net, evidence, **extra):
    return dict(experiment_id=experiment_id, hypothesis=hypothesis, spec=ExperimentSpec(hypothesis=hypothesis, **spec_kwargs),
                status=status, decision=decision, oos_net=oos_net, evidence=evidence, extra=extra)


SEEDS = [
    _seed("SEED-EQ-V1", "Entry Quality V1 logistic regression grades strategy entries (P(win))",
          dict(signal_source="strategy_trades", features=EF_V1, target="net_pnl_gt_0", horizon_min=0, model="logistic",
               hyperparameters={"frozen": "entry_quality_v1"}, selection="threshold_0.60"),
          "NO EDGE", "OOS_FAILED", -11.69, R1, oos_auc=0.546, note="higher P(win) -> higher win rate but LOWER expectancy"),
    *[_seed(f"SEED-ML-{m.upper()}-{fs}", f"Entry-quality classifier ({m}, {fs} features) filters strategy trades",
            dict(signal_source="strategy_trades", features=EF_V1 if fs == "v1" else EF_V1 + ("ext_27_candle_features",),
                 target="net_pnl_gt_0", horizon_min=0, model=m, selection="validation_threshold"),
            "NO EDGE", "OOS_FAILED", net, R1, folds_positive=0)
      for m, fs, net in [("logistic", "ext", -10.70), ("random_forest", "v1", -13.66), ("random_forest", "ext", -13.62),
                         ("hist_gradient_boosting", "v1", -19.70), ("hist_gradient_boosting", "ext", -18.22),
                         ("xgboost", "v1", -15.90), ("xgboost", "ext", -14.53)]],
    *[_seed(f"SEED-HZN-{u}-{h}", f"Existing strategy signals ({u}) held a fixed {h} min have positive net expectancy",
            dict(signal_source=f"strategy_signals:{u}", features=(), target="signed_fwd_return_net_bps", horizon_min=h,
                 model="rule"),
            "NO EDGE", "REJECTED", net, R2)
      for u, h, net in [("traded", 1, -13.50), ("traded", 3, -13.67), ("traded", 5, -13.88), ("traded", 10, -14.09),
                        ("traded", 15, -14.41), ("traded", 30, -13.85), ("traded", 60, -11.67),
                        ("all", 1, -13.52), ("all", 5, -13.60), ("all", 10, -13.78), ("all", 30, -12.60), ("all", 60, -11.78)]],
    _seed("SEED-MINMOVE", "Trade only when expected move (ATR*sqrt(h)) exceeds a threshold",
          dict(signal_source="strategy_signals:traded", features=("atr_expected_move",), target="signed_fwd_return_net_bps",
               horizon_min=30, model="rule", hyperparameters={"thresholds_bps": [5, 10, 15, 20, 30, 50]}),
          "NO EDGE", "REJECTED", -11.9, R2),
    _seed("SEED-CONF", "Trade only the top-confidence strategy signals",
          dict(signal_source="strategy_signals:traded", features=("signal_confidence",), target="signed_fwd_return_net_bps",
               horizon_min=60, model="rule", hyperparameters={"top_frac": [0.75, 0.5, 0.25, 0.1]}),
          "NO EDGE", "REJECTED", -8.0, R2),
    _seed("SEED-COOLDOWN", "Reduce turnover with per-family cooldowns",
          dict(signal_source="strategy_signals:traded", features=("cooldown_min",), target="signed_fwd_return_net_bps",
               horizon_min=30, model="rule", hyperparameters={"cooldown_min": [5, 15, 30, 60]}),
          "NO EDGE", "REJECTED", -11.4, R2),
    _seed("SEED-ORDERFLOW-FAMILY", "order_flow strategy family held 30/60 min",
          dict(signal_source="strategy_signals:traded", features=(), target="signed_fwd_return_net_bps", horizon_min=60,
               model="rule", universe={"family": "order_flow"}),
          "NO EDGE", "OOS_FAILED", -0.76, R2, windows_net=[-6.0, -5.5, 11.8], note="positive only in the last window (drift)"),
    _seed("SEED-CANDLE-FLOW", "Bar-level candle flow-imbalance proxy (volume-weighted candle colour) continuation",
          dict(signal_source="bar:candle_flow_imbalance", features=("flow_imbalance_5", "flow_imbalance_10", "flow_imbalance_20"),
               target="signed_fwd_return_net_bps", horizon_min=30, model="rule"),
          "NO EDGE", "REJECTED", None, R2, gross_bps="+2 to +7 (|t|<2.2), below cost"),
    _seed("SEED-COMBOS", "Strategy x regime x side combinations",
          dict(signal_source="strategy_signals:traded", features=("family", "regime", "side"), target="signed_fwd_return_net_bps",
               horizon_min=30, model="rule", hyperparameters={"min_bars": 30}),
          "NO EDGE", "REJECTED", None, R2, note="0 of 40 combos above cost in >=3 of 4 quarters"),
    _seed("SEED-EXITS", "Redesign exits (ATR stop/target grid, trailing, fixed time)",
          dict(signal_source="strategy_signals:traded", features=(), target="signed_fwd_return_net_bps", horizon_min=60,
               model="rule", exit="atr_sl_tp_grid"),
          "NO EDGE", "REJECTED", -11.4, R2, note="exit design cannot create an edge entries lack"),
    _seed("SEED-WF-GRID", "Walk-forward search over ~16k rules (universe x horizon x min-move x confidence x cooldown)",
          dict(signal_source="strategy_signals:all", features=("grid_16k",), target="signed_fwd_return_net_bps", horizon_min=60,
               model="rule", selection="validation_best_of_grid"),
          "NO EDGE", "OOS_FAILED", -21.4, R2, windows_net=[3.17, -2.89, -30.04]),
    _seed("SEED-LLM-COUNCIL", "LLM council direction (8 analysts, gpt-oss:120b) predicts SOL",
          dict(signal_source="llm_council", features=("council_bias", "council_confidence"), target="signed_fwd_return_net_bps",
               horizon_min=30, model="llm"),
          "NO EDGE", "REJECTED", None, R3, directional_accuracy=0.48, t_stat=0.26),
    _seed("SEED-BTC-LEAD-1M", "BTC 1m residual move leads SOL's next minute",
          dict(signal_source="bar:candles+btc", features=("btc_resid_1",), target="signed_fwd_return_net_bps", horizon_min=1,
               model="descriptive"),
          "WEAK EDGE", "REJECTED", None, R3, gross_bps="+0.7 to +0.9 (t~1.4)", note="lead-lag exists but is mostly intra-minute"),
    _seed("SEED-LATENCY", "Removing the LLM decision latency improves expectancy",
          dict(signal_source="pretrade:latency", features=("decision_latency",), target="net_expectancy_bps", horizon_min=0,
               model="replay"),
          "NO EDGE", "REJECTED", -13.43, R4, baseline_bps=-13.52),
]


def install_seeds(registry: ExperimentRegistry) -> int:
    """Idempotent: appends seeds whose experiment_id is not yet in the registry. Returns how many were added."""
    have = {r.get("experiment_id") for r in registry.all()}
    added = 0
    for s in SEEDS:
        if s["experiment_id"] in have:
            continue
        registry.record(s["spec"], result={"experiment_id": s["experiment_id"], "oos_net_expectancy_bps": s["oos_net"],
                                           "evidence": s["evidence"], **s["extra"]},
                        decision=s["decision"], status=s["status"], data_start_ms=1790496660000,
                        data_end_ms=1790958300000, duplicate_level="SEED", seed=True,
                        notes="prior research (seeded)")
        added += 1
    return added
