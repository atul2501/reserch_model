"""Pre-trade shadow dataset, dashboard payload and the /pretrade-shadow + /research-lab APIs."""
from __future__ import annotations

import json
import time

import httpx
import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

from app.pretrade.dataset import CostModel, build_dataset, edge_stats, load_records, measured_costs
from app.pretrade.report import build_payload, categorize

T0 = 1_791_000_000_000 - (1_791_000_000_000 % 60_000)
COST = CostModel(fee_bps=8.8, slippage_bps=5.3, source="test", n_trades=10)


def candles(n=200, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.05, n))
    return pd.DataFrame({"open_time": T0 + np.arange(n) * 60_000, "open": c, "high": c + 0.05, "low": c - 0.05, "close": c})


def records(bars, *, direction="LONG", mid=None, gate=True, council=None):
    rows = []
    for i, k in enumerate(bars):
        bt = T0 + k * 60_000
        rows.append({"record_type": "candidate", "decision_id": f"a{i}:{bt}", "decision_ms": bt + 63_000, "signal_bar_open_time_ms": bt,
                     "information_cutoff_ms": bt + 59_999, "agent_id": f"a{i}", "generation": 1, "strategy": "vwap",
                     "direction": direction if isinstance(direction, str) else direction[i], "setup_strength": 0.5, "regime": "RANGE",
                     "price_at_signal": 100.0, "price_at_shadow_execution_point": mid, "gate_allowed": gate,
                     "gate_rejection_reasons": [] if gate else ["risk_rejected"], "risk_reasons": [] if gate else ["risk:below_min_order_notional"],
                     "decision_age_ms": 3000, "signed_drift_bps": 0.0, "spread_bps": 0.84, "council_available": council is not None,
                     "council_direction": council, "council_confidence": 0.7 if council else None,
                     "llm_agrees": (council == direction) if council else None, "council_age_ms": 120_000 if council else None})
    rows.append({"record_type": "bar_summary", "signal_bar_open_time_ms": T0 + bars[0] * 60_000, "market_event_ms": T0 + (bars[0] + 1) * 60_000,
                 "features_started_ms": T0 + (bars[0] + 1) * 60_000 + 2800, "features_completed_ms": T0 + (bars[0] + 1) * 60_000 + 2840,
                 "signal_created_ms": T0 + (bars[0] + 1) * 60_000 + 3050, "decision_ms": T0 + (bars[0] + 1) * 60_000 + 3070,
                 "validation_ms": T0 + (bars[0] + 1) * 60_000 + 3230})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- dataset integrity
