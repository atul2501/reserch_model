"""Entry Quality Model V1 - SHADOW AUDIT tests (spec: Phase-4 forensic audit dashboard).

Covers the safety/correctness properties the dashboard promises: shadow and actual metrics never
mix, filters apply consistently, insufficient samples never render a misleading number, OOS
metrics use only genuinely-unseen rows, nothing here ever writes to the database, and the export
carries the documented audit fields.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.analytics.entry_quality_audit import MIN_SAMPLE, build_audit, export_rows, load_rows
from app.analytics.entry_quality_model import (
    FEATURE_COLUMNS, MODEL_VERSION, TRAINING_WINDOW_END_MS, predict_proba,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.main import create_app
from app.models.analytics import TradeAnalytics
from app.models.enums import Side
from app.models.market import MarketCandle
from app.models.trading import Trade
from tests.helpers_agents import closed_position, make_agents, make_dna

N_CANDLES = 400          # enough past the ~200-bar feature warm-up window
CANDLE_START_MS = 1_700_000_000_000
INTERVAL_MS = 60_000


async def _seed_candles(db, n: int = N_CANDLES) -> list[int]:
    """A smooth, mildly noisy walk - real enough that rolling stats aren't degenerate (constant
    price would make bb_width/atr collapse to zero and every feature NaN or zero)."""
    price = 100.0
    open_times = []
    for i in range(n):
        price += math.sin(i / 7.0) * 0.05 + (0.01 if i % 3 == 0 else -0.01)
        ot = CANDLE_START_MS + i * INTERVAL_MS
        db.add(MarketCandle(
            symbol="SOL", timeframe="1m", open_time=ot, close_time=ot + INTERVAL_MS - 1,
            open=price, high=price + 0.05, low=price - 0.05, close=price + 0.01, volume=1000.0 + i,
            is_final=True,
        ))
        open_times.append(ot)
    await db.flush()
    return open_times


async def _add_trade(
    db, agent, *, signal_open_time_ms: int, side: Side = Side.LONG, net_pnl: float = 1.0,
    quality_class: str = "TAKE_PROFIT_HIT", family: str = "momentum", regime: str = "TREND_UP",
    closed_at: datetime | None = None, holding_seconds: int = 300,
) -> uuid.UUID:
    pos_id = closed_position(db, agent, side=side)
    closed_at = closed_at or datetime.now(timezone.utc)
    trade = Trade(
        agent_id=agent.id, position_id=pos_id, symbol="SOL", side=side, quantity=1.0,
        entry_price=100.0, exit_price=100.0 + net_pnl, gross_pnl=net_pnl, fees=0.0, net_pnl=net_pnl,
        opened_at=closed_at - timedelta(seconds=holding_seconds), closed_at=closed_at,
        holding_seconds=holding_seconds, exit_reason="take_profit" if net_pnl > 0 else "stop_loss",
    )
    db.add(trade)
    await db.flush()
    db.add(TradeAnalytics(
        trade_id=trade.id, agent_id=agent.id, family=family, regime=regime, side=side.value,
        signal_bar_open_time_ms=signal_open_time_ms, leverage=1.0, position_notional=100.0,
        mfe_price=101.0, mae_price=99.0, mfe_time_ms=signal_open_time_ms, mae_time_ms=signal_open_time_ms,
        time_to_mfe_seconds=60, time_to_mae_seconds=30, mfe_bps=100.0, mae_bps=-50.0,
        max_unrealized_profit=1.0, max_unrealized_loss=-0.5, mfe_r=1.0, mae_r=-0.5,
        trade_quality_class=quality_class, computation_version="test-v1",
        computed_at=datetime.now(timezone.utc),
    ))
    await db.flush()
    return trade.id


@pytest_asyncio.fixture
async def api(db_session, monkeypatch):
    """Authenticated as a VIEWER exactly like tests/test_api_endpoints.py: every /api route requires auth by default
    (fail-closed), so an unauthenticated client gets 401 - the endpoints under test are viewer-level."""
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.core.security import hash_api_key

    viewer_key = "eq-viewer-key-1234"
    s = get_settings()
    monkeypatch.setattr(s, "api_auth_required", True)
    monkeypatch.setattr(s, "api_keys", SecretStr(f"eqv:viewer:{hash_api_key(viewer_key)}"))

    async def _db():
        yield db_session
    app = create_app()
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.headers.update({"X-API-Key": viewer_key})
        yield c


async def test_entry_quality_api_rejects_unauthenticated_requests(api):
    r = await api.get("/api/entry-quality/export.csv", headers={"X-API-Key": ""})
    assert r.status_code == 401


async def test_build_audit_runs_end_to_end_with_no_trades(db_session):
    """Empty database: never 500s, never fabricates a number - matches the rest of the
    dashboard's insufficient_data convention."""
    await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await db_session.commit()
    result = await build_audit(db_session)
    assert result["funnel"]["strategy_signals"] == 0
    assert result["live_vs_shadow"]["actual"]["trades"] == 0
    assert result["oos_card"]["status"] == "INSUFFICIENT_DATA"


