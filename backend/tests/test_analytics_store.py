"""Analytics-store tests: idempotent refresh, NO raw-table mutation, module
isolation (no production trading-engine imports), SQLite end-to-end."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

import app.analytics.analytics_store as store
from app.models.agent import Agent
from app.models.analytics import FitnessForwardPerformance, StrategyRegimeMatrix, TradeAnalytics
from app.models.council import CouncilDecision
from app.models.decision import Decision
from app.models.enums import AgentStatus, Bias, RiskDecision, StrategyFamily, StrategyStage
from app.models.market import MarketCandle, MarketRegimeRecord
from app.models.metrics import FitnessScore
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Generation, Strategy, StrategyVersion
from app.models.trading import Order, Position, Trade

MINUTE = 60_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % MINUTE)


# --------------------------------------------------------------------------- #
# fixture data: one agent, one strategy family, 3 trades in 2 regime episodes
# --------------------------------------------------------------------------- #
async def _seed(db):
    now = datetime.now(timezone.utc)
    gen = Generation(number=1, population_target=10, population_created=1, starting_balance=100.0,
                     total_capital_allocated=100.0, triggered_by="test", notes="", created_at=now)
    db.add(gen)
    strategy = Strategy(code="S1", family=StrategyFamily.MOMENTUM, name="S", description="")
    db.add(strategy)
    await db.flush()
    version = StrategyVersion(strategy_id=strategy.id, version=1, generation=1, dna={}, stage=StrategyStage.PAPER,
                              hypothesis="", proposed_by="test")
    db.add(version)
    await db.flush()
    agent = Agent(identifier="A1", generation=1, strategy_version_id=version.id, status=AgentStatus.ACTIVE,
                  starting_balance=100.0, balance=100.0, equity=100.0, peak_equity=100.0,
                  day_start_equity=100.0, day_start_date=now.date(), created_at=datetime.fromtimestamp(T0 / 1000, tz=timezone.utc))
    db.add(agent)
    await db.flush()

    candles = []
    for i in range(30):
        px = 100.0 + (1.0 if i % 2 else -1.0)
        candles.append(MarketCandle(
            symbol="SOL", timeframe="1m", open_time=T0 + i * MINUTE, close_time=T0 + (i + 1) * MINUTE - 1,
            open=px, high=px + 2.0, low=px - 2.0, close=px, volume=100, is_final=True, source="test",
        ))
    db.add_all(candles)
    # two regime episodes: RANGE (bars 0-9), TREND_UP (bars 10-29)
    db.add_all([
        MarketRegimeRecord(symbol="SOL", timeframe="1m", candle_open_time=T0 + i * MINUTE,
                           regime=("RANGE" if i < 10 else "TREND_UP"), confidence=0.9, detector_version="t")
        for i in range(30)
    ])

    trades = []
    for k, (open_i, close_i, net) in enumerate([(0, 5, 1.0), (6, 8, -2.0), (12, 20, 0.5)]):
        decision = Decision(
            agent_id=agent.id, strategy_version_id=version.id, market_candle_open_time=T0 + open_i * MINUTE,
            market_timestamp=datetime.fromtimestamp((T0 + open_i * MINUTE) / 1000, tz=timezone.utc),
            agent_signal=Bias.LONG, agent_signal_confidence=0.8, agent_signal_reasoning={"setup_strength": 0.7},
            risk_decision=RiskDecision.APPROVED, risk_reasoning={},
        )
        db.add(decision)
        await db.flush()
        order = Order(
            agent_id=agent.id, decision_id=decision.id, client_order_id=f"c{k}", symbol="SOL", side="LONG",
            quantity=1.0, requested_price=100.0, leverage=1.0, venue="PAPER", status="FILLED",
            submitted_at=datetime.fromtimestamp((T0 + open_i * MINUTE) / 1000, tz=timezone.utc),
            filled_at=datetime.fromtimestamp((T0 + (open_i + 1) * MINUTE) / 1000, tz=timezone.utc),
            raw_venue_response={}, signal_candle_open_time=T0 + open_i * MINUTE, intent={},
            filled_quantity=1.0, filled_price=100.0, fee=0.1, slippage_cost=0.01,
        )
        db.add(order)
        await db.flush()
        position = Position(
            agent_id=agent.id, symbol="SOL", side="LONG", quantity=1.0, entry_price=100.0, leverage=1.0,
            initial_margin=100.0, maintenance_margin=1.0, entry_order_id=order.id, entry_fee=0.1,
            entry_slippage_cost=0.01, entry_candle_open_time=T0 + (open_i + 1) * MINUTE,
            entry_regime=("RANGE" if open_i < 10 else "TREND_UP"), stop_loss_price=95.0,
            take_profit_price=110.0, opened_at=datetime.fromtimestamp((T0 + (open_i + 1) * MINUTE) / 1000, tz=timezone.utc),
            closed_at=datetime.fromtimestamp((T0 + (close_i + 1) * MINUTE - 1) / 1000, tz=timezone.utc),
            is_open=False, venue="PAPER", peak_price=102.0, trough_price=98.0,
        )
        db.add(position)
        await db.flush()
        trade = Trade(
            agent_id=agent.id, position_id=position.id, entry_order_id=order.id, symbol="SOL", side="LONG",
            quantity=1.0, entry_price=100.0, exit_price=101.0, gross_pnl=net, fees=0.1, funding=0.0,
            slippage_cost=0.01, net_pnl=net - 0.11,
            opened_at=position.opened_at, closed_at=position.closed_at,
            holding_seconds=(close_i - open_i) * 60, entry_regime=position.entry_regime,
            exit_regime="RANGE", exit_reason="exit_rules", stage=StrategyStage.PAPER,
        )
        db.add(trade)
        trades.append(trade)
    await db.flush()
    return agent, trades


async def _raw_state(db) -> dict[str, int]:
    tables = ["agents", "strategies", "strategy_versions", "decisions", "orders", "positions", "trades",
              "market_candles", "market_regimes", "generations"]
    out = {}
    for t in tables:
        out[t] = (await db.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar_one()
    return out


async def test_refresh_is_idempotent(db_session):
    _agent, _trades = await _seed(db_session)
    await db_session.commit()

    r1 = await store.refresh_trade_analytics(db_session)
    await db_session.commit()
    r2 = await store.refresh_trade_analytics(db_session)
    await db_session.commit()

    count = (await db_session.execute(select(text("COUNT(*) FROM trade_analytics")))).scalar_one()
    assert count == 3
    assert r1.trades_processed == 3 and r2.trades_updated == 3 and r2.trades_processed == 0

    m1 = await store.refresh_strategy_regime_matrix(db_session)
    await db_session.commit()
    m2 = await store.refresh_strategy_regime_matrix(db_session)
    await db_session.commit()
    assert m1.matrix_cells == m2.matrix_cells
    cells = (await db_session.execute(select(text("COUNT(*) FROM strategy_regime_matrix")))).scalar_one()
    assert cells == m1.matrix_cells          # rebuild: no duplicates

    f1 = await store.refresh_fitness_forward(db_session, grid_minutes=10)
    await db_session.commit()
    f2 = await store.refresh_fitness_forward(db_session, grid_minutes=10)
    await db_session.commit()
    assert f1.ffp_inserted > 0
    assert f2.ffp_inserted == 0 and f2.ffp_existing == f1.ffp_inserted     # write-once: only fills gaps


async def test_refresh_never_mutates_raw_tables(db_session):
    _agent, _trades = await _seed(db_session)
    await db_session.commit()
    before = await _raw_state(db_session)

    await store.refresh_trade_analytics(db_session)
    await store.refresh_strategy_regime_matrix(db_session)
    await store.refresh_fitness_forward(db_session, grid_minutes=10)
    await db_session.commit()

    after = await _raw_state(db_session)
    assert after == before, "analytics refresh must not change any raw table"


async def test_trade_analytics_populated_correctly(db_session):
    agent, trades = await _seed(db_session)
    await db_session.commit()
    await store.refresh_trade_analytics(db_session)
    await db_session.commit()

    rows = (await db_session.execute(select(TradeAnalytics))).scalars().all()
    assert len(rows) == 3
    by_trade = {r.trade_id: r for r in rows}
    for t in trades:
        ta = by_trade[t.id]
        assert ta.family == "momentum"
        assert ta.agent_id == agent.id
        assert ta.side == "LONG"
        assert ta.risk_amount == pytest.approx(5.0)          # 1 * |100-95|
        assert ta.leverage == 1.0
        assert ta.trade_quality_class == "SIGNAL_EXIT_WIN" or ta.trade_quality_class == "SIGNAL_EXIT_LOSS"
        assert ta.mfe_price >= 100.0 and ta.mae_price <= 100.0
        assert ta.signal_confidence == 0.8
        assert ta.setup_strength == 0.7
        assert ta.regime_episode_id is not None


async def test_crosscheck_reports_mismatch_not_silently(db_session):
    _agent, trades = await _seed(db_session)
    # corrupt ONE position's persisted peak (simulating a data-integrity problem)
    pos = (await db_session.execute(select(Position))).scalars().first()
    pos.peak_price = 150.0     # impossible: replayed high is ~102-104
    await db_session.commit()

    r = await store.refresh_trade_analytics(db_session)
    await db_session.commit()
    assert r.crosscheck_failures >= 1
    assert any("peak" in f or "through" in f for f in r.findings)

    row = (await db_session.execute(
        select(TradeAnalytics).join(Trade, Trade.id == TradeAnalytics.trade_id)
        .where(Trade.position_id == pos.id)
    )).scalars().one()
    assert row.peak_crosscheck_ok is False    # recorded, not hidden


async def test_matrix_cells_and_evidence(db_session):
    await _seed(db_session)
    await db_session.commit()
    await store.refresh_trade_analytics(db_session)
    r = await store.refresh_strategy_regime_matrix(db_session)
    await db_session.commit()

    cells = (await db_session.execute(select(StrategyRegimeMatrix))).scalars().all()
    fam_cells = [c for c in cells if c.granularity == "family" and c.window_key == "full"]
    # the traded cells: momentum x RANGE (2 trades, 1 episode) and momentum x TREND_UP (1 trade, 1 episode)
    mr = next(c for c in fam_cells if c.regime == "RANGE")
    mt = next(c for c in fam_cells if c.regime == "TREND_UP")
    assert mr.trade_count == 2 and mt.trade_count == 1
    # both cells have < MIN_EPISODES(3) episodes -> under-sampled, no edge declared
    assert mr.under_sampled is True and mr.gross_edge is False and mr.net_edge is False
    assert mr.evidence_state in ("PROVISIONAL", "UNTESTED")
    # zero-rows exist for every untraded family x regime
    zero = [c for c in fam_cells if c.trade_count == 0]
    assert len(zero) > 0
    assert all(c.evidence_state == "UNTESTED" and c.under_sampled for c in zero)


async def test_ffp_rows_written_and_write_once(db_session):
    await _seed(db_session)
    db_session.add(FitnessScore(
        agent_id=(await db_session.execute(select(Agent))).scalars().first().id,
        as_of=datetime.now(timezone.utc), fitness=0.5, return_score=0.0, risk_score=0.0,
        consistency_score=0.0, robustness_score=0.0, oos_score=0.0, drawdown_penalty=0.0,
        instability_penalty=0.0, weights_used={},
    ))
    await db_session.commit()
    r = await store.refresh_fitness_forward(db_session, grid_minutes=10)
    await db_session.commit()
    rows = (await db_session.execute(select(FitnessForwardPerformance))).scalars().all()
    assert r.ffp_inserted == len(rows) > 0
    assert all(r_.censor_reason in ("none", "data_end", "generation_rollover", "agent_death") for r_ in rows)
    sources = {r_.snapshot_source for r_ in rows}
    assert sources <= {"recorded", "reconstructed"}
    # write-once at the ORM level
    row = rows[0]
    row.future_net_pnl = 999.0
    with pytest.raises(Exception):
        await db_session.flush()


def test_no_production_trading_module_imports():
    """The analytics engines must not import production trading logic (decision
    loop, execution adapters, council service, risk engine, evolution,
    worker): analytics is read-only FORENSICS, so a stray import would be a
    coupling bug even if nothing is called."""
    import ast
    from pathlib import Path

    forbidden = ("app.agents", "app.execution", "app.council", "app.risk", "app.evolution", "app.worker")
    backend = Path(__file__).resolve().parents[1]
    modules = [
        backend / "app" / "analytics" / "trade_quality.py",
        backend / "app" / "analytics" / "strategy_regime.py",
        backend / "app" / "analytics" / "fitness_forward.py",
        backend / "app" / "analytics" / "analytics_store.py",
        backend / "scripts" / "refresh_analytics.py",
        backend / "scripts" / "report_strategy_regime.py",
        backend / "scripts" / "report_trade_quality.py",
        backend / "scripts" / "report_fitness_forward.py",
        backend / "scripts" / "report_agent_evidence.py",
    ]
    for path in modules:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports production module {name!r}"


async def test_trade_analytics_regime_episodes_tracked(db_session):
    await _seed(db_session)
    await db_session.commit()
    await store.refresh_trade_analytics(db_session)
    await db_session.commit()
    rows = (await db_session.execute(select(TradeAnalytics))).scalars().all()
    # RANGE trades share episode 1; the TREND_UP trade is a different episode
    episodes = {r.regime_episode_id for r in rows}
    assert len(episodes) == 2