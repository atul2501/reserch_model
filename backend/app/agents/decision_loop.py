"""Per-candle agent evaluation loop (spec sections 3/4/12/32; phases 3-12, 39).

For ONE shared MarketContext (a CONFIRMED candle), evaluates every ACTIVE agent deterministically:

    execute what the previous bar's close decided (next-open engines)
    -> manage open position (funding -> protective exit / liquidation -> MTM)
    -> DNA strategy signal (dynamic indicators) -> council context -> risk
    engine -> sizing/margin -> order -> position/PnL

and writes a Decision audit row for everything that happened. It never calls Ollama (the council already ran
upstream, once, for this candle).

Execution timing (`engine.fill_timing`):
  * next_open (PAPER, the research default): a signal on the CLOSE of bar N becomes a persisted PENDING order (entry)
    or a pending exit on the position, and fills at the OPEN of bar N+1 - exactly the backtest's model, so paper
    results carry no signal-bar look-ahead. A pending order that was not filled on bar N+1 is CANCELLED, never
    filled late.
  * immediate (SHADOW): the order is filled when submitted, against the live book - that is what shadow measures.

Protection invariant: an open position ALWAYS gets protective processing (funding, stop, take-profit, trailing,
liquidation) on every confirmed bar, whatever happened to its agent: `protect_open_positions` sweeps every position
not yet managed on this bar (failed agent savepoint, invalid DNA, DEAD/orphan owner, other generation), and the
worker calls it for bars it could not decide on (failed attempts, poison candles, skipped catch-up bars).
Management is idempotent per bar (`Position.last_processed_open_time`).

Performance (500 agents): agents, prior decisions, strategy versions, open positions, pending orders and funding
settlements are each loaded with ONE query for the whole population; population-wide indicators are computed once;
per-agent work is isolated in a SAVEPOINT so one agent's failure can never abort the cycle.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lifecycle import mark_dead, update_equity
from app.agents.position_manager import (
    Bar,
    PositionLevels,
    advance_extremes,
    bar_time,
    evaluate_bar,
)
from app.analytics.pnl_engine import compute_liquidation_price, compute_trade_pnl
from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.system_flags import trading_halt_reason as _load_trading_halt_reason
from app.council.context import COMPLETE, INCOMPLETE, NOT_RUN, CouncilContext, combine
from app.execution import accounting
from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.execution.fillmodel import fee_rate_for, slipped_price, slippage_bps
from app.execution.margin import margin_state
from app.execution.paper_adapter import new_client_order_id
from app.execution.sizing import (
    approve_against_margin,
    build_sizing_result,
    requested_notional,
    stop_distance_pct,
)
from app.market.hyperliquid_client import HyperliquidClient
from app.market.market_data_service import CandleNotFinalError
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import AgentStatus, Bias, ExecutionVenue, OrderStatus, RiskDecision, Side, StrategyStage
from app.models.market import FundingRate
from app.models.strategy import StrategyVersion
from app.models.trading import FundingPayment, Order, Position, Trade
from app.risk.risk_engine import RiskCheckInput, check_trade
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import (
    FeatureView,
    build_feature_view,
    compute_population_features,
    evaluate_signal,
)
from app.worker.lease import LeaseLost

logger = get_logger(__name__)


@dataclass
class CycleContext:
    """Everything that is constant across the agents of one candle."""

    db: AsyncSession
    engine: ExecutionEngine
    context: MarketContext
    dna_by_version: dict[uuid.UUID, StrategyDNA]
    stage_by_version: dict[uuid.UUID, StrategyStage]
    positions: dict[uuid.UUID, Position]
    funding_rates: list[FundingRate]
    interval_ms: int
    halt_reason: str | None = None
    fee_rate: float = 0.0
    # --- entry-path only (unused by the protective sweep) ---
    dyn_current: dict = field(default_factory=dict)
    dyn_previous: dict = field(default_factory=dict)
    prev_context: MarketContext | None = None
    council: CouncilContext = field(default_factory=CouncilContext)
    council_decision_id: uuid.UUID | None = None
    global_max_leverage: float = 5.0
    global_max_position_size: float = 0.5
    global_max_drawdown: float = 0.3
    global_max_daily_loss: float = 0.1
    market_data_age_seconds: float | None = None
    pending: dict[uuid.UUID, Order] = field(default_factory=dict)   # PENDING entry orders, by agent

    @property
    def next_open(self) -> bool:
        return self.engine.fill_timing == "next_open"

    @property
    def bar(self) -> Bar:
        c = self.context
        close = c.close_price
        return Bar(
            open=c.candle_open if c.candle_open is not None else close,
            high=c.candle_high if c.candle_high is not None else close,
            low=c.candle_low if c.candle_low is not None else close,
            close=close,
        )

    @property
    def open_dt(self) -> datetime:
        return bar_time(self.context.candle_open_time)

    @property
    def close_ms(self) -> int:
        return self.context.candle_close_time or (self.context.candle_open_time + self.interval_ms - 1)

    @property
    def close_dt(self) -> datetime:
        return datetime.fromtimestamp(self.close_ms / 1000, tz=timezone.utc)


_DECISION_NAMESPACE = uuid.UUID("6f0c7a58-3f0e-5b53-9a4e-2f7d5b1c9e11")


def decision_id_for(agent_id, candle_open_time: int) -> uuid.UUID:
    """Deterministic decision id: one per (agent, candle). Combined with the unique constraint it makes a retried
    or competing cycle collide instead of double-deciding, and it makes every derived order id stable."""
    return uuid.uuid5(_DECISION_NAMESPACE, f"{agent_id}:{candle_open_time}")


def _council_context(
    context: MarketContext, council_decision_id, council_trade_allowed: bool, council_bias, council_confidence,
    council_status: str | None, council_required: bool = False,
) -> CouncilContext:
    if council_decision_id is None and council_bias is None:
        status = INCOMPLETE if not council_trade_allowed else NOT_RUN
    else:
        status = council_status or (COMPLETE if council_trade_allowed else INCOMPLETE)
    if council_required and status == NOT_RUN:
        # A required council that produced nothing is a failed council, never an approval.
        status, council_trade_allowed = INCOMPLETE, False
    return CouncilContext(
        status=status, bias=council_bias, confidence=council_confidence, trade_allowed=council_trade_allowed,
        candle_open_time=context.candle_open_time, decision_id=council_decision_id, required=council_required,
    ).for_candle(context.candle_open_time)


async def _load_funding(db: AsyncSession, positions, context: MarketContext, close_ms: int) -> list[FundingRate]:
    positions = list(positions)
    if not positions:
        return []
    earliest = min(int(p.last_funding_time.timestamp() * 1000) if p.last_funding_time else close_ms for p in positions)
    return list((await db.execute(
        select(FundingRate)
        .where(FundingRate.symbol == context.symbol, FundingRate.time_ms > earliest, FundingRate.time_ms <= close_ms)
        .order_by(FundingRate.time_ms)
    )).scalars().all())


def _valid_dnas(versions) -> tuple[dict, dict, set]:
    dna_by_version: dict[uuid.UUID, StrategyDNA] = {}
    stage_by_version: dict[uuid.UUID, StrategyStage] = {}
    invalid: set[uuid.UUID] = set()
    for v in versions:
        stage_by_version[v.id] = v.stage
        try:
            dna_by_version[v.id] = StrategyDNA.model_validate(v.dna)
        except ValidationError as exc:
            invalid.add(v.id)
            logger.error("decision_loop.strategy_dna_invalid", strategy_version_id=str(v.id), error=str(exc))
    return dna_by_version, stage_by_version, invalid


async def run_decision_cycle(
    db: AsyncSession,
    execution_engine: ExecutionEngine,
    context: MarketContext,
    prev_context: MarketContext | None,
    *,
    generation: int,
    council_decision_id: uuid.UUID | None,
    global_max_leverage: float,
    global_max_position_size: float,
    global_max_drawdown: float,
    global_max_daily_loss: float,
    market_data_age_seconds: float | None,
    fee_rate: float | None = None,
    council_trade_allowed: bool = True,
    council_bias: Bias | None = None,
    council_confidence: float | None = None,
    council_status: str | None = None,
    council_required: bool = False,
    trading_halt_override: str | None = None,
    candles: pd.DataFrame | None = None,
    fence=None,
) -> int:
    """Evaluates every ACTIVE agent in `generation` against `context` (a confirmed candle) and then guarantees
    protective processing of every OTHER open position. Returns the number of agents processed.

    `council_trade_allowed=False` (INCOMPLETE council) still runs every agent so exits/audit Decisions keep
    happening, but blocks every NEW entry through the Risk Engine - fail closed, never skip the risk check."""
    settings = get_settings()
    if context.is_final is not True:
        # Hard invariant: only a CONFIRMED candle may reach council -> strategy -> risk -> execution.
        metrics.inc("non_final_candle_rejected")
        raise CandleNotFinalError(f"refusing to decide on candle {context.candle_open_time}: context.is_final is not True")
    fee_rate = fee_rate if fee_rate is not None else settings.paper_fee_rate
    halt_reason = trading_halt_override or await _load_trading_halt_reason(db)
    # Switching TRADING_MODE with positions still open on ANOTHER venue would mix paper and shadow books: those positions
    # keep being protected/closed, but no NEW entry is opened until they are gone.
    foreign = set((await db.execute(
        select(Position.venue).where(Position.is_open.is_(True), Position.venue != execution_engine.venue).distinct()
    )).scalars().all())
    if foreign:
        halt_reason = ",".join(filter(None, [halt_reason, "venue_mismatch:" + "+".join(sorted(v.value for v in foreign))]))
        metrics.inc("venue_mismatch_halts")
    interval_ms = HyperliquidClient.timeframe_to_ms(context.timeframe)
    close_ms = context.candle_close_time or (context.candle_open_time + interval_ms - 1)

    agents = (await db.execute(
        select(Agent).where(Agent.generation == generation, Agent.status == AgentStatus.ACTIVE)
    )).scalars().all()
    processed = 0
    failed_agent_ids: set[uuid.UUID] = set()

    if agents:
        # The unique constraint is the final protection; excluding an already-audited candle avoids needless work.
        decided_ids = set((await db.execute(
            select(Decision.agent_id).where(Decision.market_candle_open_time == context.candle_open_time)
        )).scalars().all())
        agents = [a for a in agents if a.id not in decided_ids]

    if agents:
        versions = (await db.execute(
            select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents}))
        )).scalars().all()
        dna_by_version, stage_by_version, invalid_versions = _valid_dnas(versions)
        positions = {
            p.agent_id: p for p in (await db.execute(
                select(Position).where(Position.agent_id.in_([a.id for a in agents]), Position.is_open.is_(True))
            )).scalars().all()
        }
        # An agent whose DNA is invalid can never trade: park it (its open position, if any, is handled by the
        # protective sweep below) instead of leaving a zombie ACTIVE agent.
        for a in agents:
            if a.strategy_version_id in invalid_versions and a.id not in positions:
                a.status = AgentStatus.PAUSED
                metrics.inc("agents_paused_invalid_dna")
                logger.error("agent.paused_invalid_dna", identifier=a.identifier)
        agents = [a for a in agents if a.strategy_version_id in dna_by_version and a.status == AgentStatus.ACTIVE]

    if agents:
        pending = {
            o.agent_id: o for o in (await db.execute(
                select(Order).where(
                    Order.agent_id.in_([a.id for a in agents]), Order.status == OrderStatus.PENDING,
                    Order.reduce_only.is_(False), Order.signal_candle_open_time.is_not(None),
                )
            )).scalars().all()
        }
        funding_rates = await _load_funding(db, positions.values(), context, close_ms)
        dyn_current: dict = {}
        dyn_previous: dict = {}
        if candles is not None and len(candles):
            dyn_current, dyn_previous = compute_population_features(candles, dna_by_version.values())
        cc = CycleContext(
            db=db, engine=execution_engine, context=context, dna_by_version=dna_by_version,
            stage_by_version=stage_by_version, positions=positions, funding_rates=funding_rates,
            interval_ms=interval_ms, halt_reason=halt_reason, fee_rate=fee_rate,
            dyn_current=dyn_current, dyn_previous=dyn_previous, prev_context=prev_context,
            council=_council_context(context, council_decision_id, council_trade_allowed, council_bias,
                                     council_confidence, council_status, council_required),
            council_decision_id=council_decision_id,
            global_max_leverage=global_max_leverage, global_max_position_size=global_max_position_size,
            global_max_drawdown=global_max_drawdown, global_max_daily_loss=global_max_daily_loss,
            market_data_age_seconds=market_data_age_seconds, pending=pending,
        )
        for agent in agents:
            if fence is not None:
                fence.check_local()   # a worker that lost its lease (or cannot renew it) stops IMMEDIATELY, mid-cycle
            identifier = agent.identifier  # captured: attributes expire if the savepoint rolls back
            agent_id = agent.id
            try:
                async with db.begin_nested():
                    await _process_agent(cc, agent)
                processed += 1
            except Exception:
                execution_engine.discard_uncommitted(str(agent_id))   # its savepoint rolled back: release the order ids
                failed_agent_ids.add(agent_id)
                metrics.inc("agent_cycle_errors")
                logger.exception("decision_loop.agent_failed_isolated", identifier=identifier,
                                 candle_open_time=context.candle_open_time)

    # PROTECTION SWEEP: every open position not yet managed on this bar (failed agent, invalid DNA, DEAD/orphan
    # owner, other generation) still gets funding/stop/take-profit/trailing/liquidation processing.
    try:
        await protect_open_positions(db, execution_engine, context, fence=fence, halt_reason=halt_reason)
    except LeaseLost:
        execution_engine.discard_uncommitted()
        raise
    await _cancel_stale_pending(db, context, interval_ms)

    try:
        if fence is not None:
            # Fenced commit: epoch/owner/expiry is verified INSIDE the transaction, right before it commits,
            # so a superseded worker can never persist decisions, orders, positions or balances.
            await fence.check_db(db, lock=True)
        await db.commit()
    except Exception:
        execution_engine.discard_uncommitted()
        raise
    execution_engine.commit_cycle()
    metrics.inc("agents_processed", processed)
    metrics.inc("agent_decisions", processed)
    return processed


async def protect_open_positions(
    db: AsyncSession, execution_engine: ExecutionEngine, context: MarketContext, *, fence=None,
    halt_reason: str | None = None,
) -> int:
    """Protective-only pass for `context`'s bar: funding, stop, take-profit, trailing, liquidation, and the
    deterministic resolution of positions owned by DEAD/invalid agents. Never opens anything. Idempotent per bar.
    Does not commit (the caller owns the transaction)."""
    if context.is_final is not True:
        raise CandleNotFinalError(f"refusing protective pass on non-final candle {context.candle_open_time}")
    K = context.candle_open_time
    positions = (await db.execute(
        select(Position).where(
            Position.is_open.is_(True),
            (Position.last_processed_open_time.is_(None)) | (Position.last_processed_open_time < K),
        )
    )).scalars().all()
    if not positions:
        return 0
    interval_ms = HyperliquidClient.timeframe_to_ms(context.timeframe)
    close_ms = context.candle_close_time or (K + interval_ms - 1)
    agents = {a.id: a for a in (await db.execute(
        select(Agent).where(Agent.id.in_({p.agent_id for p in positions}))
    )).scalars().all()}
    versions = (await db.execute(
        select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents.values()}))
    )).scalars().all()
    dna_by_version, stage_by_version, _ = _valid_dnas(versions)
    cc = CycleContext(
        db=db, engine=execution_engine, context=context, dna_by_version=dna_by_version,
        stage_by_version=stage_by_version, positions={p.agent_id: p for p in positions},
        funding_rates=await _load_funding(db, positions, context, close_ms), interval_ms=interval_ms,
        halt_reason=halt_reason,
    )
    done = 0
    for position in positions:
        if fence is not None:
            fence.check_local()
        agent = agents[position.agent_id]
        agent_id = agent.id
        identifier = agent.identifier
        try:
            async with db.begin_nested():
                dna = dna_by_version.get(agent.strategy_version_id)
                stage = stage_by_version.get(agent.strategy_version_id) or StrategyStage.PAPER
                if cc.engine.venue == ExecutionVenue.SHADOW:
                    stage = StrategyStage.SHADOW
                await _protect_one(cc, agent, dna, stage, position)
            done += 1
            metrics.inc("positions_protected")
        except LeaseLost:
            raise
        except Exception:
            execution_engine.discard_uncommitted(str(agent_id))
            metrics.inc("protection_failures")
            logger.critical("decision_loop.protection_failed", identifier=identifier, candle_open_time=K)
    return done


async def _protect_one(cc: CycleContext, agent: Agent, dna: StrategyDNA | None, stage, position: Position) -> None:
    context = cc.context
    decision = Decision(
        id=decision_id_for(agent.id, context.candle_open_time),
        agent_id=agent.id, strategy_version_id=agent.strategy_version_id, council_decision_id=None,
        market_candle_open_time=context.candle_open_time, market_timestamp=cc.open_dt, market_context=None,
        agent_signal=Bias.NEUTRAL, agent_signal_confidence=0.0, agent_signal_reasoning={"protective_only": True},
        council_bias=None, council_confidence=None, final_signal=Bias.NEUTRAL,
        risk_decision=RiskDecision.REJECTED, risk_reasoning={},
    )
    existing = (await cc.db.execute(
        select(Decision.id).where(Decision.agent_id == agent.id, Decision.market_candle_open_time == context.candle_open_time)
    )).first()
    if existing is not None:
        decision = None  # already audited this bar (a protective retry after an earlier partial run)
    closed = await _manage_open_position(cc, agent, dna, stage, position, decision, cc.bar)
    if not closed and agent.status != AgentStatus.ACTIVE and position.is_open:
        # Owner is DEAD/PAUSED: an orphan must be resolved deterministically, never left open forever.
        await _close_position(cc, agent, dna, stage, position, decision, reference_price=cc.bar.close,
                              order_kind="liquidation" if agent.status == AgentStatus.DEAD else "market",
                              exit_reason="agent_death" if agent.status == AgentStatus.DEAD else "orphan_resolution")


async def _cancel_stale_pending(db: AsyncSession, context: MarketContext, interval_ms: int) -> None:
    """A pending entry that was not filled on the bar after its signal is CANCELLED - never filled late."""
    cutoff = context.candle_open_time - interval_ms
    await db.execute(
        update(Order).where(
            Order.status == OrderStatus.PENDING, Order.reduce_only.is_(False),
            Order.signal_candle_open_time.is_not(None), Order.signal_candle_open_time < cutoff,
        ).values(status=OrderStatus.CANCELLED, rejection_reason="expired_unfilled")
        .execution_options(synchronize_session=False)
    )


# --------------------------------------------------------------------------- #
# Per-agent processing
# --------------------------------------------------------------------------- #
def _set_equity(agent: Agent, equity: float, *, death_reason: str = "equity_depleted") -> None:
    """update_equity that is a no-op on an already-dead agent (a dead agent's account is frozen)."""
    if agent.status != AgentStatus.DEAD:
        update_equity(agent, equity, death_reason=death_reason)


async def _process_agent(cc: CycleContext, agent: Agent) -> None:
    await _process_agent_inner(cc, agent)
    # An agent that is flat, has nothing pending and can no longer afford a minimum order is untradeable.
    settings = get_settings()
    if (
        agent.status == AgentStatus.ACTIVE and agent.id not in cc.positions
        and agent.equity < settings.agent_min_viable_equity
        and not (agent.id in cc.pending and cc.pending[agent.id].status == OrderStatus.PENDING)
    ):
        mark_dead(agent, reason="untradeable_equity")
        metrics.inc("agents_died", reason="untradeable_equity")


async def _process_agent_inner(cc: CycleContext, agent: Agent) -> None:
    db, context, bar = cc.db, cc.context, cc.bar
    settings = get_settings()
    dna = cc.dna_by_version[agent.strategy_version_id]
    # In shadow mode every hypothetical trade belongs to the SHADOW stage so its
    # metrics can be compared with PAPER/BACKTEST by the reality-gap engine.
    stage = StrategyStage.SHADOW if cc.engine.venue == ExecutionVenue.SHADOW else cc.stage_by_version[agent.strategy_version_id]
    position = cc.positions.get(agent.id)
    market_ts = cc.open_dt

    # Daily-loss circuit breaker anchored to the CANDLE clock (replay-safe).
    if agent.day_start_date != market_ts.date():
        agent.day_start_equity = agent.equity
        agent.day_start_date = market_ts.date()
        agent.daily_trade_count = 0

    # A Decision row is an AUDIT record of something that happened; the ~99% of agent-candles where nothing
    # happened write NO row.
    decision = Decision(
        id=decision_id_for(agent.id, context.candle_open_time),
        agent_id=agent.id, strategy_version_id=agent.strategy_version_id, council_decision_id=cc.council_decision_id,
        market_candle_open_time=context.candle_open_time, market_timestamp=market_ts,
        market_context=None,
        agent_signal=Bias.NEUTRAL, agent_signal_confidence=0.0, agent_signal_reasoning={},
        council_bias=cc.council.bias, council_confidence=cc.council.confidence, final_signal=Bias.NEUTRAL,
        risk_decision=RiskDecision.REJECTED, risk_reasoning={},
    )

    # ---- 0. execute what the PREVIOUS bar's close decided (next-open engines) ------------------- #
    pending_entry = cc.pending.get(agent.id)
    if position is not None and position.pending_exit_signal_time is not None:
        position = await _execute_pending_exit(cc, agent, dna, stage, position, decision)
    elif position is None and pending_entry is not None:
        position = await _execute_pending_entry(cc, agent, dna, stage, pending_entry, decision)

    # ---- 1. manage the open position ------------------------------------- #
    if position is not None:
        if await _manage_open_position(cc, agent, dna, stage, position, decision, bar):
            return
        if agent.status == AgentStatus.DEAD:  # died on mark-to-market: force-close, never orphan a position
            await _close_position(cc, agent, dna, stage, position, decision, reference_price=bar.close,
                                  order_kind="liquidation", exit_reason="agent_death")
            return

    # ---- 2. strategy signal ---------------------------------------------- #
    view: FeatureView = build_feature_view(context, cc.prev_context, cc.dyn_current, cc.dyn_previous)
    signal = evaluate_signal(dna, view, position_side=position.side if position is not None else None)
    decision.agent_signal = signal.bias
    decision.agent_signal_confidence = signal.confidence
    decision.agent_signal_reasoning = signal.reasoning
    decision.final_signal = signal.bias

    if position is not None:
        if signal.matched_exit:
            reason = signal.reasoning.get("exit_reason") or "signal"
            if cc.next_open:
                position.pending_exit_reason = reason
                position.pending_exit_signal_time = context.candle_open_time
                decision.risk_decision = RiskDecision.APPROVED
                decision.risk_reasoning = {"action": "exit_signal_pending_next_open", "exit_reason": reason}
                await _keep(db, decision)
            else:
                await _close_position(cc, agent, dna, stage, position, decision, reference_price=bar.close,
                                      order_kind="market", exit_reason=reason)
        return  # holding: nothing happened -> no audit row

    if not signal.matched_entry:
        return  # no signal: nothing happened -> no audit row

    # DNA trade-frequency controls are hard runtime gates, not metadata.
    if agent.cooldown_until is not None and market_ts < agent.cooldown_until:
        decision.risk_reasoning = {"skipped": "cooldown_active", "cooldown_until": agent.cooldown_until.isoformat()}
        await _keep(db, decision)
        return
    if agent.daily_trade_count >= dna.max_trades_per_day:
        decision.risk_reasoning = {"skipped": "max_trades_per_day_reached"}
        await _keep(db, decision)
        return

    # ---- 3. council as shared context (never an oracle) ------------------- #
    combined = combine(signal.bias, cc.council)
    decision.final_signal = combined.final_signal
    council_audit = combined.audit()
    if combined.reason == "council_directional_conflict_veto":
        decision.risk_reasoning = {"skipped": "council_directional_conflict", "council": council_audit}
        await _keep(db, decision)
        return

    # ---- 4. sizing + risk (priced at the signal bar's CLOSE: the only price known now) ---------- #
    side = Side.LONG if signal.bias == Bias.LONG else Side.SHORT
    atr = context.volatility.atr_14
    swing_low, swing_high = context.structure.swing_low, context.structure.swing_high
    stop_dist = stop_distance_pct(dna, context.close_price, atr, swing_low, swing_high, side == Side.LONG)
    requested = requested_notional(dna, equity=agent.equity, price=context.close_price, atr=atr, stop_dist_pct=stop_dist)
    if combined.reason != "council_incomplete_no_new_trades":
        requested *= combined.size_modifier

    margin = margin_state(balance=agent.balance, maintenance_margin_rate=settings.maintenance_margin_rate)
    risk_result = check_trade(
        RiskCheckInput(
            agent=agent, dna=dna, side=side, proposed_notional=requested, proposed_leverage=dna.leverage_limit,
            current_price=context.close_price, atr=atr, equity=agent.equity,
            daily_pnl=agent.equity - agent.day_start_equity, has_open_position=False,
            market_data_age_seconds=cc.market_data_age_seconds,
            # The Risk Engine - not this loop - is the single enforcement point for an INCOMPLETE council.
            council_trade_allowed=cc.council.trade_allowed and cc.council.status != INCOMPLETE,
            trading_halt_reason=cc.halt_reason, available_margin=margin.available_margin,
            stop_distance_pct=stop_dist if dna.stop_loss.enabled else None,
        ),
        global_max_leverage=cc.global_max_leverage, global_max_position_size=cc.global_max_position_size,
        global_max_drawdown=cc.global_max_drawdown, global_max_daily_loss=cc.global_max_daily_loss,
    )
    decision.risk_decision = risk_result.decision
    rejected = risk_result.decision == RiskDecision.REJECTED
    approved = 0.0 if rejected else approve_against_margin(
        risk_result.approved_notional, leverage=risk_result.approved_leverage or 1.0,
        available_margin=margin.available_margin,
    )
    reasons = list(risk_result.reasons)
    if not rejected and approved < risk_result.approved_notional:
        reasons.append("notional_reduced_to_available_margin")
    if not rejected and approved <= 0:
        rejected = True
        decision.risk_decision = RiskDecision.REJECTED
        reasons.append("zero_notional_after_margin_cap")
    sizing = build_sizing_result(
        method=dna.position_sizing.method, requested=requested, approved=approved,
        leverage=risk_result.approved_leverage or 0.0, price=context.close_price, stop_dist_pct=stop_dist,
    )
    decision.risk_reasoning = {
        "reasons": reasons, "approved_notional": approved, "requested_notional": requested,
        "margin": sizing.margin, "leverage": sizing.leverage, "risk_amount": sizing.risk_amount,
        "sizing_method": sizing.method, "council": council_audit,
    }
    if rejected:
        metrics.inc("risk_vetoes", reason=str(reasons[0]).split(":")[0] if reasons else "unknown")
        await _keep(db, decision)
        return

    await _keep(db, decision)  # the Order FK needs the Decision row in place

    # ---- 5. order -------------------------------------------------------- #
    order = Order(
        agent_id=agent.id, decision_id=decision.id,
        client_order_id=new_client_order_id(str(agent.id), str(decision.id)),
        symbol=context.symbol, side=side, quantity=sizing.quantity,
        requested_notional=requested, approved_notional=approved, initial_margin=sizing.margin,
        risk_amount=sizing.risk_amount, requested_price=context.close_price, leverage=sizing.leverage,
        venue=cc.engine.venue, status=OrderStatus.PENDING, reduce_only=False, order_kind="market",
        submitted_at=cc.close_dt, signal_candle_open_time=context.candle_open_time,
        intent={"atr": atr, "swing_low": swing_low, "swing_high": swing_high, "stop_dist_pct": stop_dist,
                "entry_regime": context.regime.regime.value, "sizing_method": sizing.method},
    )
    db.add(order)
    await db.flush()
    decision.order_id = order.id

    if cc.next_open:
        # Decided on the CLOSE of this bar; fills at the OPEN of the next one (see _execute_pending_entry).
        metrics.inc("orders", kind="entry", status="PENDING")
        return

    position = await _fill_entry(cc, agent, dna, order, decision, reference_price=context.close_price,
                                 fill_bar_open_ms=context.candle_open_time, immediate=True)


async def _keep(db: AsyncSession, decision: Decision | None) -> None:
    """Persist an actionable decision (idempotent). Flushed immediately so its id
    can back the deterministic order idempotency key and the Order foreign key."""
    if decision is not None and decision not in db:
        db.add(decision)
        await db.flush()


def _apply_fill_to_order(order: Order, fill: ExecutionResult, filled_at: datetime) -> None:
    order.status = fill.status
    order.rejection_reason = fill.rejection_reason
    order.filled_at = filled_at if fill.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) else None
    order.raw_venue_response = fill.raw_response
    order.latency_ms = fill.latency_ms
    order.filled_quantity = fill.filled_quantity
    order.filled_price = fill.filled_price
    order.fee = fill.fee
    order.slippage_cost = fill.slippage_cost


