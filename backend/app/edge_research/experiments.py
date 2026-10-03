"""Experiment runner: spec + dataset -> walk-forward OOS evaluation -> objective status -> registry.

Exactly two model types (no model shopping):
  rule   deterministic: trade every row (directional data) or trade in the sign of `direction_feature` (bar data);
         optional ranking by `score_feature`.
  ridge  closed-form ridge regression of the forward return on standardised features, fitted on TRAIN only.
         Cost-aware: a row is tradable only if the predicted GROSS move exceeds the measured cost (+ margin); for bar
         data the side is the sign of the prediction.
Selection: the fraction of tradable rows to keep (all / top 50% / 25% / 10% by score) is chosen on VALIDATION only,
using a threshold whose value comes from the TRAIN score distribution. The final OOS window never influences any
choice. Neighbouring selection levels are reported to measure stability.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.edge_research import evaluate as ev
from app.edge_research.registry import ExperimentRegistry, ExperimentSpec
from app.edge_research.walkforward import assert_no_leakage, split, windows_for

SELECTION_GRID = (1.0, 0.5, 0.25, 0.1)
MIN_VALIDATION_TRADES = 30
MODELS = ("rule", "ridge")


@dataclass
class ExperimentData:
    df: pd.DataFrame
    kind: str              # "directional" | "bar"
    cost_bps: float
    cost_source: str
    note: str = ""


class _Fitted:
    def __init__(self, spec: ExperimentSpec, kind: str, train: pd.DataFrame, cost: float):
        self.spec, self.kind, self.cost = spec, kind, cost
        hp = spec.hyperparameters
        self.margin = float(hp.get("cost_margin_bps", 0.0))
        if spec.model == "ridge":
            X = train[list(spec.features)].to_numpy(float)
            y = train[f"ret_{spec.horizon_min}"].to_numpy(float)
            m = np.isfinite(X).all(axis=1) & np.isfinite(y)
            X, y = X[m], y[m]
            self.mu, self.sd = X.mean(axis=0), X.std(axis=0) + 1e-12
            Z = (X - self.mu) / self.sd
            lam = float(hp.get("alpha", 10.0)) * len(Z)
            self.w = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
            self.b = float(y.mean())
        tr = self.raw_scores(train)
        tr = tr[np.isfinite(tr)]
        self.train_scores = tr if len(tr) else np.array([0.0])

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        Z = (df[list(self.spec.features)].to_numpy(float) - self.mu) / self.sd
        return Z @ self.w + self.b

    def raw_scores(self, df: pd.DataFrame) -> np.ndarray:
        hp = self.spec.hyperparameters
        if self.spec.model == "ridge":
            p = self.predict(df)
            return np.abs(p) if self.kind == "bar" else p
        f = hp.get("score_feature")
        return df[f].to_numpy(float) * (1 if hp.get("score_sign", 1) >= 0 else -1) if f else np.ones(len(df))

    def trades(self, df: pd.DataFrame, frac: float) -> tuple[np.ndarray, np.ndarray]:
        """(mask of traded rows, signed gross return of each row) for selection level `frac`."""
        h = self.spec.horizon_min
        ret = df[f"ret_{h}"].to_numpy(float)
        score = self.raw_scores(df)
        if self.spec.model == "ridge":
            pred = self.predict(df)
            side = np.sign(pred) if self.kind == "bar" else np.ones(len(df))
            tradable = (np.abs(pred) if self.kind == "bar" else pred) > self.cost + self.margin
        else:
            side = np.sign(df[self.spec.hyperparameters["direction_feature"]].to_numpy(float)) if self.kind == "bar" \
                else np.ones(len(df))
            tradable = np.ones(len(df), bool)
        thr = np.quantile(self.train_scores, 1 - frac) if frac < 1 else -np.inf
        mask = tradable & (score >= thr) & np.isfinite(ret) & np.isfinite(score) & (side != 0)
        return mask, ret * side


def run_experiment(spec: ExperimentSpec, data: ExperimentData, registry: ExperimentRegistry, *,
                   justification: str | None = None, dry_run: bool = False,
                   window_days: tuple[float, float, float] = (1.0, 1.0, 2.0)) -> dict:
    if spec.model not in MODELS:
        raise ValueError(f"model must be one of {MODELS} (no model shopping)")
    df = data.df.dropna(subset=["t"]).sort_values("t").reset_index(drop=True)
    data_start = int(df.t.min()) if len(df) else None
    data_end = int(df.t.max()) if len(df) else None
    dup = registry.check(spec, data_end_ms=data_end, justification=justification)
    if not dup.allowed:
        return {"refused": True, "duplicate_level": dup.level, "message": dup.message, "previous": dup.previous}

    h_ms = spec.horizon_min * 60_000
    oos_d, val_d, train_d = window_days
    wins = windows_for(df, horizon_min=spec.horizon_min, oos_days=oos_d, val_days=val_d, min_train_days=train_d)
    per_window, pooled_net, pooled_gross, pooled_t = [], [], [], []
    neighbour_net = {f: [] for f in SELECTION_GRID}
    val_nets = []
    for w in wins:
        tr, va, oo = split(df, w, horizon_ms=h_ms)
        assert_no_leakage(tr, va, oo, horizon_ms=h_ms)
        if len(tr) < 50 or len(va) < 10:
            continue
        fit = _Fitted(spec, data.kind, tr, data.cost_bps)
        best = None
        for frac in SELECTION_GRID:                               # chosen on VALIDATION only
            m, r = fit.trades(va, frac)
            if m.sum() >= MIN_VALIDATION_TRADES:
                v = float((r[m] - data.cost_bps).mean())
                if best is None or v > best[1]:
                    best = (frac, v)
        if best is None:
            per_window.append({"window": w.name, "trades": 0, "note": "no selection level had enough validation trades"})
            continue
        frac, vnet = best
        val_nets.append(vnet)
        m, r = fit.trades(oo, frac)
        gross, net = r[m], r[m] - data.cost_bps
        mt = ev.metrics(net, gross, oo.t.to_numpy()[m], data.cost_bps)
        per_window.append({"window": w.name, "train": w.train, "validation": w.val, "oos": w.oos, "selection_frac": frac,
                           "validation_net_bps": vnet, **mt})
        pooled_net.append(net); pooled_gross.append(gross); pooled_t.append(oo.t.to_numpy()[m])
        for f in SELECTION_GRID:
            mm, rr = fit.trades(oo, f)
            neighbour_net[f].append(rr[mm] - data.cost_bps)

    net = np.concatenate(pooled_net) if pooled_net else np.array([])
    pooled = ev.metrics(net, np.concatenate(pooled_gross) if pooled_gross else np.array([]),
                        np.concatenate(pooled_t) if pooled_t else np.array([]), data.cost_bps)
    neighbours = {f: (float(np.concatenate(v).mean()) if v and len(np.concatenate(v)) else None) for f, v in neighbour_net.items()}
    chosen = [w.get("selection_frac") for w in per_window if w.get("selection_frac")]
    stable = None
    if chosen:
        f0 = max(set(chosen), key=chosen.count)
        k = SELECTION_GRID.index(f0)
        adj = [SELECTION_GRID[j] for j in (k - 1, k + 1) if 0 <= j < len(SELECTION_GRID)]
        stable = all((neighbours.get(a) or -1) > 0 for a in adj)
    traded_windows = [w for w in per_window if w.get("trades", 0) > 0]
    n_tests = sum(1 for r in registry.all() if not r.get("seed")) + 1
    status, decision, reasons = ev.classify(traded_windows, pooled, n_tests=n_tests, neighbours_positive=stable,
                                            validation_net_bps=float(np.mean(val_nets)) if val_nets else None,
                                            windows_available=len(per_window))
    warnings = []
    if val_nets and pooled.get("net_expectancy_bps") is not None and np.mean(val_nets) - pooled["net_expectancy_bps"] > 5:
        warnings.append(f"LARGE VALIDATION/OOS GAP: validation {np.mean(val_nets):+.2f} vs OOS {pooled['net_expectancy_bps']:+.2f} bps")
    if len(traded_windows) <= 1:
        warnings.append("SINGLE OOS WINDOW (or none): no time-stability evidence")
    if (pooled.get("trades") or 0) < 100:
        warnings.append(f"ONLY {pooled.get('trades', 0)} OOS TRADES")
    result = {
        "oos_trades": pooled.get("trades", 0), "oos_gross_expectancy_bps": pooled.get("gross_expectancy_bps"),
        "oos_net_expectancy_bps": pooled.get("net_expectancy_bps"), "oos_profit_factor": pooled.get("profit_factor"),
        "oos_total_net_bps": pooled.get("total_net_bps"), "oos_max_drawdown_bps": pooled.get("max_drawdown_bps"),
        "oos_net_ci95": [pooled.get("net_ci95_low"), pooled.get("net_ci95_high")], "oos_t_stat_net": pooled.get("t_stat_net"),
        "oos_pooled": pooled, "windows": per_window, "neighbour_selection_net_bps": neighbours, "stable_neighbours": stable,
        "cost_assumption_bps": data.cost_bps, "cost_source": data.cost_source, "n_tests_for_correction": n_tests,
        "reasons": reasons, "warnings": warnings, "data_note": data.note,
        "training_periods": [w.get("train") for w in per_window], "validation_periods": [w.get("validation") for w in per_window],
        "oos_periods": [w.get("oos") for w in per_window],
    }
    if dry_run:
        return {"refused": False, "status": status, "decision": decision, **result}
    rec = registry.record(spec, result=result, decision=decision, status=status, data_start_ms=data_start,
                          data_end_ms=data_end, duplicate_level=dup.level, notes=justification or "")
    return {"refused": False, **rec}
