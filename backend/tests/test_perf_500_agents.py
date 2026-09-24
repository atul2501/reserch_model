"""500 agents x 1 confirmed candle (spec phases 39, 45): constant read
queries, shared indicator computation, no Ollama per agent, bounded time."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import event, func, select

from app.agents.lifecycle import create_generation
from app.core.config import get_settings
from app.core.database import engine as app_engine
from app.execution.paper_adapter import PaperExecutionAdapter
from app.market.feature_engine import compute_features
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import AgentStatus
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Position
from app.strategies import indicators as ind
from app.strategies.factory import generate_population_dna
from tests.helpers_agents import cycle


def _frame(n=300, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.01, 0.4, n))
    return pd.DataFrame({
        "open_time": np.arange(n) * 60_000 + 1_700_000_040_000, "open": close - rng.normal(0, .1, n),
        "high": close + rng.uniform(0.05, 0.9, n), "low": close - rng.uniform(0.05, 0.9, n), "close": close,
        "volume": rng.uniform(200, 3000, n),
    })


async def _population(db, n=500):
    ids = []
    for dna in generate_population_dna(n, seed=21):
        strat = Strategy(code=f"S-{len(ids):05d}", family=dna.strategy_family, name="p")
        db.add(strat)
        await db.flush()
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=1, dna=dna.model_dump(mode="json"))
        db.add(v)
        await db.flush()
        ids.append(v.id)
    await create_generation(db, generation_number=100, strategy_version_ids=ids, starting_balance=100.0)


async def test_500_agents_one_cycle_is_fast_query_bounded_and_ollama_free(db_session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "paper_latency_ms", 0)
    monkeypatch.setattr(s, "paper_latency_jitter_ms", 0)
    await _population(db_session)
    assert (await db_session.execute(select(func.count()).select_from(Agent))).scalar_one() == 500

    df = _frame()
    from app.execution import paper_adapter
    paper_adapter._SEEN_ORDER_IDS.clear()

    computed = []
    real = ind.compute_indicator
    monkeypatch.setattr(ind, "compute_indicator", lambda d, spec: (computed.append(spec), real(d, spec))[1])
    # Ollama must never be touched by the decision loop.
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no per-agent LLM calls")))

    selects: list[str] = []

    def _count(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    sync_engine = db_session.get_bind()
    event.listen(sync_engine, "before_cursor_execute", _count)
    per_cycle_selects, elapsed_each = [], []
    engine_ = PaperExecutionAdapter()
    try:
        n = len(df)
        prev = None
        for i in range(n - 12, n):                   # 12 consecutive confirmed candles
            frame = df.iloc[: i + 1]
            ctx = compute_features(frame, "SOL", "1m").model_copy(update={"is_final": True})  # a confirmed bar
            before, t0 = len(selects), time.monotonic()
            processed = await cycle(db_session, engine_, ctx, prev, candles=frame)
            elapsed_each.append(time.monotonic() - t0)
            per_cycle_selects.append(len(selects) - before)
            prev = ctx
            assert processed <= 500
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert max(elapsed_each) < 20, f"500-agent cycle took {max(elapsed_each):.1f}s"
    # Reads are population-level, not per-agent: agents, decided ids, versions, positions, funding, flags(+small constant).
    assert max(per_cycle_selects) <= 25, f"{max(per_cycle_selects)} SELECTs for 500 agents"
    # Every distinct indicator computed once per candle (never once per agent).
    per_candle_specs = len(computed) / 12
    assert 0 < per_candle_specs < 200
    decisions = (await db_session.execute(select(func.count()).select_from(Decision))).scalar_one()
    # Only actionable agent-candles are audited (entries, exits, vetoes) - NOT 500 x 12 no-op rows.
    assert decisions < 500 * 12 * 0.5
    opened_ever = (await db_session.execute(select(func.count()).select_from(Position))).scalar_one()
    from app.models.enums import OrderStatus
    orders = (await db_session.execute(select(func.count()).select_from(Order).where(
        Order.reduce_only.is_(False), Order.status.in_([OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED])))).scalar_one()
    exits = (await db_session.execute(select(func.count()).select_from(Order).where(Order.reduce_only.is_(True)))).scalar_one()
    assert opened_ever > 0 and opened_ever == orders                      # entries happened; exactly one position per FILLED entry (dust/rejected entries open none)
    print(f"PERF max_cycle={max(elapsed_each):.2f}s selects/cycle={max(per_cycle_selects)} positions={opened_ever} exits={exits} indicators/candle={per_candle_specs:.0f}")