def _cancel_order(order: Order, reason: str) -> None:
    order.status = OrderStatus.CANCELLED
    order.rejection_reason = reason[:250]
    metrics.inc("orders", kind="entry", status="CANCELLED")


# --------------------------------------------------------------------------- #
# Next-open execution of what the previous bar's close decided
# --------------------------------------------------------------------------- #
async def _execute_pending_entry(
    cc: CycleContext, agent: Agent, dna: StrategyDNA, stage, order: Order, decision: Decision
) -> Position | None:
    K = cc.context.candle_open_time
    cc.pending.pop(agent.id, None)
    if order.signal_candle_open_time != K - cc.interval_ms:
        _cancel_order(order, "expired_unfilled")
        return None
    if cc.halt_reason or agent.status != AgentStatus.ACTIVE:
        # Kill switch / data gap / catch-up replay: a NEW entry is never opened, and a stale one is dropped.
        _cancel_order(order, f"entries_halted:{cc.halt_reason or agent.status.value}")
        return None
    return await _fill_entry(cc, agent, dna, order, decision, reference_price=cc.bar.open,
                             fill_bar_open_ms=K, immediate=False)


async def _fill_entry(
    cc: CycleContext, agent: Agent, dna: StrategyDNA, order: Order, decision: Decision, *,
    reference_price: float, fill_bar_open_ms: int, immediate: bool,
) -> Position | None:
    """Submits a PENDING entry order and opens the position from the fill. `immediate` = filled on the signal
    bar's close (shadow); otherwise at the next bar's open (paper) and managed on that same bar."""
    settings = get_settings()
    db, context = cc.db, cc.context
    intent = order.intent or {}
    margin = margin_state(balance=agent.balance, maintenance_margin_rate=settings.maintenance_margin_rate)
    notional = approve_against_margin(order.approved_notional or 0.0, leverage=order.leverage or 1.0,
                                      available_margin=margin.available_margin)
    quantity = notional / reference_price if reference_price > 0 else 0.0
    fill = await cc.engine.submit_order(
        ExecutionRequest(
            client_order_id=order.client_order_id, agent_id=str(agent.id), symbol=order.symbol, side=order.side,
            quantity=quantity, leverage=order.leverage, reference_price=reference_price,
        )
    )
    filled_at = cc.close_dt if immediate else cc.open_dt
    order.quantity = quantity
    _apply_fill_to_order(order, fill, filled_at)
    metrics.inc("orders", kind="entry", status=fill.status.value)
    if fill.filled_price is not None and fill.filled_quantity > 0:
        metrics.observe("fill_slippage_cost", fill.slippage_cost or 0.0, kind="entry")
        metrics.observe("fill_latency_ms", fill.latency_ms or 0, kind="entry")

    if fill.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) or fill.filled_price is None or fill.filled_quantity <= 0:
        decision.risk_reasoning = {**(decision.risk_reasoning or {}), "order_rejection": fill.rejection_reason}
        metrics.inc("order_rejections", reason=fill.rejection_reason or "unknown")
        if not immediate:
            await _keep(db, decision)
        return None

    side = order.side
    entry = fill.filled_price
    fnotional = entry * fill.filled_quantity
    liq_price = compute_liquidation_price(
        side=side, entry_price=entry, quantity=fill.filled_quantity, balance=agent.balance - fill.fee,
        maintenance_margin_rate=settings.maintenance_margin_rate,
    )
    lv = accounting.entry_levels(dna, side, entry, atr=intent.get("atr", context.volatility.atr_14),
                                 swing_low=intent.get("swing_low"), swing_high=intent.get("swing_high"))
    opened_at = cc.close_dt if immediate else cc.open_dt
    last_funding = cc.close_dt if immediate else cc.open_dt - timedelta(milliseconds=1)   # signal bar's close
    position = Position(
        agent_id=agent.id, symbol=order.symbol, side=side, quantity=fill.filled_quantity, entry_price=entry,
        leverage=order.leverage, initial_margin=fnotional / (order.leverage or 1.0),
        maintenance_margin=fnotional * settings.maintenance_margin_rate,
        peak_price=entry, trough_price=entry, last_funding_time=last_funding,
        entry_order_id=order.id, entry_fee=fill.fee, entry_slippage_cost=fill.slippage_cost,
        liquidation_price=liq_price, entry_candle_open_time=fill_bar_open_ms,
        entry_regime=intent.get("entry_regime") or context.regime.regime.value,
        venue=cc.engine.venue, trailing_active=lv.trailing_active,
        stop_loss_price=lv.stop_loss, take_profit_price=lv.take_profit, trailing_stop_distance=lv.trailing_distance,
        opened_at=opened_at,
        # immediate fills happen AFTER this bar's management step: management starts on the next bar.
        last_processed_open_time=context.candle_open_time if immediate else None,
    )
    db.add(position)
    cc.positions[agent.id] = position

    agent.balance -= fill.fee
    agent.fees_paid += fill.fee
    agent.trade_count += 1
    agent.daily_trade_count += 1
    agent.last_trade_time = opened_at
    _set_equity(agent, agent.balance)
    return position


