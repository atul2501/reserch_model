"""Entry Quality Model V1 - SHADOW ONLY. Nothing in the live decision path imports this module.

Scores "given the market context at the moment an existing strategy's own entry signal fired,
how likely is this specific trade to win" - it does not generate signals itself, it only grades
signals the strategy layer already produced (spec: Phase-4 forensic audit, 2026-09-30).

The model is a plain logistic regression (StandardScaler + LogisticRegression, scikit-learn,
class_weight="balanced") fit on 28,343 real historical trade entries, chronologically split
70/15/15 into train/validation/OOS - see docs/entry_quality_v1_training.md for the exact
methodology. Coefficients are frozen here as plain floats so scoring at runtime needs no ML
library: sigmoid(dot(standardized_features, coef) + intercept) is the entire model, matching
this module's only job (grade, don't learn) and this project's precedent (shadow_fitness.py)
of keeping shadow analytics dependency-free and easy to audit line by line.

Training window: 2026-09-27 08:11 -> 2026-09-30 13:52 (the only data available at fit time).
That is four days of one instrument - explicitly NOT enough to call this validated; the OOS AUC
below is walk-forward-consistent evidence worth shadow-testing further, not proof of a durable
edge. See the "insufficient data" framing throughout the audit dashboard this model feeds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

MODEL_VERSION = "entry_quality_v1"
FEATURE_VERSION = "ef_v1"  # app.analytics.entry_quality_features.FEATURE_COLUMNS below

# Order MUST match training. Every feature except the ones in DIRECTION_SIGNED_FEATURES is used
# as-is; direction-signed ones are multiplied by +1 (LONG) / -1 (SHORT) before scoring, so the
# model always sees "in this trade's own direction" rather than raw up/down.
FEATURE_COLUMNS: tuple[str, ...] = (
    "ret_1", "ret_3", "ret_5", "ret_10", "rsi_14", "rsi_14_slope", "macd_hist", "macd_hist_slope",
    "ema_fast_slope", "price_dist_ema_fast", "price_dist_ema_slow", "atr_14", "atr_pctile",
    "bb_width", "bb_position", "volume_ratio", "trend_strength", "candle_body", "upper_wick",
    "lower_wick", "dist_from_high20", "dist_from_low20",
)
DIRECTION_SIGNED_FEATURES: frozenset[str] = frozenset({
    "ret_1", "ret_3", "ret_5", "ret_10", "rsi_14_slope", "macd_hist", "macd_hist_slope",
    "ema_fast_slope", "price_dist_ema_fast", "price_dist_ema_slow", "trend_strength",
    "dist_from_high20", "dist_from_low20",
})

# Frozen artifact fit on TRAIN+VALIDATION (24,091 of the 28,343 trades, chronologically first
# 85%) so the deployed weights use every bar available before the OOS window. TRAIN/VALIDATION/
# OOS_AUC below are measured from a SEPARATE fit on TRAIN alone, evaluated on all three splits -
# that is the honest walk-forward number; it is not the same fit as the frozen weights (which
# additionally see the validation split), by design (same convention as scikit-learn's
# refit-on-train+val-before-deploy pattern).
_SCALER_MEAN: tuple[float, ...] = (
    0.000136, -0.000025, -0.000108, -0.000311, 48.134484, 0.015166, -0.008532, -0.001093,
    -0.000174, -0.000102, -0.000235, 0.001031, 0.611393, 0.005908, -0.061816, 1.639479,
    -0.000132, 0.697465, 0.149215, 0.15332, 0.000025, -0.000423,
)
_SCALER_SCALE: tuple[float, ...] = (
    0.00113, 0.002041, 0.002563, 0.003368, 15.692041, 9.863304, 0.060749, 0.03848,
    0.001222, 0.001921, 0.003488, 0.000359, 0.209711, 0.002927, 0.903732, 2.212375,
    0.002008, 0.284877, 0.207532, 0.209249, 0.004612, 0.003744,
)
_COEF: tuple[float, ...] = (
    0.084004, 0.108214, -0.098566, -0.096381, -0.304574, -0.228892, -0.082075, 0.290163,
    -0.132563, -0.277656, -0.0871, 0.069909, 0.107322, -0.132378, 0.219152, -0.030641,
    0.09559, -0.080968, 0.109938, 0.001196, 0.0212, -0.191663,
)
_INTERCEPT: float = -0.089273

TRAIN_SAMPLES = 19_840
VALIDATION_SAMPLES = 4_251
OOS_SAMPLES = 4_252
TRAIN_AUC = 0.668
VALIDATION_AUC = 0.622
OOS_AUC = 0.634
TRAINED_AT = datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)
TRAINING_WINDOW_START_MS = 1_790_496_660_000  # first scored signal bar (2026-09-27 08:11 UTC)
# End of the frozen weights' train+val window (85% mark, chronologically) = 2026-09-30 03:32 UTC.
# Any trade whose signal fired AFTER this is genuine OOS: this exact model has never seen it.
TRAINING_WINDOW_END_MS = 1_790_739_120_000
OOS_WINDOW_END_MS = 1_790_776_320_000  # last scored signal bar in the dataset (2026-09-30 13:52 UTC)


@dataclass(frozen=True)
class EntryQualityPrediction:
    probability: float                     # P(win | context), 0..1
    features_used: dict[str, float]
    model_version: str = MODEL_VERSION
    missing_features: tuple[str, ...] = field(default_factory=tuple)


def predict_proba(raw_features: dict[str, float], *, side: str) -> EntryQualityPrediction | None:
    """Scores one entry context. Returns None (never raises) if a required feature is missing or
    non-finite - the caller (the audit service) counts these as coverage gaps, and the live
    trading system never calls this at all, so a None here can never affect a real trade."""
    sign = 1.0 if side == "LONG" else -1.0
    missing: list[str] = []
    z = 0.0
    for i, name in enumerate(FEATURE_COLUMNS):
        v = raw_features.get(name)
        if v is None or isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            missing.append(name)
            continue
        if name in DIRECTION_SIGNED_FEATURES:
            v = v * sign
        standardized = (v - _SCALER_MEAN[i]) / _SCALER_SCALE[i]
        z += standardized * _COEF[i]
    if missing:
        return None
    z += _INTERCEPT
    probability = 1.0 / (1.0 + math.exp(-z))
    return EntryQualityPrediction(probability=probability, features_used=dict(raw_features),
                                  missing_features=tuple(missing))


def model_status() -> dict:
    """The Model Status card's data - static provenance, no DB access."""
    return {
        "status": "SHADOW", "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
        "model_type": "LogisticRegression", "train_samples": TRAIN_SAMPLES,
        "validation_samples": VALIDATION_SAMPLES, "oos_samples": OOS_SAMPLES,
        "train_auc": TRAIN_AUC, "validation_auc": VALIDATION_AUC, "oos_auc": OOS_AUC,
        "trained_at": TRAINED_AT.isoformat(), "n_features": len(FEATURE_COLUMNS),
        "affects_live_trading": False,
    }