async def test_shadow_and_actual_metrics_never_mix(db_session):
    """The funnel's actual_trades count must equal what's really in the trades table regardless
    of the threshold - the shadow model must never be described as having blocked anything real."""
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    for i in range(40):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i],
                         net_pnl=1.0 if i % 2 == 0 else -1.0)
    await db_session.commit()

    real_trade_count = (await db_session.execute(select(Trade))).scalars().all()
    for threshold in (0.1, 0.5, 0.9):
        result = await build_audit(db_session, threshold=threshold)
        assert result["funnel"]["actual_trades"] == len(real_trade_count)
        assert result["live_vs_shadow"]["actual"]["trades"] == len(real_trade_count)
        # shadow_trade + shadow_no_trade + unscorable must reconstruct the total - no double count,
        # no silent drop.
        f = result["funnel"]
        assert f["shadow_trade"] + f["shadow_no_trade"] + f["unscorable"] == f["strategy_signals"]


async def test_build_audit_never_writes_to_the_database(db_session):
    """Purely a read/aggregation service - Trade.net_pnl and count must be bit-for-bit identical
    before and after, at every threshold, confirming a shadow audit request can never touch a
    real trade's P&L."""
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    for i in range(20):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i], net_pnl=float(i) - 10)
    await db_session.commit()

    before = {t.id: t.net_pnl for t in (await db_session.execute(select(Trade))).scalars().all()}
    await build_audit(db_session, threshold=0.3)
    await build_audit(db_session, threshold=0.7)
    after = {t.id: t.net_pnl for t in (await db_session.execute(select(Trade))).scalars().all()}
    assert before == after


async def test_insufficient_sample_never_renders_a_misleading_number(db_session):
    """Fewer than MIN_SAMPLE trades in a family/regime cell must report None / a sufficiency
    flag, never a numeric win rate or expectancy a viewer could mistake for something reliable."""
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    assert MIN_SAMPLE > 5, "test assumes a handful of trades is below the real threshold"
    for i in range(5):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i],
                         family="scalping", regime="RANGE")
    await db_session.commit()

    result = await build_audit(db_session, family="scalping", regime="RANGE")
    breakdown = next(r for r in result["strategy_breakdown"] if r["family"] == "scalping")
    assert breakdown["sufficient_sample"] is False
    assert breakdown["shadow_win_rate"] is None
    assert breakdown["shadow_expectancy"] is None
    cell = next(c for c in result["strategy_regime_matrix"]["cells"] if c["family"] == "scalping")
    assert cell["sufficient_sample"] is False and cell["value"] is None and cell["label"] == "INSUFFICIENT_DATA"


async def test_oos_card_only_counts_rows_after_the_frozen_training_window(db_session):
    """A trade whose signal fired inside the model's own train+val window must never be counted
    as OOS - that would let the model grade its own training data as if it were unseen."""
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    in_training_ms = 1_000_000_000  # far before TRAINING_WINDOW_END_MS
    assert in_training_ms < TRAINING_WINDOW_END_MS
    for i in range(10):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i])
    await db_session.commit()

    result = await build_audit(db_session)
    # every seeded trade's signal time is near CANDLE_START_MS (2023-era unix ms), which predates
    # TRAINING_WINDOW_END_MS (2026) - none of them should count as OOS.
    assert result["oos_card"]["oos_trades"] == 0


