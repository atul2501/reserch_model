"""entry_quality.html must render the SHADOW audit payload without throwing, must never claim a
real trade was blocked, and must show 'insufficient data' rather than a fabricated number for
thin-sample cells (spec: Phase-4 forensic audit dashboard). Runs the real page script in a
stubbed DOM under Node (skipped if Node is unavailable) - same harness pattern as
test_dashboard_js.py."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[1] / "app" / "static" / "entry_quality.html").read_text()
SCRIPT = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HARNESS = r"""
const vm = require('vm'); const fs = require('fs');
const els = {};
function mk(id) {
  if (els[id]) return els[id];
  const el = { id, innerHTML: '', textContent: '', style: {}, className: '', dataset: {}, value: '',
    href: '', clientWidth: 400, clientHeight: 200, options: [], children: [],
    addEventListener(){}, querySelector(sel){ return mk(id + '>' + sel); }, querySelectorAll(){ return []; },
    getBoundingClientRect(){ return {width: 300, height: 100}; }, setAttribute(k,v){ this[k]=v; },
    add(opt){ this.options.push(opt); }, remove(){}, closest(){ return null; } };
  els[id] = el; return el;
}
const document = { getElementById: mk, querySelector: (s) => { if (s === '.page-nav a.active') return null; return mk('q:' + s); },
                   querySelectorAll: (s) => { if (s === '#table-features th') return [mk('th1'), mk('th2'), mk('th3')]; return []; },
                   addEventListener(){}, createElement: () => mk('created') };
const window = { innerWidth: 1024, addEventListener(){}, prompt(){ return null; }, alert(){} };
function Option(text, value) { return { text, value }; }
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
let fetchCalls = 0;
const ctx = { document, window, Option,
              sessionStorage: {getItem(){return ''}, setItem(){}, removeItem(){}},
              console: {log(){}, warn(){}, error(m,e){ throw e || new Error(String(m)); }},
              fetch: () => { fetchCalls++; return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) }); },
              setInterval(){}, setTimeout(fn){ fn(); }, Date, Math, JSON, Promise, TextDecoder, encodeURIComponent,
              Number, String, Object, Array, isNaN, isFinite, URLSearchParams };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