async def _execute_pending_exit(
    cc: CycleContext, agent: Agent, dna: StrategyDNA | None, stage, position: Position, decision: Decision
) -> Position | None:
    """A signal exit decided on the previous bar's close executes at this bar's OPEN (before any intrabar level)."""
    K = cc.context.candle_open_time
    reason, signal_time = position.pending_exit_reason or "signal", position.pending_exit_signal_time
    position.pending_exit_reason = None
    position.pending_exit_signal_time = None
    if signal_time != K - cc.interval_ms:
        return position  # stale: the next signal evaluation re-derives it if it still holds
    closed = await _close_position(cc, agent, dna, stage, position, decision, reference_price=cc.bar.open,
                                   order_kind="market", exit_reason=reason)
    return None if closed else position


# --------------------------------------------------------------------------- #
# Open-position management
# --------------------------------------------------------------------------- #
async def _accrue_funding(cc: CycleContext, agent: Agent, position: Position) -> None:
    """Applies every exchange-published funding settlement in (last processed settlement, this bar's close].
    Idempotent through the (position, settlement time) unique constraint."""
    last_ms = int(position.last_funding_time.timestamp() * 1000) if position.last_funding_time else 0
    due = [r for r in cc.funding_rates if last_ms < r.time_ms <= cc.close_ms]
    if not due:
        return
    for r in due:
        notional = position.quantity * cc.context.close_price
        payment = accounting.funding_payment(position.side, position.quantity, cc.context.close_price, r.rate)
        cc.db.add(FundingPayment(
            agent_id=agent.id, position_id=position.id, symbol=position.symbol, funding_time_ms=r.time_ms,
            funding_rate=r.rate, position_notional=notional, payment=payment,
        ))
        agent.balance -= payment
        agent.funding_paid += payment
        position.funding_accrued += payment
        position.last_funding_time = datetime.fromtimestamp(r.time_ms / 1000, tz=timezone.utc)
    await cc.db.flush()