async def test_threshold_analysis_never_mutates_settings(db_session):
    """Running the exploratory threshold grid must never write back a "chosen" threshold to
    application settings - it is audit-only, never an auto-promotion mechanism."""
    settings_before = get_settings().model_dump() if hasattr(get_settings(), "model_dump") else vars(get_settings())
    await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await db_session.commit()
    await build_audit(db_session, threshold=0.9)
    settings_after = get_settings().model_dump() if hasattr(get_settings(), "model_dump") else vars(get_settings())
    assert settings_before == settings_after


async def test_model_version_matches_the_frozen_artifact(db_session):
    await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await db_session.commit()
    result = await build_audit(db_session)
    assert result["model_status"]["model_version"] == MODEL_VERSION
    assert result["model_version_info"]["model_version"] == MODEL_VERSION
    assert result["model_status"]["affects_live_trading"] is False


async def test_unscorable_signal_does_not_crash_and_is_reported(db_session):
    """A signal timestamp with no matching candle (feature coverage gap) must be counted, not
    silently dropped and not a crash - the dashboard's whole point is to surface this."""
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await _add_trade(db_session, agent, signal_open_time_ms=open_times[250])  # scorable
    await _add_trade(db_session, agent, signal_open_time_ms=1)  # long before any candle exists
    await db_session.commit()

    result = await build_audit(db_session)
    assert result["funnel"]["strategy_signals"] == 2
    assert result["funnel"]["unscorable"] >= 1
    assert result["model_health"]["shadow_predictions"] == result["funnel"]["scored"]


async def test_predict_proba_never_raises_on_missing_features():
    assert predict_proba({}, side="LONG") is None
    partial = {c: 0.0 for c in FEATURE_COLUMNS[:-1]}
    assert predict_proba(partial, side="SHORT") is None
    complete = {c: 0.01 for c in FEATURE_COLUMNS}
    pred = predict_proba(complete, side="LONG")
    assert pred is not None and 0.0 <= pred.probability <= 1.0


async def test_export_contains_the_documented_audit_fields(db_session):
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await _add_trade(db_session, agent, signal_open_time_ms=open_times[250], net_pnl=2.0)
    await db_session.commit()

    rows = await load_rows(db_session)
    records = export_rows(rows, threshold=0.6)
    assert len(records) == 1
    expected_fields = {
        "timestamp", "agent_id", "generation_id", "strategy", "regime", "direction",
        "model_version", "predicted_probability", "shadow_threshold", "shadow_decision",
        "actual_trade", "actual_outcome", "actual_pnl", "mfe_r", "mae_r", "hold_seconds",
        "exit_reason",
    }
    assert expected_fields.issubset(records[0].keys())
    assert records[0]["actual_trade"] is True
    assert records[0]["model_version"] == MODEL_VERSION
    assert records[0]["shadow_decision"] in ("shadow_trade", "shadow_no_trade", "unscorable")


async def test_api_audit_endpoint_returns_strict_json(api, db_session):
    """A profit_factor of Infinity (all-winning bucket) must never leak into the HTTP response -
    Infinity is not valid JSON and would break every real browser's response.json()."""
    import json
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    for i in range(35):  # all winners, no losers -> profit_factor would divide by zero
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i], net_pnl=1.0)
    await db_session.commit()

    r = await api.get("/api/entry-quality/audit")
    assert r.status_code == 200
    json.loads(r.text)  # strict parse - raises on a bare Infinity/NaN token


async def test_api_export_csv_endpoint(api, db_session):
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    await _add_trade(db_session, agent, signal_open_time_ms=open_times[250])
    await db_session.commit()

    r = await api.get("/api/entry-quality/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "timestamp" in r.text.splitlines()[0]


async def test_filters_narrow_the_dataset_consistently(db_session):
    open_times = await _seed_candles(db_session)
    (agent,) = await make_agents(db_session, [make_dna()])
    for i in range(10):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[250 + i], side=Side.LONG, family="vwap")
    for i in range(10):
        await _add_trade(db_session, agent, signal_open_time_ms=open_times[270 + i], side=Side.SHORT, family="momentum")
    await db_session.commit()

    unfiltered = await build_audit(db_session)
    assert unfiltered["funnel"]["strategy_signals"] == 20

    long_only = await build_audit(db_session, side="LONG")
    assert long_only["funnel"]["strategy_signals"] == 10
    assert all(r["side"] == "LONG" for r in long_only["long_short"] if r["signals"] > 0)

    vwap_only = await build_audit(db_session, family="vwap")
    assert vwap_only["funnel"]["strategy_signals"] == 10
