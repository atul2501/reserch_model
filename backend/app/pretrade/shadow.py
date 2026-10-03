"""PRETRADE_MODE=shadow — the deterministic pre-trade path, run alongside the existing path, recording only.

Safety model (each layer is tested in tests/test_pretrade_shadow.py):
  1. Its own database session/transaction (never the worker's session): no identity-map sharing with the existing
     path, so nothing it loads can leak a stale object into production decisions.
  2. That transaction is READ ONLY at the database level (PostgreSQL `SET TRANSACTION READ ONLY`, SQLite
     `PRAGMA query_only`), is never committed, and is rolled back and closed in `finally`. A pending ORM change is a
     hard error.
  3. It only calls pure functions (feature/strategy evaluation, sizing, risk check, gate) and never an
     ExecutionEngine, so it cannot create orders, positions, fills or balance changes.
  4. Its only side effect is appending JSON lines to `pretrade_shadow_dir`.
  5. The worker runs it inside a try/except with a hard timeout: a shadow failure is logged and skipped, it never
     affects the existing path.

The LLM council is NOT called here. The existing path's own council result is published into a CouncilView after it
completes; this path, running before that council on each bar, reads whatever snapshot is already there (exactly
what a fully-async council would offer) and RECORDS it. It never vetoes, sizes or authorises anything.
"""
from __future__ import annotations

import json
import math
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.position_manager import bar_time
from app.core.config import BACKEND_DIR, Settings
from app.core.logging import get_logger
from app.core.system_flags import trading_halt_reason
from app.execution.margin import margin_state
from app.execution.price_observation import PriceObservation, first_observed_at_or_after
from app.execution.sizing import below_min_order_notional, requested_notional, stop_distance_pct
from app.market.feature_engine import FEATURE_WINDOW
from app.models.agent import Agent
from app.models.enums import AgentStatus, Bias, OrderStatus, RiskDecision, Side
from app.models.strategy import Generation, StrategyVersion
from app.models.trading import Order, Position
from app.pretrade.council_view import CouncilView
from app.pretrade.decision import PreTradeDecision
from app.pretrade.gate import ExecutionGate, GateConfig, MarketSnapshot
from app.risk.risk_engine import RiskCheckInput, check_trade
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import ENGINE_VERSION, build_feature_view, compute_population_features, evaluate_signal

logger = get_logger(__name__)
PRETRADE_VERSION = "pretrade_shadow_v1"
BAR_MS = 60_000


class LookAheadError(RuntimeError):
    """The shadow path was handed data from after the signal bar's information cutoff."""


class ShadowWriteAttempt(RuntimeError):
    """Something tried to stage a database change inside the shadow transaction."""


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def feature_version(context: MarketContext) -> str:
    """Real identifiers of the code that produced the features/signal (no invented model/prompt versions)."""
    return f"features:window{FEATURE_WINDOW}|regime:{context.regime.detector_version}|strategy_engine:{ENGINE_VERSION}"