async def _manage_open_position(
    cc: CycleContext, agent: Agent, dna: StrategyDNA | None, stage: StrategyStage, position: Position,
    decision: Decision | None, bar: Bar,
) -> bool:
    """Returns True if the position was closed this bar. Idempotent per bar."""
    settings = get_settings()
    K = cc.context.candle_open_time
    if position.last_processed_open_time is not None and position.last_processed_open_time >= K:
        return False  # this bar was already evaluated (retry / protective replay): never evaluate a bar twice
    await _accrue_funding(cc, agent, position)

    # Liquidation price depends on the CURRENT balance (funding/fees applied).
    liq_price = compute_liquidation_price(
        side=position.side, entry_price=position.entry_price, quantity=position.quantity, balance=agent.balance,
        maintenance_margin_rate=settings.maintenance_margin_rate,
    )
    position.liquidation_price = liq_price
    activation = dna.trailing_stop.activation_pct if dna is not None and dna.trailing_stop.enabled else 0.0
    levels = PositionLevels(
        side=position.side, entry_price=position.entry_price, stop_loss_price=position.stop_loss_price,
        take_profit_price=position.take_profit_price, trailing_distance=position.trailing_stop_distance,
        trailing_activation_pct=activation,
        trailing_active=position.trailing_active, peak_price=position.peak_price, trough_price=position.trough_price,
        liquidation_price=liq_price,
    )
    position.last_processed_open_time = K
    trigger = evaluate_bar(levels, bar, same_bar_extreme=settings.trailing_stop_uses_same_bar_extreme)
    if trigger is not None:
        return await _close_position(
            cc, agent, dna, stage, position, decision, reference_price=trigger.reference_price,
            order_kind=trigger.order_kind, exit_reason=trigger.exit_reason,
        )

    # Survived the bar: advance extremes (AFTER the exit check) and arm trailing.
    peak, trough, active = advance_extremes(levels, bar)
    position.peak_price, position.trough_price, position.trailing_active = peak, trough, active

    state = margin_state(
        balance=agent.balance, maintenance_margin_rate=settings.maintenance_margin_rate, side=position.side,
        quantity=position.quantity, entry_price=position.entry_price, mark_price=bar.close,
        initial_margin=position.initial_margin,
    )
    position.unrealized_pnl = state.unrealized_pnl
    position.maintenance_margin = state.maintenance_margin
    if state.liquidatable:  # account breached maintenance margin at the close
        return await _close_position(cc, agent, dna, stage, position, decision, reference_price=bar.close,
                                     order_kind="liquidation", exit_reason="liquidation")
    _set_equity(agent, state.equity)
    return False


