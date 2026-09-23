"""Per-candle agent evaluation loop (spec sections 3/4/12/32; phases 3-12, 39).

For ONE shared MarketContext (a confirmed candle), evaluates every ACTIVE
agent deterministically:

    manage open position (funding -> protective exit / liquidation -> MTM)
    -> DNA strategy signal (dynamic indicators) -> council context -> risk
    engine -> sizing/margin -> execution engine -> position/PnL

and writes a full Decision audit row regardless of outcome. It never calls
Ollama (the council already ran upstream, once, for this candle).

Performance (500 agents): agents, prior decisions, strategy versions, open
positions and funding settlements are each loaded with ONE query for the whole
population; population-wide indicators are computed once; per-agent work is
isolated in a SAVEPOINT so one agent's failure can never abort the cycle.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lifecycle import mark_dead, update_equity
from app.agents.position_manager import (
    Bar,
    PositionLevels,
    advance_extremes,
    bar_time,
    evaluate_bar,
    stop_price,
    take_profit_price,
)
from app.analytics.pnl_engine import compute_liquidation_price, compute_trade_pnl
from app.core import metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.system_flags import trading_halt_reason as _load_trading_halt_reason
from app.council.context import COMPLETE, INCOMPLETE, NOT_RUN, CouncilContext, combine
from app.execution.base import ExecutionEngine, ExecutionRequest
from app.execution.margin import margin_state
from app.execution.paper_adapter import new_client_order_id
from app.execution.sizing import (
    approve_against_margin,
    build_sizing_result,
    requested_notional,
    stop_distance_pct,
)
from app.market.hyperliquid_client import HyperliquidClient
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

logger = get_logger(__name__)


@dataclass
class CycleContext:
    """Everything that is constant across the agents of one candle."""

    db: AsyncSession
    engine: ExecutionEngine
    context: MarketContext
    dna_by_version: dict[uuid.UUID, StrategyDNA]
    stage_by_version: dict[uuid.UUID, StrategyStage]
    dyn_current: dict
    dyn_previous: dict
    prev_context: MarketContext | None
    council: CouncilContext
    council_decision_id: uuid.UUID | None
    global_max_leverage: float
    global_max_position_size: float
    global_max_drawdown: float
    global_max_daily_loss: float
    market_data_age_seconds: float | None
    halt_reason: str | None
    fee_rate: float
    positions: dict[uuid.UUID, Position]
    funding_rates: list[FundingRate]
    interval_ms: int

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


def _council_context(
    context: MarketContext, council_decision_id, council_trade_allowed: bool, council_bias, council_confidence,
    council_status: str | None,
) -> CouncilContext:
    if council_decision_id is None and council_bias is None:
        status = INCOMPLETE if not council_trade_allowed else NOT_RUN
    else:
        status = council_status or (COMPLETE if council_trade_allowed else INCOMPLETE)
    return CouncilContext(
        status=status, bias=council_bias, confidence=council_confidence, trade_allowed=council_trade_allowed,
        candle_open_time=context.candle_open_time, decision_id=council_decision_id,
    ).for_candle(context.candle_open_time)


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
    trading_halt_override: str | None = None,
    candles: pd.DataFrame | None = None,
) -> int:
    """Evaluates every ACTIVE agent in `generation` against `context`.
    Returns the number of agents processed.

    `council_trade_allowed=False` (INCOMPLETE council) still runs every agent
    so exits/audit Decisions keep happening, but blocks every NEW entry through
    the Risk Engine — fail closed, never skip the risk check.

    `candles` (the confirmed-bar frame ending at `context`) enables the DNA's
    declared dynamic indicators; without it only the static context features
    are available (legacy callers/tests)."""
    settings = get_settings()
    fee_rate = fee_rate if fee_rate is not None else settings.paper_fee_rate
    halt_reason = trading_halt_override or await _load_trading_halt_reason(db)

    agents = (
        await db.execute(
            select(Agent).where(Agent.generation == generation, Agent.status == AgentStatus.ACTIVE)
        )
    ).scalars().all()
    if not agents:
        return 0

    # A durable unique constraint is the final protection; excluding an
    # already-audited candle avoids needless work when a worker restarts.
    decided_ids = set((await db.execute(
        select(Decision.agent_id).where(Decision.market_candle_open_time == context.candle_open_time)
    )).scalars().all())
    agents = [a for a in agents if a.id not in decided_ids]
    if not agents:
        return 0

    versions = (
        await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents})))
    ).scalars().all()

    # One drifted/legacy StrategyVersion must never crash the population's cycle.
    dna_by_version: dict[uuid.UUID, StrategyDNA] = {}
    stage_by_version: dict[uuid.UUID, StrategyStage] = {}
    for v in versions:
        try:
            dna_by_version[v.id] = StrategyDNA.model_validate(v.dna)
            stage_by_version[v.id] = v.stage
        except ValidationError as exc:
            logger.error("decision_loop.strategy_dna_invalid_skipping_version", strategy_version_id=str(v.id), error=str(exc))

    agents = [a for a in agents if a.strategy_version_id in dna_by_version]
    if not agents:
        return 0

    interval_ms = HyperliquidClient.timeframe_to_ms(context.timeframe)

    # Batch loads: ONE query each for the whole population.
    positions = {
        p.agent_id: p
        for p in (
            await db.execute(
                select(Position).where(Position.agent_id.in_([a.id for a in agents]), Position.is_open.is_(True))
            )
        ).scalars().all()
    }
    funding_rates: list[FundingRate] = []
    close_ms = context.candle_close_time or (context.candle_open_time + interval_ms - 1)
    if positions:
        earliest = min(
            int(p.last_funding_time.timestamp() * 1000) if p.last_funding_time else close_ms for p in positions.values()
        )
        funding_rates = list(
            (
                await db.execute(
                    select(FundingRate)
                    .where(FundingRate.symbol == context.symbol, FundingRate.time_ms > earliest, FundingRate.time_ms <= close_ms)
                    .order_by(FundingRate.time_ms)
                )
            ).scalars().all()
        )

    # Population-wide dynamic indicators, each distinct spec computed ONCE.
    dyn_current: dict = {}
    dyn_previous: dict = {}
    if candles is not None and len(candles):
        dyn_current, dyn_previous = compute_population_features(candles, dna_by_version.values())

    cc = CycleContext(
        db=db, engine=execution_engine, context=context, dna_by_version=dna_by_version, stage_by_version=stage_by_version,
        dyn_current=dyn_current, dyn_previous=dyn_previous, prev_context=prev_context,
        council=_council_context(context, council_decision_id, council_trade_allowed, council_bias, council_confidence, council_status),
        council_decision_id=council_decision_id,
        global_max_leverage=global_max_leverage, global_max_position_size=global_max_position_size,
        global_max_drawdown=global_max_drawdown, global_max_daily_loss=global_max_daily_loss,
        market_data_age_seconds=market_data_age_seconds, halt_reason=halt_reason, fee_rate=fee_rate,
        positions=positions, funding_rates=funding_rates, interval_ms=interval_ms,
    )

    processed = 0
    for agent in agents:
        identifier = agent.identifier  # captured: attributes expire if the savepoint rolls back
        try:
            async with db.begin_nested():
                await _process_agent(cc, agent)
            processed += 1
        except Exception:
            metrics.inc("agent_cycle_errors")
            logger.exception("decision_loop.agent_failed_isolated", identifier=identifier,
                             candle_open_time=context.candle_open_time)

    await db.commit()
    metrics.inc("agents_processed", processed)
    metrics.inc("agent_decisions", processed)
    return processed


# --------------------------------------------------------------------------- #
# Per-agent processing
# --------------------------------------------------------------------------- #
def _set_equity(agent: Agent, equity: float, *, death_reason: str = "equity_depleted") -> None:
    """update_equity that is a no-op on an already-dead agent (a dead agent's
    account is frozen; it must never raise mid-cycle)."""
    if agent.status != AgentStatus.DEAD:
        update_equity(agent, equity, death_reason=death_reason)


async def _process_agent(cc: CycleContext, agent: Agent) -> None:
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

    decision = Decision(
        agent_id=agent.id, strategy_version_id=agent.strategy_version_id, council_decision_id=cc.council_decision_id,
        market_candle_open_time=context.candle_open_time, market_timestamp=market_ts,
        market_context=context.model_dump(mode="json"),
        agent_signal=Bias.NEUTRAL, agent_signal_confidence=0.0, agent_signal_reasoning={},
        council_bias=cc.council.bias, council_confidence=cc.council.confidence, final_signal=Bias.NEUTRAL,
        risk_decision=RiskDecision.REJECTED, risk_reasoning={},
    )
    db.add(decision)
    await db.flush()  # decision.id seeds the deterministic order idempotency key

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
            await _close_position(cc, agent, dna, stage, position, decision, reference_price=bar.close,
                                  order_kind="market", exit_reason=signal.reasoning.get("exit_reason") or "signal")
        else:
            decision.risk_reasoning = {"skipped": "position_open_holding"}
        return

    if not signal.matched_entry:
        decision.risk_reasoning = {"skipped": "no_entry_signal_or_position_open"}
        return

    # DNA trade-frequency controls are hard runtime gates, not metadata.
    if agent.cooldown_until is not None and market_ts < agent.cooldown_until:
        decision.risk_reasoning = {"skipped": "cooldown_active", "cooldown_until": agent.cooldown_until.isoformat()}
        return
    if agent.daily_trade_count >= dna.max_trades_per_day:
        decision.risk_reasoning = {"skipped": "max_trades_per_day_reached"}
        return

    # ---- 3. council as shared context (never an oracle) ------------------- #
    combined = combine(signal.bias, cc.council)
    decision.final_signal = combined.final_signal
    council_audit = combined.audit()
    if combined.reason == "council_directional_conflict_veto":
        decision.risk_reasoning = {"skipped": "council_directional_conflict", "council": council_audit}
        return

    # ---- 4. sizing + risk ------------------------------------------------- #
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
            # The Risk Engine — not this loop — is the single enforcement point
            # for an INCOMPLETE council, so it is always consulted.
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
        metrics.inc("risk_vetoes")
        return

    # ---- 5. order + fill -------------------------------------------------- #
    order = Order(
        agent_id=agent.id, decision_id=decision.id,
        client_order_id=new_client_order_id(str(agent.id), str(decision.id)),
        symbol=context.symbol, side=side, quantity=sizing.quantity,
        requested_notional=requested, approved_notional=approved, initial_margin=sizing.margin,
        risk_amount=sizing.risk_amount, requested_price=context.close_price, leverage=sizing.leverage,
        venue=cc.engine.venue, status=OrderStatus.PENDING, reduce_only=False, order_kind="market",
        submitted_at=cc.close_dt,
    )
    db.add(order)
    await db.flush()

    fill = await cc.engine.submit_order(
        ExecutionRequest(
            client_order_id=order.client_order_id, agent_id=str(agent.id), symbol=context.symbol, side=side,
            quantity=sizing.quantity, leverage=sizing.leverage, reference_price=context.close_price,
        )
    )
    _apply_fill_to_order(order, fill, cc)
    decision.order_id = order.id
    metrics.inc("orders", kind="entry", status=fill.status.value)

    if fill.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) or fill.filled_price is None or fill.filled_quantity <= 0:
        decision.risk_reasoning = {**decision.risk_reasoning, "order_rejection": fill.rejection_reason}
        metrics.inc("order_rejections", reason=fill.rejection_reason or "unknown")
        return

    notional = fill.filled_price * fill.filled_quantity
    entry = fill.filled_price
    liq_price = compute_liquidation_price(
        side=side, entry_price=entry, quantity=fill.filled_quantity, balance=agent.balance - fill.fee,
        maintenance_margin_rate=settings.maintenance_margin_rate,
    )
    sl = stop_price(entry, side, method=dna.stop_loss.method, value=dna.stop_loss.value, atr=atr,
                    swing_low=swing_low, swing_high=swing_high) if dna.stop_loss.enabled else None
    tp = take_profit_price(entry, side, method=dna.take_profit.method, value=dna.take_profit.value, atr=atr, stop=sl) \
        if dna.take_profit.enabled else None
    trail_dist = entry * dna.trailing_stop.trail_pct / 100 if dna.trailing_stop.enabled and dna.trailing_stop.trail_pct > 0 else None
    position = Position(
        agent_id=agent.id, symbol=context.symbol, side=side, quantity=fill.filled_quantity, entry_price=entry,
        leverage=sizing.leverage, initial_margin=notional / sizing.leverage,
        maintenance_margin=notional * settings.maintenance_margin_rate,
        peak_price=entry, trough_price=entry, last_funding_time=cc.close_dt,
        entry_order_id=order.id, entry_fee=fill.fee, entry_slippage_cost=fill.slippage_cost,
        liquidation_price=liq_price, entry_candle_open_time=context.candle_open_time,
        entry_regime=context.regime.regime.value,
        trailing_active=bool(trail_dist and dna.trailing_stop.activation_pct <= 0),
        stop_loss_price=sl, take_profit_price=tp, trailing_stop_distance=trail_dist,
        opened_at=cc.close_dt,
    )
    db.add(position)
    cc.positions[agent.id] = position

    agent.balance -= fill.fee
    agent.fees_paid += fill.fee
    agent.trade_count += 1
    agent.daily_trade_count += 1
    agent.last_trade_time = cc.close_dt
    _set_equity(agent, agent.balance)


def _apply_fill_to_order(order: Order, fill, cc: CycleContext) -> None:
    order.status = fill.status
    order.rejection_reason = fill.rejection_reason
    order.filled_at = cc.close_dt if fill.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) else None
    order.raw_venue_response = fill.raw_response
    order.latency_ms = fill.latency_ms
    order.filled_quantity = fill.filled_quantity
    order.filled_price = fill.filled_price
    order.fee = fill.fee
    order.slippage_cost = fill.slippage_cost


# --------------------------------------------------------------------------- #
# Open-position management
# --------------------------------------------------------------------------- #
async def _accrue_funding(cc: CycleContext, agent: Agent, position: Position) -> None:
    """Applies every exchange-published funding settlement in
    (last processed settlement, this bar's close]. Idempotent through the
    (position, settlement time) unique constraint."""
    last_ms = int(position.last_funding_time.timestamp() * 1000) if position.last_funding_time else 0
    due = [r for r in cc.funding_rates if last_ms < r.time_ms <= cc.close_ms]
    if not due:
        return
    for r in due:
        notional = position.quantity * cc.context.close_price
        payment = notional * r.rate * (1 if position.side == Side.LONG else -1)  # + = agent pays
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
    cc: CycleContext, agent: Agent, dna: StrategyDNA, stage: StrategyStage, position: Position, decision: Decision, bar: Bar
) -> bool:
    """Returns True if the position was closed this bar."""
    settings = get_settings()
    await _accrue_funding(cc, agent, position)

    # Liquidation price depends on the CURRENT balance (funding/fees applied).
    liq_price = compute_liquidation_price(
        side=position.side, entry_price=position.entry_price, quantity=position.quantity, balance=agent.balance,
        maintenance_margin_rate=settings.maintenance_margin_rate,
    )
    position.liquidation_price = liq_price
    levels = PositionLevels(
        side=position.side, entry_price=position.entry_price, stop_loss_price=position.stop_loss_price,
        take_profit_price=position.take_profit_price, trailing_distance=position.trailing_stop_distance,
        trailing_activation_pct=dna.trailing_stop.activation_pct if dna.trailing_stop.enabled else 0.0,
        trailing_active=position.trailing_active, peak_price=position.peak_price, trough_price=position.trough_price,
        liquidation_price=liq_price,
    )
    trigger = evaluate_bar(levels, bar)
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


async def _close_position(
    cc: CycleContext, agent: Agent, dna: StrategyDNA, stage: StrategyStage, position: Position, decision: Decision,
    *, reference_price: float, order_kind: str, exit_reason: str,
) -> bool:
    """Closes through the ExecutionEngine (a real reduce-only order, real fees
    and slippage) and books the Trade. Returns False if the exit did not fill
    (the position stays open and is retried next bar)."""
    settings = get_settings()
    db, context = cc.db, cc.context
    order = Order(
        agent_id=agent.id, decision_id=decision.id,
        client_order_id=new_client_order_id(str(agent.id), str(decision.id), "exit"),
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
    _apply_fill_to_order(order, fill, cc)
    metrics.inc("orders", kind="exit", status=fill.status.value)
    if fill.status != OrderStatus.FILLED or fill.filled_price is None:
        decision.risk_reasoning = {**(decision.risk_reasoning or {}), "exit_failed": fill.rejection_reason, "intended_exit": exit_reason}
        logger.error("decision_loop.exit_not_filled", identifier=agent.identifier, reason=fill.rejection_reason)
        return False

    exit_fee = fill.fee
    if order_kind == "liquidation":  # exchange liquidation penalty on the closed notional
        exit_fee += fill.filled_price * position.quantity * settings.liquidation_fee_rate

    pnl = compute_trade_pnl(
        side=position.side, quantity=position.quantity, entry_price=position.entry_price, exit_price=fill.filled_price,
        entry_fee=position.entry_fee, exit_fee=exit_fee, funding_paid=position.funding_accrued,
        slippage_cost=position.entry_slippage_cost + fill.slippage_cost,
    )
    position.is_open = False
    position.closed_at = cc.close_dt
    position.unrealized_pnl = 0.0
    cc.positions.pop(agent.id, None)

    trade = Trade(
        agent_id=agent.id, position_id=position.id, entry_order_id=position.entry_order_id, exit_order_id=order.id,
        symbol=position.symbol, side=position.side, quantity=position.quantity, entry_price=position.entry_price,
        exit_price=fill.filled_price, gross_pnl=pnl.gross_pnl, fees=pnl.fees, funding=pnl.funding,
        slippage_cost=pnl.slippage_cost, net_pnl=pnl.net_pnl, opened_at=position.opened_at, closed_at=position.closed_at,
        holding_seconds=max(0, int((position.closed_at - position.opened_at).total_seconds())),
        entry_regime=position.entry_regime, exit_regime=context.regime.regime.value, exit_reason=exit_reason, stage=stage,
    )
    db.add(trade)
    await db.flush()

    decision.risk_decision = RiskDecision.APPROVED
    decision.risk_reasoning = {**(decision.risk_reasoning or {}), "action": "close_position", "exit_reason": exit_reason}
    decision.order_id = order.id
    decision.trade_id = trade.id

    # Entry fee and funding were already deducted from balance when they were
    # incurred; only the price PnL and the exit fee remain to settle here.
    agent.balance = max(0.0, agent.balance + pnl.gross_pnl - exit_fee)
    agent.realized_pnl += pnl.net_pnl
    agent.fees_paid += exit_fee
    _set_equity(agent, agent.balance, death_reason="liquidated" if order_kind == "liquidation" else "equity_depleted")
    if exit_reason == "liquidation" and settings.liquidation_is_fatal and agent.status != AgentStatus.DEAD:
        mark_dead(agent, reason="liquidated")
    if agent.status == AgentStatus.DEAD:
        logger.warning("agent.died_on_trade_close", identifier=agent.identifier, net_pnl=pnl.net_pnl, exit_reason=exit_reason)
        metrics.inc("agents_died", reason=agent.death_reason or "unknown")

    cooldown_bars = dna.cooldown.bars_after_win if pnl.net_pnl >= 0 else dna.cooldown.bars_after_loss
    if cooldown_bars:
        # Cooldown is counted in BARS of the configured timeframe, measured on the candle clock.
        agent.cooldown_until = cc.close_dt + timedelta(milliseconds=cc.interval_ms * cooldown_bars)
    return True
