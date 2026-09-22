"""Per-candle agent evaluation loop (spec sections 3/4/12/32).

For ONE shared MarketContext, evaluates every ACTIVE agent's strategy DNA
deterministically, runs the risk engine, and (if approved) submits an order
through the execution engine — writing a full Decision audit row regardless
of outcome. This is the "500 agents consume one shared context" step; it
never calls Ollama itself (the council already ran upstream for this candle).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lifecycle import update_equity
from app.analytics.pnl_engine import compute_trade_pnl, compute_unrealized_pnl
from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.base import ExecutionEngine, ExecutionRequest
from app.execution.paper_adapter import new_client_order_id
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.enums import AgentStatus, Bias, OrderStatus, RiskDecision, Side, StrategyStage
from app.models.strategy import StrategyVersion
from app.models.trading import Order, Position, Trade
from app.risk.risk_engine import RiskCheckInput, check_trade
from app.schemas.market_context import MarketContext
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.rule_engine import evaluate

logger = get_logger(__name__)


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
) -> int:
    """Evaluates every ACTIVE agent in `generation` against `context`.
    Returns the number of agents processed.

    `council_trade_allowed=False` (this candle's council cycle was
    INCOMPLETE — quorum not met) still runs every agent so exits/audit
    Decisions keep happening, but blocks every NEW entry via the Risk
    Engine (see RiskCheckInput.council_trade_allowed / check_trade) —
    fail closed, never skip the risk check just to keep the cycle moving."""
    fee_rate = fee_rate if fee_rate is not None else get_settings().paper_fee_rate
    agents = (
        await db.execute(
            select(Agent).where(Agent.generation == generation, Agent.status == AgentStatus.ACTIVE)
        )
    ).scalars().all()
    if not agents:
        return 0

    # A durable unique constraint is the final protection.  Excluding an
    # already-audited candle here avoids needless work when a worker restarts.
    decided_ids = set((await db.execute(
        select(Decision.agent_id).where(Decision.market_candle_open_time == context.candle_open_time)
    )).scalars().all())
    agents = [agent for agent in agents if agent.id not in decided_ids]

    strategy_version_ids = {a.strategy_version_id for a in agents}
    versions = (
        await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_(strategy_version_ids)))
    ).scalars().all()

    # Each StrategyVersion's DNA is validated once, at insert time (see
    # app/models/strategy.py) — but a single StrategyVersion whose stored
    # JSON no longer matches the CURRENT StrategyDNA schema (schema drift
    # from ongoing development, or a hand-edited/legacy row) must never
    # crash the whole population's cycle. Isolate per-version: skip that
    # version's agents this cycle, log it loudly, keep going for everyone
    # else. This was previously unguarded and was the confirmed root cause
    # of a whole-cycle crash from a single bad StrategyVersion row.
    dna_by_version_id: dict[uuid.UUID, StrategyDNA] = {}
    stage_by_version_id: dict[uuid.UUID, StrategyStage] = {}
    broken_version_ids: set[uuid.UUID] = set()
    for v in versions:
        try:
            dna_by_version_id[v.id] = StrategyDNA.model_validate(v.dna)
            stage_by_version_id[v.id] = v.stage
        except ValidationError as exc:
            broken_version_ids.add(v.id)
            logger.error(
                "decision_loop.strategy_dna_invalid_skipping_version",
                strategy_version_id=str(v.id),
                error=str(exc),
            )

    processed = 0
    for agent in agents:
        if agent.strategy_version_id in broken_version_ids:
            continue
        dna = dna_by_version_id[agent.strategy_version_id]
        stage = stage_by_version_id[agent.strategy_version_id]
        await _process_agent(
            db,
            execution_engine,
            agent,
            dna,
            stage,
            context,
            prev_context,
            council_decision_id=council_decision_id,
            global_max_leverage=global_max_leverage,
            global_max_position_size=global_max_position_size,
            global_max_drawdown=global_max_drawdown,
            global_max_daily_loss=global_max_daily_loss,
            market_data_age_seconds=market_data_age_seconds,
            fee_rate=fee_rate,
            council_trade_allowed=council_trade_allowed,
            council_bias=council_bias,
            council_confidence=council_confidence,
        )
        processed += 1

    await db.commit()
    return processed


async def _process_agent(
    db: AsyncSession,
    execution_engine: ExecutionEngine,
    agent: Agent,
    dna: StrategyDNA,
    stage: StrategyStage,
    context: MarketContext,
    prev_context: MarketContext | None,
    *,
    council_decision_id: uuid.UUID | None,
    global_max_leverage: float,
    global_max_position_size: float,
    global_max_drawdown: float,
    global_max_daily_loss: float,
    market_data_age_seconds: float | None,
    fee_rate: float,
    council_trade_allowed: bool = True,
    council_bias: Bias | None = None,
    council_confidence: float | None = None,
) -> None:
    market_timestamp = datetime.fromtimestamp(context.candle_open_time / 1000, tz=timezone.utc)

    open_position = (
        await db.execute(
            select(Position).where(Position.agent_id == agent.id, Position.is_open.is_(True))
        )
    ).scalar_one_or_none()

    if open_position is not None:
        _mark_to_market(agent, open_position, context.close_price)
        _apply_funding(agent, open_position, context)

    # Anchor the daily-loss circuit breaker to the candle clock (not
    # wall-clock) so this stays correct under backtests/replays too.
    candle_date = market_timestamp.date()
    if agent.day_start_date != candle_date:
        agent.day_start_equity = agent.equity
        agent.day_start_date = candle_date
        agent.daily_trade_count = 0

    signal = evaluate(dna, context, prev_context, has_open_position=open_position is not None)

    decision = Decision(
        agent_id=agent.id,
        strategy_version_id=agent.strategy_version_id,
        council_decision_id=council_decision_id,
        market_candle_open_time=context.candle_open_time,
        market_timestamp=market_timestamp,
        market_context=context.model_dump(mode="json"),
        agent_signal=signal.bias,
        agent_signal_confidence=signal.confidence,
        agent_signal_reasoning=signal.reasoning,
        council_bias=council_bias,
        council_confidence=council_confidence,
        final_signal=signal.bias,
        risk_decision=RiskDecision.REJECTED,
        risk_reasoning={},
    )

    protective_exit = _protective_exit_reason(open_position, context) if open_position is not None else None
    if open_position is not None and (signal.matched_exit or protective_exit is not None):
        await _close_position(
            db, agent, open_position, context, decision, fee_rate, stage,
            dna=dna, exit_reason=protective_exit or "signal",
        )
        db.add(decision)
        return

    if open_position is not None or not signal.matched_entry:
        decision.risk_reasoning = {"skipped": "no_entry_signal_or_position_open"}
        db.add(decision)
        return

    # DNA trade-frequency controls are hard runtime gates, not metadata.
    if agent.cooldown_until is not None and market_timestamp < agent.cooldown_until:
        decision.risk_reasoning = {"skipped": "cooldown_active", "cooldown_until": agent.cooldown_until.isoformat()}
        db.add(decision)
        return
    if agent.daily_trade_count >= dna.max_trades_per_day:
        decision.risk_reasoning = {"skipped": "max_trades_per_day_reached"}
        db.add(decision)
        return

    size_modifier = 1.0
    if council_bias is not None:
        if council_bias in (Bias.LONG, Bias.SHORT) and council_bias != signal.bias and (council_confidence or 0) >= 0.60:
            decision.final_signal = Bias.NEUTRAL
            decision.risk_reasoning = {"skipped": "council_directional_conflict", "agent_signal": signal.bias.value}
            db.add(decision)
            return
        if council_bias == Bias.NEUTRAL:
            size_modifier = 0.75
    decision.final_signal = signal.bias

    notional = _proposed_notional(agent, dna, context) * size_modifier
    risk_result = check_trade(
        RiskCheckInput(
            agent=agent,
            dna=dna,
            side=signal.bias if signal.bias in (Bias.LONG, Bias.SHORT) else Bias.LONG,
            proposed_notional=notional,
            proposed_leverage=dna.leverage_limit,
            current_price=context.close_price,
            atr=context.volatility.atr_14,
            equity=agent.equity,
            daily_pnl=agent.equity - agent.day_start_equity,
            has_open_position=False,
            market_data_age_seconds=market_data_age_seconds,
            council_trade_allowed=council_trade_allowed,
        ),
        global_max_leverage=global_max_leverage,
        global_max_position_size=global_max_position_size,
        global_max_drawdown=global_max_drawdown,
        global_max_daily_loss=global_max_daily_loss,
    )
    decision.risk_decision = risk_result.decision
    decision.risk_reasoning = {"reasons": risk_result.reasons, "approved_notional": risk_result.approved_notional}

    if risk_result.decision == RiskDecision.REJECTED:
        db.add(decision)
        return

    # `decision` must be added BEFORE this flush, or decision.id stays
    # None (SQLAlchemy's uuid4 default only fires for objects actually in
    # the session) — new_client_order_id(agent_id, str(decision.id)) below
    # would then build the literal string f"{agent_id}:None" for every
    # first order, and the SAME string again for that agent's next order
    # after it, violating the UNIQUE constraint on Order.client_order_id
    # and crashing the whole cycle. This was the confirmed root cause of
    # the live "UNIQUE constraint failed: orders.client_order_id" crash.
    db.add(decision)
    await db.flush()  # decision.id needed for the idempotency key
    side = Side.LONG if signal.bias == Bias.LONG else Side.SHORT
    quantity = risk_result.approved_notional / context.close_price
    initial_margin = risk_result.approved_notional / risk_result.approved_leverage
    order = Order(
        agent_id=agent.id,
        decision_id=decision.id,
        client_order_id=new_client_order_id(str(agent.id), str(decision.id)),
        symbol=context.symbol,
        side=side,
        quantity=quantity,
        requested_notional=notional,
        approved_notional=risk_result.approved_notional,
        initial_margin=initial_margin,
        risk_amount=_risk_amount(dna, risk_result.approved_notional, context),
        requested_price=context.close_price,
        leverage=risk_result.approved_leverage,
        venue=execution_engine.venue,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    fill = await execution_engine.submit_order(
        ExecutionRequest(
            client_order_id=order.client_order_id,
            agent_id=str(agent.id),
            symbol=context.symbol,
            side=side,
            quantity=quantity,
            leverage=risk_result.approved_leverage,
            reference_price=context.close_price,
        )
    )
    order.status = fill.status
    order.rejection_reason = fill.rejection_reason
    order.filled_at = datetime.now(timezone.utc) if fill.status == OrderStatus.FILLED else None
    order.raw_venue_response = fill.raw_response
    order.latency_ms = fill.latency_ms

    decision.order_id = order.id

    if fill.status != OrderStatus.FILLED or fill.filled_price is None:
        db.add(decision)
        return

    position = Position(
        agent_id=agent.id,
        symbol=context.symbol,
        side=side,
        quantity=fill.filled_quantity,
        entry_price=fill.filled_price,
        leverage=risk_result.approved_leverage,
        initial_margin=initial_margin,
        maintenance_margin=risk_result.approved_notional * 0.005,
        peak_price=fill.filled_price,
        trough_price=fill.filled_price,
        last_funding_time=market_timestamp,
        stop_loss_price=_stop_price(dna, fill.filled_price, context.volatility.atr_14, side),
        take_profit_price=_take_profit_price(dna, fill.filled_price, context.volatility.atr_14, side),
        trailing_stop_distance=(fill.filled_price * dna.trailing_stop.trail_pct / 100 if dna.trailing_stop.enabled else None),
        opened_at=datetime.now(timezone.utc),
    )
    db.add(position)

    agent.balance -= fill.fee
    agent.fees_paid += fill.fee
    agent.trade_count += 1
    agent.daily_trade_count += 1
    agent.last_trade_time = market_timestamp
    update_equity(agent, agent.balance)

    db.add(decision)


def _mark_to_market(agent: Agent, position: Position, current_price: float) -> None:
    """Updates the open position's unrealized PnL and the agent's equity
    every candle — without this, drawdown/risk checks would only see stale
    equity from the last time a position closed."""
    position.unrealized_pnl = compute_unrealized_pnl(
        side=position.side, quantity=position.quantity, entry_price=position.entry_price, current_price=current_price
    )
    if agent.status != AgentStatus.DEAD:
        position.peak_price = max(position.peak_price or current_price, current_price)
        position.trough_price = min(position.trough_price or current_price, current_price)
        update_equity(agent, agent.balance + position.unrealized_pnl)


async def _close_position(
    db: AsyncSession,
    agent: Agent,
    position: Position,
    context: MarketContext,
    decision: Decision,
    fee_rate: float,
    stage: StrategyStage,
    *,
    dna: StrategyDNA,
    exit_reason: str,
) -> None:
    # Conservative bar assumption: where an OHLC bar could hit both a stop
    # and target, _protective_exit_reason chooses the stop.  Exits also pay
    # adverse paper slippage, matching entries rather than using raw close.
    direction = 1 if position.side == Side.LONG else -1
    exit_price = context.close_price * (1 - direction * get_settings().paper_slippage_bps / 10_000)
    fee = exit_price * position.quantity * fee_rate

    pnl = compute_trade_pnl(
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_fee=0.0,  # entry fee already deducted from balance at open time
        exit_fee=fee,
        funding_paid=0.0,
        slippage_cost=abs(exit_price - context.close_price) * position.quantity,
    )

    position.is_open = False
    position.closed_at = datetime.now(timezone.utc)
    position.unrealized_pnl = 0.0

    trade = Trade(
        agent_id=agent.id,
        position_id=position.id,
        symbol=position.symbol,
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        gross_pnl=pnl.gross_pnl,
        fees=pnl.fees,
        funding=pnl.funding,
        slippage_cost=pnl.slippage_cost,
        net_pnl=pnl.net_pnl,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        holding_seconds=int((position.closed_at - position.opened_at).total_seconds()),
        exit_reason=exit_reason,
        stage=stage,
    )
    db.add(trade)
    await db.flush()

    decision.risk_decision = RiskDecision.APPROVED
    decision.risk_reasoning = {"action": "close_position"}
    decision.trade_id = trade.id

    agent.balance += pnl.net_pnl
    agent.realized_pnl += pnl.net_pnl
    agent.fees_paid += fee
    update_equity(agent, agent.balance)

    if agent.status == AgentStatus.DEAD:
        logger.warning("agent.died_on_trade_close", identifier=agent.identifier, net_pnl=pnl.net_pnl)

    cooldown_bars = dna.cooldown.bars_after_win if pnl.net_pnl >= 0 else dna.cooldown.bars_after_loss
    if cooldown_bars:
        agent.cooldown_until = context_dt = datetime.fromtimestamp(
            context.candle_open_time / 1000, tz=timezone.utc
        ) + timedelta(minutes=cooldown_bars)


def _proposed_notional(agent: Agent, dna: StrategyDNA, context: MarketContext) -> float:
    sizing = dna.position_sizing
    if sizing.method == "fixed_notional":
        return sizing.max_notional or agent.equity * sizing.fraction_of_equity
    if sizing.method in {"volatility_scaled", "volatility_based"}:
        atr_pct = context.volatility.atr_14 / context.close_price if context.close_price else 1.0
        return agent.equity * sizing.fraction_of_equity * dna.leverage_limit * min(1.0, 0.02 / max(atr_pct, 0.001))
    if sizing.method in {"kelly_fraction", "risk_based"}:
        stop_pct = _stop_distance_pct(dna, context)
        return min(agent.equity * sizing.fraction_of_equity / max(stop_pct, 0.001), agent.equity * dna.leverage_limit)
    return agent.equity * sizing.fraction_of_equity * dna.leverage_limit


def _risk_amount(dna: StrategyDNA, notional: float, context: MarketContext) -> float:
    return notional * _stop_distance_pct(dna, context)


def _stop_distance_pct(dna: StrategyDNA, context: MarketContext) -> float:
    if not dna.stop_loss.enabled:
        return 1.0
    if dna.stop_loss.method == "atr_multiple":
        return context.volatility.atr_14 * dna.stop_loss.value / max(context.close_price, 1e-9)
    return dna.stop_loss.value / 100


def _stop_price(dna: StrategyDNA, entry_price: float, atr: float, side: Side) -> float | None:
    if not dna.stop_loss.enabled:
        return None
    distance = atr * dna.stop_loss.value if dna.stop_loss.method == "atr_multiple" else entry_price * dna.stop_loss.value / 100
    return entry_price - distance if side == Side.LONG else entry_price + distance


def _take_profit_price(dna: StrategyDNA, entry_price: float, atr: float, side: Side) -> float | None:
    if not dna.take_profit.enabled:
        return None
    if dna.take_profit.method == "atr_multiple":
        distance = atr * dna.take_profit.value
    elif dna.take_profit.method == "risk_reward_multiple" and dna.stop_loss.enabled:
        distance = abs(entry_price - (_stop_price(dna, entry_price, atr, side) or entry_price)) * dna.take_profit.value
    else:
        distance = entry_price * dna.take_profit.value / 100
    return entry_price + distance if side == Side.LONG else entry_price - distance


def _protective_exit_reason(position: Position, context: MarketContext) -> str | None:
    high, low = context.candle_high or context.close_price, context.candle_low or context.close_price
    if position.side == Side.LONG:
        stop_hit = position.stop_loss_price is not None and low <= position.stop_loss_price
        target_hit = position.take_profit_price is not None and high >= position.take_profit_price
    else:
        stop_hit = position.stop_loss_price is not None and high >= position.stop_loss_price
        target_hit = position.take_profit_price is not None and low <= position.take_profit_price
    # Worst-case ordering prevents an optimistic OHLC backtest/paper bias.
    if stop_hit:
        return "stop_loss"
    if target_hit:
        return "take_profit"
    if position.trailing_stop_distance:
        anchor = position.peak_price if position.side == Side.LONG else position.trough_price
        if anchor is not None:
            trigger = anchor - position.trailing_stop_distance if position.side == Side.LONG else anchor + position.trailing_stop_distance
            if (position.side == Side.LONG and low <= trigger) or (position.side == Side.SHORT and high >= trigger):
                return "trailing_stop"
    return None


def _apply_funding(agent: Agent, position: Position, context: MarketContext) -> None:
    if context.funding_rate is None or position.last_funding_time is None:
        return
    candle_time = datetime.fromtimestamp(context.candle_open_time / 1000, tz=timezone.utc)
    if candle_time - position.last_funding_time < timedelta(hours=1):
        return
    notional = position.quantity * context.close_price
    # Positive funding is paid by longs to shorts; negative reverses it.
    payment = notional * context.funding_rate * (1 if position.side == Side.LONG else -1)
    agent.balance -= payment
    agent.funding_paid += payment
    position.last_funding_time = candle_time
    update_equity(agent, agent.balance + position.unrealized_pnl)