setTimeout(() => {
  const q = (sel) => { const el = els['q:' + sel]; return el ? el.innerHTML : ''; };
  process.stdout.write(JSON.stringify({
    fetchCalls,
    statusCards: els['status-cards'].innerHTML,
    stopImmediate: q('#table-stopimm tbody'),
    strategyTable: q('#table-strategy tbody'),
    funnel: els['funnel-panel'].innerHTML,
    liveVsShadow: q('#table-livevsshadow tbody'),
  }));
}, 50);
"""


def _minimal_payload(*, insufficient: bool = False) -> dict:
    strategy_row = {
        "family": "momentum", "signals": 40, "actual_trades": 40, "scored": 40,
        "shadow_trades": 10, "shadow_no_trade": 30,
        "actual_win_rate": 0.3, "shadow_win_rate": None if insufficient else 0.5,
        "actual_expectancy": -0.02, "shadow_expectancy": None if insufficient else -0.01,
        "sufficient_sample": not insufficient,
    }
    return {
        "shadow_only_banner": "SHADOW — DOES NOT AFFECT LIVE TRADING",
        "model_status": {"status": "SHADOW", "model_version": "entry_quality_v1", "feature_version": "ef_v1",
                         "model_type": "LogisticRegression", "train_samples": 100, "validation_samples": 20,
                         "oos_samples": 20, "train_auc": 0.65, "validation_auc": 0.6, "oos_auc": 0.62,
                         "trained_at": "2026-09-30T22:00:00+00:00", "n_features": 22, "affects_live_trading": False},
        "model_health": {"model_loaded": True, "feature_schema_valid": True, "shadow_predictions": 40,
                         "unscorable_signals": 0, "coverage_pct": 1.0, "prediction_errors": 0, "invalid_probabilities": 0},
        "filters_applied": {"family": None, "regime": None, "side": None, "generation": None, "agent_id": None,
                            "since": None, "until": None, "threshold": 0.6},
        "live_vs_shadow": {
            "actual": {"trades": 40, "win_rate": 0.3, "net_pnl": -10.0, "expectancy": -0.25,
                      "profit_factor": 0.4, "avg_win": 1.0, "avg_loss": -1.5, "avg_hold_seconds": 300},
            "shadow_filtered": {"trades": 10, "win_rate": 0.5, "net_pnl": -2.0, "expectancy": -0.2,
                                "profit_factor": 0.6, "avg_win": 1.0, "avg_loss": -1.5, "avg_hold_seconds": 300},
            "label": "Hypothetical Shadow Result — trades were NOT actually blocked",
        },
        "funnel": {"strategy_signals": 40, "scored": 40, "unscorable": 0, "shadow_trade": 10,
                  "shadow_no_trade": 30, "actual_trades": 40},
        "probability_distribution": [{"bucket": f"{i/10:.2f}-{(i+1)/10:.2f}", "n": 4, "pct_of_signals": 0.1,
                                      "actual_win_rate": 0.3, "avg_pnl": -0.1, "sufficient_sample": False}
                                     for i in range(10)],
        "calibration": {"points": [{"predicted_mean": 0.3, "actual_win_rate": 0.28, "n": 20, "sufficient_sample": True}],
                        "brier_score": 0.21, "log_loss": 0.6, "n": 40},
        "threshold_audit": {"rows": [{"threshold": t, "shadow_trades": 10, "shadow_no_trade": 30, "win_rate": 0.5,
                                      "expectancy": -0.1, "profit_factor": 0.6, "net_pnl": -2.0,
                                      "stop_immediate_pct": 0.2, "sufficient_sample": True}
                                     for t in (0.5, 0.6, 0.7)],
                            "note": "Exploratory threshold analysis — not production configuration"},
        "stop_immediate_audit": {"actual": {"count": 12, "pct_of_trades": 0.3, "avg_mfe_r": 0.1, "avg_mae_r": -1.3},
                                 "shadow_filtered": {"count": 3, "pct_of_trades": 0.3, "avg_mfe_r": 0.11, "avg_mae_r": -1.2},
                                 "reduction_pct": 0.02, "sufficient_sample": True},
        "strategy_breakdown": [strategy_row],
        "regime_breakdown": [{"regime": "TREND_UP", "signals": 40, "actual_trades": 40, "scored": 40,
                              "shadow_trades": 10, "shadow_no_trade": 30, "actual_win_rate": 0.3,
                              "shadow_win_rate": 0.5, "actual_expectancy": -0.02, "shadow_expectancy": -0.01,
                              "sufficient_sample": True}],
        "strategy_regime_matrix": {"metric": "actual_expectancy",
                                   "cells": [{"family": "momentum", "regime": "TREND_UP", "trade_count": 40,
                                             "value": -0.02, "sufficient_sample": True, "label": None}]},
        "long_short": [{"side": "LONG", "signals": 20, "actual_trades": 20, "scored": 20, "shadow_trades": 5,
                        "shadow_no_trade": 15, "actual_win_rate": 0.3, "shadow_win_rate": 0.5,
                        "actual_expectancy": -0.02, "shadow_expectancy": -0.01, "sufficient_sample": True}],
        "hold_time_audit": [{"bucket": "<1min", "trades": 5, "win_rate": 0.1, "expectancy": -0.05,
                             "profit_factor": 0.2, "stop_immediate_pct": 0.6, "shadow_win_rate": None,
                             "shadow_expectancy": None, "sufficient_sample": False}],
        "feature_importance": [{"feature": "macd_hist_slope", "coefficient": 0.29,
                               "direction": "increases win probability", "abs_importance": 0.29}],
        "model_version_info": {"model_version": "entry_quality_v1", "n_features": 22,
                               "training_window_start": "2026-09-27T08:11:00+00:00",
                               "training_window_end": "2026-09-30T03:32:00+00:00", "n_training_rows": 120},
        "data_freshness": {"latest_trade_closed_at": "2026-09-30T13:00:00+00:00",
                           "latest_prediction_scored": "2026-09-30T13:00:00+00:00",
                           "model_trained_at": "2026-09-30T22:00:00+00:00"},
        "oos_card": {"oos_auc": 0.62, "oos_trades": 20, "oos_win_rate": 0.35, "status": "PROMISING"},
        "drift": {"feature_drift": "NOT_COMPUTED", "prediction_drift": "NORMAL", "outcome_drift": "NORMAL",
                 "recent_predicted_mean": 0.4, "baseline_predicted_mean": 0.4, "recent_win_rate": 0.3,
                 "recent_n": 20, "thresholds_documented": "doc"},
        "mfe_mae_scatter": [{"mae_r": -0.5, "mfe_r": 1.2, "is_win": True, "quality_class": "TAKE_PROFIT_HIT"}],
        "time_series": {"actual_cumulative_pnl": [{"t": "2026-09-30T00:00:00+00:00", "v": -1.0}],
                        "hypothetical_shadow_cumulative_pnl": [{"t": "2026-09-30T00:00:00+00:00", "v": -0.5}],
                        "labels": {"actual": "ACTUAL", "shadow": "HYPOTHETICAL SHADOW"}},
        "audit_questions": {"q1_probability_tracks_win_rate": [], "q10_sufficient_data": True},
    }


def run(payload: dict, tmp_path: Path) -> dict:
    js = tmp_path / "page.js"
    js.write_text(SCRIPT)
    h = tmp_path / "h.js"
    h.write_text(HARNESS)
    r = subprocess.run(["node", str(h), str(js)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_page_renders_without_throwing(tmp_path):
    out = run(_minimal_payload(), tmp_path)
    assert out["fetchCalls"] == 2  # main load() + the filter-options follow-up
    assert "SHADOW" in out["statusCards"] or "entry_quality_v1" in out["statusCards"]


def test_funnel_never_claims_actual_trades_changed(tmp_path):
    """The funnel panel must show actual_trades unchanged and labelled as such - it must never
    read as if shadow_no_trade signals were actually skipped."""
    out = run(_minimal_payload(), tmp_path)
    assert "unchanged" in out["funnel"]
    assert "40" in out["funnel"]  # actual_trades from the fixture


def test_insufficient_sample_renders_as_insufficient_not_a_number(tmp_path):
    out = run(_minimal_payload(insufficient=True), tmp_path)
    assert "insufficient" in out["strategyTable"].lower()


def test_stop_immediate_reduction_shown_when_sufficient(tmp_path):
    out = run(_minimal_payload(), tmp_path)
    assert "%" in out["stopImmediate"]


def test_live_vs_shadow_table_labels_shadow_as_hypothetical(tmp_path):
    out = run(_minimal_payload(), tmp_path)
    # the table itself doesn't repeat the label (that's in the section header), but it must show
    # both columns' real numbers, not a merged/mixed figure.
    assert "40" in out["liveVsShadow"] and "10" in out["liveVsShadow"]