def test_forward_returns_use_only_later_bars_and_exact_horizons():
    c = candles()
    ds = build_dataset(records([10, 20]), c, COST)
    for _, r in ds.iterrows():
        k = int((r.bar_time - T0) // 60_000)
        for h in (1, 5, 10, 30, 60):
            exp = (c.close.iloc[k + h] / 100.0 - 1) * 1e4        # entry = signal close fallback (no book mid given)
            assert r[f"return_{h}m_bps"] == pytest.approx(exp)
            assert r[f"net_return_{h}m_bps"] == pytest.approx(exp - COST.total_bps)
    assert (ds.entry_price_source == "signal_close").all()


def test_partial_horizons_are_null_not_estimated():
    c = candles(n=40)
    ds = build_dataset(records([30]), c, COST)
    assert np.isfinite(ds.return_5m_bps.iloc[0]) and np.isnan(ds.return_10m_bps.iloc[0]) and np.isnan(ds.return_60m_bps.iloc[0])
    assert np.isnan(ds.mfe_30m_bps.iloc[0])


def test_gap_in_candles_never_stretches_a_horizon():
    c = candles().drop(index=[15]).reset_index(drop=True)          # bar 15 missing
    ds = build_dataset(records([10]), c, COST)
    assert np.isnan(ds.return_5m_bps.iloc[0])                      # bar 10+5 missing -> NULL, not "the next available bar"


def test_short_returns_are_sign_flipped_and_book_mid_is_the_entry():
    c = candles()
    ds = build_dataset(records([10], direction="SHORT", mid=100.5), c, COST)
    assert ds.entry_price_source.iloc[0] == "l2_mid" and ds.entry_price.iloc[0] == 100.5
    assert ds.return_5m_bps.iloc[0] == pytest.approx(-(c.close.iloc[15] / 100.5 - 1) * 1e4)


def test_vectorised_mfe_mae_match_brute_force():
    c = candles(n=300, seed=4)
    rec = records(list(range(5, 200, 7)), direction=["LONG", "SHORT"] * 14)
    ds = build_dataset(rec, c, COST)
    for _, r in ds.iterrows():
        k = int((r.bar_time - T0) // 60_000)
        for h in (1, 5, 30):
            hi, lo = c.high.iloc[k + 1:k + 1 + h].max(), c.low.iloc[k + 1:k + 1 + h].min()
            up, dn = (hi / r.entry_price - 1) * 1e4, (lo / r.entry_price - 1) * 1e4
            mfe, mae = (up, dn) if r.direction == "LONG" else (-dn, -up)
            assert r[f"mfe_{h}m_bps"] == pytest.approx(mfe) and r[f"mae_{h}m_bps"] == pytest.approx(mae)


def test_costs_are_measured_from_paper_trades_with_explicit_fallback():
    t = pd.DataFrame({"entry_price": [100.0, 200.0], "quantity": [1.0, 0.5], "fees": [0.09, 0.09], "slippage_cost": [0.05, 0.05]})
    m = measured_costs(t, taker_fee=0.00045, slippage_bps_per_side=2.0)
    assert m.fee_bps == pytest.approx(9.0) and m.slippage_bps == pytest.approx(5.0) and m.n_trades == 2 and "measured" in m.source
    f = measured_costs(None, taker_fee=0.00045, slippage_bps_per_side=2.0)
    assert f.total_bps == pytest.approx(13.0) and "configured" in f.source and f.n_trades == 0


def test_edge_stats_warn_on_small_samples_and_report_net_after_cost():
    s = edge_stats(pd.Series([20.0] * 10), pd.Series([T0] * 10), cost_bps=14.0)
    assert s["net_expectancy_bps"] == pytest.approx(6.0) and s["mean_gross_bps"] == pytest.approx(20.0)
    assert any("INSUFFICIENT SAMPLE" in w for w in s["warnings"]) and any("TIME BLOCKS" in w for w in s["warnings"])
    assert s["t_stat_net"] is None                                  # one time block: no t-stat pretending to be evidence


# --------------------------------------------------------------------------- payload
def test_payload_on_empty_dataset():
    p = build_payload(records=pd.DataFrame(), dataset=build_dataset(pd.DataFrame(), candles(), COST), costs=COST,
                      settings_view={"trading_mode": "paper", "pretrade_mode": "shadow"})
    assert p["A_status"]["shadow_status"] == "NO DATA" and p["B_opportunities"]["total_candidates"] == 0
    assert p["M_equity"]["points"] == [] and p["M_equity"]["label"].startswith("HYPOTHETICAL")
    json.dumps(p, default=str)


def test_payload_sections_and_llm_never_authoritative():
    c = candles(n=300)
    rec = pd.concat([records(list(range(5, 150, 3)), council="SHORT"),
                     records(list(range(6, 150, 3)), gate=False)], ignore_index=True)
    ds = build_dataset(rec, c, COST)
    p = build_payload(records=rec, dataset=ds, costs=COST, settings_view={"trading_mode": "paper", "pretrade_mode": "shadow"},
                      horizon=10, now_ms=T0 + 400 * 60_000)
    B = p["B_opportunities"]
    assert B["total_candidates"] == len(ds) and B["would_trade"] + B["would_reject"] == len(ds)
    cats = {r["category"]: r["count"] for r in B["rejection_reasons"]}
    assert cats["minimum_notional"] == B["would_reject"]
    groups = {(r["group"], r["horizon_min"]) for r in p["C_signal_edge"]}
    assert ("ALL SIGNALS", 10) in groups and ("GATE-PASS", 60) in groups and ("SHORT", 1) in groups
    D = p["D_gross_vs_net"]
    assert D["net_expected_move_bps"] == pytest.approx(D["gross_expected_move_bps"] - COST.total_bps)
    assert p["J_llm"]["authority"].startswith("NONE") and p["J_llm"]["disagreement_pct_of_directional"] == 1.0
    assert all(v is None or v == v for v in p["M_equity"]["points"][0].values()) if p["M_equity"]["points"] else True
    assert p["K_latency"]["total_decision_latency"]["p50"] == pytest.approx(3070)


def test_payload_handles_a_large_dataset():
    n_bars = 6000
    c = candles(n=n_bars + 80, seed=9)
    rec = records(list(range(1, n_bars, 1)) * 5)                      # ~30k candidates
    t0 = time.perf_counter()
    ds = build_dataset(rec, c, COST)
    p = build_payload(records=rec, dataset=ds, costs=COST, settings_view={})
    assert len(ds) == len(rec) - 1 and p["B_opportunities"]["total_candidates"] == len(ds)
    assert time.perf_counter() - t0 < 120                            # functional bound, not a benchmark


def test_rejection_categories():
    assert categorize(["risk:below_min_order_notional", "position_already_open"]) == {"minimum_notional", "position_open"}
    assert categorize(["decision_too_old", "price_moved_too_far", "spread_too_wide", "conflicting_signal"]) == {"stale", "price_drift", "spread", "conflict"}
    assert categorize(["risk:max_leverage"]) == {"risk"} and categorize(["weird"]) == {"other"}


def test_load_records_reads_and_caches_jsonl(tmp_path):
    rec = records([3, 4])
    with open(tmp_path / "pretrade_shadow_20261003.jsonl", "w", encoding="utf-8") as fh:
        for r in rec.to_dict("records"):
            fh.write(json.dumps(r) + "\n")
    a = load_records(tmp_path)
    assert len(a) == len(rec) and len(load_records(tmp_path)) == len(rec)


# --------------------------------------------------------------------------- APIs (authenticated viewer)
@pytest_asyncio.fixture
async def api(db_session, monkeypatch, tmp_path):
    from pydantic import SecretStr
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.security import hash_api_key
    from app.main import create_app
    from app.api.routes import pretrade_shadow as ps

    key = "dash-viewer-key-1234"
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", True)
    monkeypatch.setattr(s, "api_keys", SecretStr(f"dv:viewer:{hash_api_key(key)}"))
    monkeypatch.setattr(s, "pretrade_shadow_dir", str(tmp_path / "shadow"))
    monkeypatch.setattr(s, "microstructure_dir", str(tmp_path / "micro"))
    monkeypatch.setattr(s, "edge_registry_path", str(tmp_path / "registry.jsonl"))
    monkeypatch.setattr(ps, "_CACHE", {})
    app = create_app()

    async def _db():
        yield db_session
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.headers.update({"X-API-Key": key})
        yield c


async def test_pretrade_shadow_api_empty_and_with_data(api, db_session, tmp_path):
    from app.models.market import MarketCandle
    r = await api.get("/api/pretrade-shadow/summary")
    assert r.status_code == 200 and r.json()["A_status"]["shadow_status"] == "NO DATA"
    c = candles(n=120)
    for row in c.itertuples():
        db_session.add(MarketCandle(symbol="SOL", timeframe="1m", open_time=int(row.open_time), close_time=int(row.open_time) + 59_999,
                                    open=row.open, high=row.high, low=row.low, close=row.close, volume=1.0, is_final=True, source="test"))
    await db_session.commit()
    d = tmp_path / "shadow"; d.mkdir()
    with open(d / "pretrade_shadow_20261003.jsonl", "w", encoding="utf-8") as fh:
        for rr in records([10, 20, 30]).to_dict("records"):
            fh.write(json.dumps(rr) + "\n")
    from app.api.routes import pretrade_shadow as ps
    ps._CACHE.clear()
    body = (await api.get("/api/pretrade-shadow/summary?horizon=5")).json()
    assert body["B_opportunities"]["total_candidates"] == 3 and body["selected_horizon_min"] == 5
    assert body["banner"].startswith("SHADOW") and body["cost_model"]["source"].startswith("configured")   # no paper trades -> says so
    csv = await api.get("/api/pretrade-shadow/decisions.csv")
    assert csv.status_code == 200 and "return_5m_bps" in csv.text.splitlines()[0]
    assert (await api.get("/api/pretrade-shadow/summary", headers={"X-API-Key": ""})).status_code == 401


async def test_research_lab_api(api):
    from app.edge_research.registry import ExperimentRegistry
    from app.edge_research.seeds import install_seeds
    install_seeds(ExperimentRegistry())
    body = (await api.get("/api/research-lab/summary")).json()
    assert body["current_status"]["deployable_edge"] == "NO"
    assert body["current_status"]["seeded_prior_experiments"] > 0 and body["failures"]
    nets = [r["oos_net_expectancy_bps"] for r in body["leaderboard"]]
    assert nets == sorted(nets, reverse=True)                        # ranked by OOS NET expectancy
    assert body["next_experiment"]["action"] == "COLLECT_DATA"


async def test_pages_are_served(api):
    for path in ("/pretrade-shadow", "/research-lab"):
        r = await api.get(path)
        assert r.status_code == 200 and "<!doctype html>" in r.text.lower()