# --------------------------------------------------------------------------- storage
class ShadowRecorder:
    """Append-only JSON-lines writer: one file per UTC day. The only side effect of shadow mode."""

    def __init__(self, directory: str | Path) -> None:
        p = Path(directory)
        self.directory = p if p.is_absolute() else (BACKEND_DIR / p)

    def write(self, rows: list[dict]) -> Path | None:
        if not rows:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.directory / f"pretrade_shadow_{day}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=_json_default, allow_nan=False) + "\n")
        return path


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def _clean(v):
    """JSON-safe: NaN/inf -> None (never written as invalid JSON)."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


# --------------------------------------------------------------------------- read-only DB access
@asynccontextmanager
async def read_only_session(bind):
    """A fresh session on `bind` whose transaction the DATABASE refuses to write in. Never committed."""
    session = AsyncSession(bind=bind, expire_on_commit=False, autoflush=False)
    dialect = bind.dialect.name
    try:
        if dialect == "postgresql":
            await session.execute(text("SET TRANSACTION READ ONLY"))
        elif dialect == "sqlite":
            await session.execute(text("PRAGMA query_only = ON"))
        yield session
        if session.new or session.dirty or session.deleted:
            raise ShadowWriteAttempt("shadow session has pending ORM changes")
    finally:
        try:
            if dialect == "sqlite":
                await session.execute(text("PRAGMA query_only = OFF"))   # connection goes back to the pool clean
        finally:
            await session.rollback()
            await session.close()


# --------------------------------------------------------------------------- order book (public read endpoint only)
@dataclass(frozen=True)
class BookSnapshot:
    bid: float | None
    ask: float | None
    exchange_time_ms: int | None
    requested_at_ms: int
    received_at_ms: int

    @property
    def mid(self) -> float | None:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else None

    @property
    def spread_bps(self) -> float | None:
        m = self.mid
        return (self.ask - self.bid) / m * 1e4 if m else None

    @property
    def ts_ms(self) -> int:
        """When the price is valid: exchange snapshot time if given, else when we received it."""
        return self.exchange_time_ms or self.received_at_ms


async def fetch_book(provider, coin: str, timeout_s: float) -> BookSnapshot | None:
    """Best bid/ask from the public l2Book read endpoint. None (recorded as 'unavailable') on any failure."""
    import asyncio

    from app.execution.shadow_adapter import parse_book

    if provider is None:
        return None
    t0 = wall_ms()
    try:
        raw = await asyncio.wait_for(provider.get_l2_book(coin), timeout=timeout_s)
        book = parse_book(raw, max_levels=1)
    except Exception as exc:  # noqa: BLE001 - network/timeout/shape: spread is simply unknown
        logger.warning("pretrade_shadow.book_unavailable", error=str(exc)[:200])
        return None
    return BookSnapshot(
        bid=book.bids[0][0] if book.bids else None, ask=book.asks[0][0] if book.asks else None,
        exchange_time_ms=book.time_ms or None, requested_at_ms=t0, received_at_ms=wall_ms(),
    )


# --------------------------------------------------------------------------- the shadow cycle
async def run_shadow_cycle(
    *, bind, context: MarketContext, prev_context: MarketContext | None, candles: pd.DataFrame, generation: int | None,
    settings: Settings, council_view: CouncilView, recorder: ShadowRecorder, book_provider=None,
    features_started_ms: int | None = None, features_completed_ms: int | None = None, clock=wall_ms,
) -> dict:
    """Runs the deterministic pre-trade path for ONE confirmed bar and records what it WOULD do. Returns a summary."""
    K = int(context.candle_open_time)
    cutoff = K + BAR_MS - 1
    market_event_ms = K + BAR_MS
    # ---- information boundary: nothing after bar K may be in the inputs
    if context.is_final is not True:
        raise LookAheadError(f"bar {K} is not confirmed final")
    last = int(candles["open_time"].iloc[-1])
    if last != K or int(candles["open_time"].max()) > K:
        raise LookAheadError(f"candles extend past the signal bar (last {last}, signal {K})")

    async with read_only_session(bind) as s:
        if generation is None:
            generation = (await s.execute(select(Generation.number).order_by(Generation.number.desc()).limit(1))).scalar_one_or_none()
        if generation is None:
            return {"record_type": "bar_summary", "signal_bar_open_time_ms": K, "skipped": "no_generation"}
        agents = (await s.execute(select(Agent).where(Agent.generation == generation, Agent.status == AgentStatus.ACTIVE))).scalars().all()
        versions = (await s.execute(select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents})))).scalars().all() if agents else []
        positions = set((await s.execute(select(Position.agent_id).where(Position.is_open.is_(True)))).scalars().all())
        pending = set((await s.execute(select(Order.agent_id).where(
            Order.status == OrderStatus.PENDING, Order.reduce_only.is_(False)))).scalars().all())
        halt = await trading_halt_reason(s)

        dnas: dict = {}
        for v in versions:
            try:
                dnas[v.id] = StrategyDNA.model_validate(v.dna)
            except ValidationError:
                continue
        cur, prv = compute_population_features(candles, dnas.values())
        view = build_feature_view(context, prev_context, cur, prv)
        signal_created_ms = clock()

        market_ts = bar_time(K)
        candidates = []
        for a in agents:
            dna = dnas.get(a.strategy_version_id)
            if dna is None:
                continue
            sig = evaluate_signal(dna, view)                       # entry evaluation, as if flat
            if not sig.matched_entry:
                continue
            side = Side.LONG if sig.bias == Bias.LONG else Side.SHORT
            same_day = a.day_start_date == market_ts.date()
            day_start_equity = a.day_start_equity if same_day else a.equity
            daily_count = a.daily_trade_count if same_day else 0
            reasons: list[str] = []
            if a.cooldown_until is not None and market_ts < a.cooldown_until:
                reasons.append("cooldown_active")
            if daily_count >= dna.max_trades_per_day:
                reasons.append("max_trades_per_day_reached")
            atr = context.volatility.atr_14
            stop = stop_distance_pct(dna, context.close_price, atr, context.structure.swing_low,
                                     context.structure.swing_high, side == Side.LONG)
            req = requested_notional(dna, equity=a.equity, price=context.close_price, atr=atr, stop_dist_pct=stop)
            margin = margin_state(balance=a.balance, maintenance_margin_rate=settings.maintenance_margin_rate)
            rr = check_trade(RiskCheckInput(
                agent=a, dna=dna, side=side, proposed_notional=req, proposed_leverage=dna.leverage_limit,
                current_price=context.close_price, atr=atr, equity=a.equity, daily_pnl=a.equity - day_start_equity,
                has_open_position=a.id in positions, market_data_age_seconds=None,
                council_trade_allowed=True,                        # the LLM is never an input to this path
                trading_halt_reason=halt, available_margin=margin.available_margin,
                stop_distance_pct=stop if dna.stop_loss.enabled else None,
            ), global_max_leverage=settings.max_leverage, global_max_position_size=settings.max_position_size,
                global_max_drawdown=settings.max_drawdown, global_max_daily_loss=settings.max_daily_loss)
            if rr.decision == RiskDecision.REJECTED:
                reasons += [f"risk:{r}" for r in rr.reasons] or ["risk:rejected"]
            elif below_min_order_notional(rr.approved_notional, context.close_price):
                reasons.append("risk:below_min_order_notional")
            # plain values only: no ORM object may leave the read-only session
            candidates.append((a.id, a.strategy_version_id, dna.strategy_family.value, sig, side, reasons, rr.approved_notional))

        n_agents = len(agents)
        if s.new or s.dirty or s.deleted:
            raise ShadowWriteAttempt("shadow path staged a database change")

    decision_ms = clock()
    decisions = [
        (PreTradeDecision(
            decision_id=f"{aid}:{K}", agent_id=str(aid), symbol=context.symbol, direction=side.value,
            signal_bar_open_time_ms=K, information_cutoff_ms=cutoff, features_as_of_ms=cutoff,
            signal_timestamp_ms=signal_created_ms, decision_timestamp_ms=decision_ms,
            reference_price=context.close_price, strategy=family,
            strategy_version_id=str(svid), regime=context.regime.regime.value,
            confidence=sig.confidence, feature_version=feature_version(context),
        ), aid, sig, reasons, approved) for aid, svid, family, sig, side, reasons, approved in candidates
    ]

    book = await fetch_book(book_provider, context.symbol, settings.pretrade_shadow_book_timeout_seconds) if decisions else None
    gate = ExecutionGate(GateConfig(
        max_decision_age_ms=int(settings.pretrade_max_decision_age_seconds * 1000),
        max_entry_drift_bps=settings.pretrade_max_entry_drift_bps,
        max_spread_bps=None, require_spread=False, require_expected_move=False,
    ))
    validation_ms = clock()
    snap = council_view.latest_any()
    exec_price = book.mid if book and book.mid else None
    fill_obs = first_observed_at_or_after(decision_ms, [PriceObservation(book.ts_ms, exec_price, "l2_mid")]) if exec_price else None
    rows = []
    for d, aid, sig, reasons, approved in decisions:
        m = MarketSnapshot(
            now_ms=validation_ms, current_signal_bar_ms=K,
            current_price=exec_price if exec_price else d.reference_price,
            spread_bps=book.spread_bps if book else None,
            position_open=aid in positions, pending_order=aid in pending,
            risk_ok=not reasons, risk_reasons=tuple(reasons), conflicting_signal=False,
        )
        g = gate.validate(d, m)
        council_age = (validation_ms - snap.information_cutoff_ms) if snap else None
        council_dir = snap.bias if snap else None
        opposed = council_dir in ("LONG", "SHORT") and council_dir != d.direction
        rows.append({k: _clean(v) for k, v in {
            "record_type": "candidate", "pretrade_version": PRETRADE_VERSION, "pretrade_mode": "shadow",
            "signal_bar_open_time_ms": K, "information_cutoff_ms": cutoff, "market_event_ms": market_event_ms,
            "features_started_ms": features_started_ms, "features_completed_ms": features_completed_ms,
            "signal_created_ms": signal_created_ms, "decision_ms": decision_ms, "validation_ms": validation_ms,
            "decision_id": d.decision_id, "agent_id": d.agent_id, "generation": generation, "strategy": d.strategy,
            "strategy_version_id": d.strategy_version_id, "regime": d.regime, "direction": d.direction,
            "strategy_confidence": d.confidence, "setup_strength": sig.reasoning.get("setup_strength"),
            "feature_version": d.feature_version, "prompt_version": None, "model_version": None,
            "expected_move_bps": None, "horizon_seconds": None,
            "reference_price": d.reference_price, "price_at_signal": context.close_price, "price_at_signal_ts_ms": cutoff,
            "price_at_decision": None,  # not separately observed: the one book read happens right after the decision
            "price_at_shadow_execution_point": exec_price,
            "price_at_shadow_execution_point_ts_ms": book.ts_ms if book else None,
            "price_source": "l2_mid" if exec_price else "unavailable",
            "bid": book.bid if book else None, "ask": book.ask if book else None,
            "spread_bps": book.spread_bps if book else None,
            "book_requested_ms": book.requested_at_ms if book else None, "book_received_ms": book.received_at_ms if book else None,
            "decision_age_ms": g.decision_age_ms,
            "signed_drift_bps": g.price_drift_bps if exec_price else None,
            "absolute_drift_bps": abs(g.price_drift_bps) if exec_price else None,
            "gate_allowed": g.allowed, "gate_rejection_reasons": list(g.reasons), "gate_flags": list(g.flags),
            "gate_validation_us": g.validation_us,
            "risk_allowed": not reasons, "risk_reasons": reasons, "approved_notional": approved,
            "position_state": "OPEN" if aid in positions else "FLAT",
            "pending_order_state": "PENDING" if aid in pending else "NONE",
            "cost_check_result": "unavailable_no_expected_move_model",
            "council_available": snap is not None, "council_status": snap.status if snap else None,
            "council_age_ms": council_age, "council_direction": council_dir,
            "council_confidence": snap.confidence if snap else None,
            "council_cutoff_ms": snap.information_cutoff_ms if snap else None,
            "council_model_configured": snap.model_version if snap else None,
            "llm_agrees": (council_dir == d.direction) if council_dir in ("LONG", "SHORT") else None,
            "llm_would_veto": bool(snap and snap.status == "COMPLETE" and opposed
                                   and snap.confidence >= settings.council_veto_confidence),
            "would_trade": g.allowed, "would_reject": not g.allowed,
            "shadow_fill_price": fill_obs.price if fill_obs else None,
            "shadow_fill_ts_ms": fill_obs.ts_ms if fill_obs else None,
            "shadow_fill_source": fill_obs.source if fill_obs else "no_observed_price_after_decision",
            "orders_created": 0,
        }.items()})
    recorder.write(rows)
    summary = {
        "record_type": "bar_summary", "pretrade_version": PRETRADE_VERSION, "signal_bar_open_time_ms": K,
        "market_event_ms": market_event_ms, "features_started_ms": features_started_ms,
        "features_completed_ms": features_completed_ms, "signal_created_ms": signal_created_ms,
        "decision_ms": decision_ms, "validation_ms": validation_ms, "agents": n_agents, "candidates": len(rows),
        "would_trade": sum(r["would_trade"] for r in rows), "book_available": book is not None,
        "council_snapshot_age_ms": (validation_ms - snap.information_cutoff_ms) if snap else None,
    }
    recorder.write([summary])
    return summary


async def record_old_path_point(*, open_time_ms: int, recorder: ShadowRecorder, book_provider, settings: Settings,
                                old_path_completed_ms: int, old_path_agents_processed: int) -> None:
    """After the EXISTING path finished bar K: the price at that moment, for decision-time vs old-path comparison."""
    book = await fetch_book(book_provider, settings.market_symbol, settings.pretrade_shadow_book_timeout_seconds)
    recorder.write([{k: _clean(v) for k, v in {
        "record_type": "old_path_point", "pretrade_version": PRETRADE_VERSION, "signal_bar_open_time_ms": open_time_ms,
        "old_path_completed_ms": old_path_completed_ms, "old_path_agents_processed": old_path_agents_processed,
        "price": book.mid if book else None, "price_ts_ms": book.ts_ms if book else None,
        "bid": book.bid if book else None, "ask": book.ask if book else None,
        "spread_bps": book.spread_bps if book else None,
    }.items()}])
