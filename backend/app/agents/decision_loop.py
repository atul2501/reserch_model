"""Per-candle agent evaluation loop (spec sections 3/4/12/32).

For ONE shared MarketContext, evaluates every ACTIVE agent's strategy DNA
deterministically, runs the risk engine, and (if approved) submits an order
through the execution engine — writing a full Decision audit row regardless
of outcome. This is the "500 agents consume one shared context" step; it
never calls Ollama itself (the council already ran upstream for this candle).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
) -> None:
    market_timestamp = datetime.fromtimestamp(context.candle_open_time / 1000, tz=timezone.utc)

    open_position = (
        await db.execute(
            select(Position).where(Position.agent_id == agent.id, Position.is_open.is_(True))
        )
    ).scalar_one_or_none()

    if open_position is not None:
        _mark_to_market(agent, open_position, context.close_price)

    # Anchor the daily-loss circuit breaker to the candle clock (not
    # wall-clock) so this stays correct under backtests/replays too.
    candle_date = market_timestamp.date()
    if agent.day_start_date != candle_date:
        agent.day_start_equity = agent.equity
        agent.day_start_date = candle_date

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
        risk_decision=RiskDecision.REJECTED,
        risk_reasoning={},
    )

    if open_position is not None and signal.matched_exit:
        await _close_position(db, agent, open_position, context, decision, fee_rate, stage)
        db.add(decision)
        return

    if open_position is not None or not signal.matched_entry:
        decision.risk_reasoning = {"skipped": "no_entry_signal_or_position_open"}
        db.add(decision)
        return

    notional = agent.equity * dna.position_sizing.fraction_of_equity * dna.leverage_limit
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
    order = Order(
        agent_id=agent.id,
        decision_id=decision.id,
        client_order_id=new_client_order_id(str(agent.id), str(decision.id)),
        symbol=context.symbol,
        side=side,
        quantity=quantity,
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
        opened_at=datetime.now(timezone.utc),
    )
    db.add(position)

    agent.balance -= fill.fee
    agent.fees_paid += fill.fee
    agent.trade_count += 1
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
        update_equity(agent, agent.balance + position.unrealized_pnl)


async def _close_position(
    db: AsyncSession,
    agent: Agent,
    position: Position,
    context: MarketContext,
    decision: Decision,
    fee_rate: float,
    stage: StrategyStage,
) -> None:
    exit_price = context.close_price
    fee = exit_price * position.quantity * fee_rate

    pnl = compute_trade_pnl(
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_fee=0.0,  # entry fee already deducted from balance at open time
        exit_fee=fee,
        funding_paid=0.0,
        slippage_cost=0.0,
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
        exit_reason="signal",
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