def _synthetic_exit_fill(cc: CycleContext, position: Position, order: Order, reference_price: float, order_kind: str) -> ExecutionResult:
    """Deterministic settlement at the modelled price when the engine keeps failing to fill an exit."""
    s = get_settings()
    notional = reference_price * position.quantity
    bps = slippage_bps(order_kind, notional, base_bps=s.paper_slippage_bps,
                       impact_bps_per_10k=s.paper_slippage_impact_bps_per_10k, stop_multiplier=s.paper_stop_slippage_multiplier)
    px = slipped_price(reference_price, position.side, reduce_only=True, bps=bps)
    fee = px * position.quantity * fee_rate_for(order_kind, taker=s.paper_fee_rate, maker=s.paper_maker_fee_rate)
    return ExecutionResult(
        client_order_id=order.client_order_id, status=OrderStatus.FILLED, filled_price=px,
        filled_quantity=position.quantity, fee=fee, slippage_cost=abs(px - reference_price) * position.quantity,
        latency_ms=0, raw_response={"synthetic": "force_settle", "reference_price": reference_price},
    )


async def _close_position(
    cc: CycleContext, agent: Agent, dna: StrategyDNA | None, stage: StrategyStage, position: Position,
    decision: Decision | None, *, reference_price: float, order_kind: str, exit_reason: str,
) -> bool:
    """Closes through the ExecutionEngine (a real reduce-only order, real fees and slippage) and books the Trade.
    Returns False if the exit did not fill (the position stays open; after N failures it is settled at the
    modelled price so an agent can never be stuck)."""
    settings = get_settings()
    db, context = cc.db, cc.context
    await _keep(db, decision)
    anchor = decision.id if decision is not None else decision_id_for(agent.id, context.candle_open_time)
    order = Order(
        agent_id=agent.id, decision_id=decision.id if decision is not None else None,
        client_order_id=new_client_order_id(str(agent.id), str(anchor), f"exit{position.exit_attempts}"),
        symbol=position.symbol, side=position.side, quantity=position.quantity,
        requested_price=reference_price, leverage=position.leverage, venue=cc.engine.venue,
        status=OrderStatus.PENDING, reduce_only=True, order_kind=order_kind, submitted_at=cc.close_dt,
    )
    db.add(order)
    await db.flush()
    fill = await cc.engine.submit_order(
        ExecutionRequest(
            client_order_id=order.client_order_id, agent_id=str(agent.id), symbol=position.symbol, side=position.side,
            quantity=position.quantity, leverage=position.leverage, reference_price=reference_price,
            reduce_only=True, order_kind=order_kind,
        )
    )
    _apply_fill_to_order(order, fill, cc.close_dt)
    metrics.inc("orders", kind="exit", status=fill.status.value)
    if fill.filled_price is not None:
        metrics.observe("fill_slippage_cost", fill.slippage_cost or 0.0, kind="exit")
        metrics.observe("fill_latency_ms", fill.latency_ms or 0, kind="exit")
    if fill.status != OrderStatus.FILLED or fill.filled_price is None:
        position.exit_attempts += 1
        if decision is not None:
            decision.risk_reasoning = {**(decision.risk_reasoning or {}), "exit_failed": fill.rejection_reason, "intended_exit": exit_reason}
        logger.error("decision_loop.exit_not_filled", identifier=agent.identifier, reason=fill.rejection_reason,
                     attempts=position.exit_attempts)
        if cc.engine.venue == ExecutionVenue.LIVE or position.exit_attempts < settings.exit_force_settle_after_attempts:
            return False
        metrics.inc("exit_force_settled")
        fill = _synthetic_exit_fill(cc, position, order, reference_price, order_kind)
        _apply_fill_to_order(order, fill, cc.close_dt)
        exit_reason = f"{exit_reason}|force_settled"

    exit_fee = fill.fee
    if order_kind == "liquidation":  # exchange liquidation penalty on the closed notional
        exit_fee += accounting.liquidation_penalty(fill.filled_price, position.quantity, settings.liquidation_fee_rate)

    pnl = compute_trade_pnl(
        side=position.side, quantity=position.quantity, entry_price=position.entry_price, exit_price=fill.filled_price,
        entry_fee=position.entry_fee, exit_fee=exit_fee, funding_paid=position.funding_accrued,
        slippage_cost=position.entry_slippage_cost + fill.slippage_cost,
    )
    position.is_open = False
    position.closed_at = cc.close_dt
    position.unrealized_pnl = 0.0
    position.pending_exit_reason = None
    position.pending_exit_signal_time = None
    cc.positions.pop(agent.id, None)

    # Entry fee and funding were already deducted from balance when incurred; only the price PnL and the exit
    # fee remain to settle. A shortfall is RECORDED as bad debt, never silently clamped away.
    settlement = accounting.settle_close(agent.balance, pnl.gross_pnl, exit_fee)
    trade = Trade(
        agent_id=agent.id, position_id=position.id, entry_order_id=position.entry_order_id, exit_order_id=order.id,
        symbol=position.symbol, side=position.side, quantity=position.quantity, entry_price=position.entry_price,
        exit_price=fill.filled_price, gross_pnl=pnl.gross_pnl, fees=pnl.fees, funding=pnl.funding,
        slippage_cost=pnl.slippage_cost, net_pnl=pnl.net_pnl, bad_debt=settlement.bad_debt,
        opened_at=position.opened_at, closed_at=position.closed_at,
        holding_seconds=max(0, int((position.closed_at - position.opened_at).total_seconds())),
        entry_regime=position.entry_regime, exit_regime=context.regime.regime.value, exit_reason=exit_reason, stage=stage,
    )
    db.add(trade)
    await db.flush()

    if decision is not None:
        decision.risk_decision = RiskDecision.APPROVED
        decision.risk_reasoning = {**(decision.risk_reasoning or {}), "action": "close_position", "exit_reason": exit_reason}
        decision.order_id = order.id
        decision.trade_id = trade.id

    agent.balance = settlement.new_balance
    agent.bad_debt += settlement.bad_debt
    agent.realized_pnl += pnl.net_pnl
    agent.fees_paid += exit_fee
    if settlement.bad_debt > 0:
        metrics.inc("bad_debt_events")
        logger.error("agent.bad_debt", identifier=agent.identifier, bad_debt=settlement.bad_debt, exit_reason=exit_reason)
    _set_equity(agent, agent.balance, death_reason="liquidated" if order_kind == "liquidation" else "equity_depleted")
    if exit_reason.startswith("liquidation") and settings.liquidation_is_fatal and agent.status != AgentStatus.DEAD:
        mark_dead(agent, reason="liquidated")
    if agent.status == AgentStatus.DEAD:
        # The account is frozen AFTER the forced exit's fees, slippage and liquidation penalty were booked.
        agent.equity = agent.balance
        agent.final_equity = agent.balance
        agent.final_pnl = agent.balance - agent.starting_balance
        logger.warning("agent.died_on_trade_close", identifier=agent.identifier, net_pnl=pnl.net_pnl, exit_reason=exit_reason)
        metrics.inc("agents_died", reason=agent.death_reason or "unknown")

    bars = accounting.cooldown_bars_after(dna, pnl.net_pnl)
    expiry = accounting.cooldown_expiry_ms(context.candle_open_time, bars, cc.interval_ms)
    if expiry is not None:
        # Cooldown is counted in BARS of the configured timeframe on the candle clock: an exit in bar X blocks
        # entry signals for bars X .. X+bars-1 (identical in paper, shadow and backtest).
        agent.cooldown_until = bar_time(expiry)
    return True
