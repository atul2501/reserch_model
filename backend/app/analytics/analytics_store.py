"""DB I/O for the analytics foundation. The ONLY module that writes, and it
writes ONLY to trade_analytics / strategy_regime_matrix /
fitness_forward_performance. Raw trading tables are read, never modified —
tests/test_analytics_store.py asserts this with a checksum of every raw table.

All refresh functions are IDEMPOTENT: running them twice produces the same
rows (trade_analytics upserts by trade_id; the matrix is rebuilt per
computation_version in a transaction; fitness_forward_performance only INSERTs
rows that do not exist yet — it is write-once evidence).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import strategy_regime as sr
from app.analytics import trade_quality as tq
from app.analytics import fitness_forward as ff
from app.analytics.shadow_fitness import ShadowConfig
from app.models.agent import Agent
from app.models.analytics import FitnessForwardPerformance, StrategyRegimeMatrix, TradeAnalytics
from app.models.council import CouncilDecision
from app.models.decision import Decision
from app.models.market import MarketCandle, MarketRegimeRecord
from app.models.metrics import FitnessScore
from app.models.stage_metrics import StageMetrics
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import Order, Position, Trade
from app.models.enums import StrategyStage

COMPUTATION_VERSION = "v1"
REGIME_UNKNOWN = "UNKNOWN"
_WINDOWS = ("full", "24h", "7d")


@dataclass
class RefreshResult:
    trades_processed: int = 0
    trades_updated: int = 0
    crosscheck_failures: int = 0
    crosscheck_skipped: int = 0
    missing_candles: int = 0
    missing_episode: int = 0
    regime_mismatches: int = 0            # entry_regime vs the regime row at the signal bar
    findings: list[str] = field(default_factory=list)
    matrix_cells: int = 0
    ffp_inserted: int = 0
    ffp_existing: int = 0


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _bar_ms(candles: Sequence[tq.Bar]) -> int:
    """Interval of the candle grid (median diff), 60_000 fallback."""
    diffs = [b.open_time - a.open_time for a, b in zip(candles, candles[1:]) if b.open_time > a.open_time]
    if not diffs:
        return 60_000
    diffs.sort()
    return diffs[len(diffs) // 2]


# --------------------------------------------------------------------------- #
# Phase 1: trade_analytics
# --------------------------------------------------------------------------- #
async def refresh_trade_analytics(db: AsyncSession, *, computation_version: str = COMPUTATION_VERSION) -> RefreshResult:
    result = RefreshResult()
    now = datetime.now(timezone.utc)

    # (trade_id -> (computation_version, analytics_row_id or None)) — the None id
    # marks a row added earlier in THIS run (still pending flush).
    existing: dict[uuid.UUID, tuple[str, object]] = {
        row[0]: (row[1], row[2])
        for row in (await db.execute(
            select(TradeAnalytics.trade_id, TradeAnalytics.computation_version, TradeAnalytics.id)
        )).all()
    }

    # ---- load the replay corpus (confirmed candles, once) ------------------ #
    candle_rows = (
        await db.execute(
            select(MarketCandle).where(MarketCandle.is_final.is_(True)).order_by(MarketCandle.symbol, MarketCandle.timeframe, MarketCandle.open_time)
        )
    ).scalars().all()
    bars_by_key: dict[tuple[str, str], list[tq.Bar]] = {}
    for c in candle_rows:
        bars_by_key.setdefault((c.symbol, c.timeframe), []).append(
            tq.Bar(open_time=c.open_time, open=c.open, high=c.high, low=c.low, close=c.close)
        )
    bar_ms_by_key = {k: _bar_ms(v) for k, v in bars_by_key.items()}

    # ---- regime series -> episode ids (per symbol+timeframe) ---------------- #
    regime_rows = (
        await db.execute(
            select(MarketRegimeRecord.symbol, MarketRegimeRecord.timeframe,
                   MarketRegimeRecord.candle_open_time, MarketRegimeRecord.regime)
            .order_by(MarketRegimeRecord.symbol, MarketRegimeRecord.timeframe, MarketRegimeRecord.candle_open_time)
        )
    ).all()
    episodes_by_key: dict[tuple[str, str], dict[int, int]] = {}
    regimes_by_key: dict[tuple[str, str], dict[int, str]] = {}
    current_key: tuple[str, str] | None = None
    series: list[tuple[int, str]] = []
    for symbol, timeframe, open_time, regime in regime_rows:
        key = (symbol, timeframe)
        if key != current_key:
            if current_key is not None:
                episodes_by_key[current_key] = sr.episode_ids(series)
            current_key = key
            series = []
        series.append((open_time, regime.value if hasattr(regime, "value") else str(regime)))
        regimes_by_key.setdefault(key, {})[open_time] = regime.value if hasattr(regime, "value") else str(regime)
    if current_key is not None:
        episodes_by_key[current_key] = sr.episode_ids(series)

    # ---- entry decisions + orders + positions for every trade ---------------- #
    rows = (
        await db.execute(
            select(Trade, Position, Order, Decision, Strategy.family)
            .join(Position, Position.id == Trade.position_id)
            .join(Order, Order.id == Trade.entry_order_id, isouter=True)
            .join(Decision, Decision.id == Order.decision_id, isouter=True)
            .outerjoin(StrategyVersion, StrategyVersion.id == Decision.strategy_version_id)
            .outerjoin(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .order_by(Trade.closed_at)
        )
    ).all()

    # exit-signal decision per trade (pending exits set decision.trade_id on close)
    exit_dec_by_trade: dict[uuid.UUID, Decision] = {}
    for d in (
        await db.execute(select(Decision).where(Decision.trade_id.is_not(None)).order_by(Decision.market_candle_open_time))
    ).scalars():
        exit_dec_by_trade.setdefault(d.trade_id, d)

    # exit orders for exit slippage
    exit_orders = {
        o.id: o
        for o in (await db.execute(select(Order).where(Order.reduce_only.is_(True)))).scalars()
    }

    # council decisions keyed for status lookup (decisions.council_decision_id -> status)
    council_status_by_id = {
        c.id: c.council_status
        for c in (await db.execute(select(CouncilDecision))).scalars()
    }

    for trade, position, entry_order, decision, family in rows:
        sym_key = (trade.symbol, next((tf for (s, tf) in bars_by_key if s == trade.symbol), "1m"))
        bars = bars_by_key.get(sym_key, [])
        bar_ms = bar_ms_by_key.get(sym_key, 60_000)

        long = str(trade.side).upper() != "SHORT"
        facts = tq.TradeFacts(
            side=str(trade.side).upper(), entry_price=trade.entry_price, exit_price=trade.exit_price,
            quantity=trade.quantity, opened_at_ms=_ms(trade.opened_at), closed_at_ms=_ms(trade.closed_at),
            stop_loss_price=position.stop_loss_price, take_profit_price=position.take_profit_price,
            persisted_peak_price=position.peak_price, persisted_trough_price=position.trough_price,
            entry_bar_open_ms=position.entry_candle_open_time, exit_reason=trade.exit_reason,
        )
        # slice bars around the trade (entry bar .. exit bar + POST_EXIT_BARS)
        lo = facts.entry_bar_open_ms if facts.entry_bar_open_ms is not None else facts.opened_at_ms
        hi = facts.closed_at_ms + bar_ms * (tq.POST_EXIT_BARS + 1)
        window_bars = [b for b in bars if lo - bar_ms <= b.open_time <= hi]
        ex = tq.analyze_trade(facts, window_bars, bar_ms)

        if ex.exit_bar_open_ms is None:
            result.missing_candles += 1
            result.findings.append(f"trade {trade.id}: no confirmed candle coverage for its window")

        # regime / episode via the SIGNAL bar (decision candle), fallback entry bar
        signal_bar = decision.market_candle_open_time if decision is not None else None
        episode_map = episodes_by_key.get(sym_key, {})
        regime_map = regimes_by_key.get(sym_key, {})
        regime = trade.entry_regime or REGIME_UNKNOWN
        episode_id = None
        for probe in (signal_bar, position.entry_candle_open_time):
            if probe is not None and probe in episode_map:
                episode_id = episode_map[probe]
                if trade.entry_regime is not None and regime_map.get(probe) != trade.entry_regime:
                    result.regime_mismatches += 1
                break
        if episode_id is None:
            result.missing_episode += 1

        # ---- entry quality -------------------------------------------------- #
        signal_close_ms = (entry_order.signal_candle_open_time + bar_ms) if entry_order is not None and entry_order.signal_candle_open_time is not None else None
        entry_delay = None
        if entry_order is not None and entry_order.filled_at is not None and entry_order.signal_candle_open_time is not None:
            entry_delay = (entry_order.filled_at.timestamp() - (entry_order.signal_candle_open_time + bar_ms) / 1000.0)
        entry_slip_bps = None
        if entry_order is not None and entry_order.requested_price and entry_order.filled_price:
            if long:
                entry_slip_bps = (entry_order.filled_price - entry_order.requested_price) / entry_order.requested_price * 1e4
            else:
                entry_slip_bps = (entry_order.requested_price - entry_order.filled_price) / entry_order.requested_price * 1e4

        reasoning = decision.agent_signal_reasoning if decision is not None else None
        setup_strength = None
        if isinstance(reasoning, dict):
            raw = reasoning.get("setup_strength")
            setup_strength = float(raw) if isinstance(raw, (int, float)) else None

        # ---- risk plan ------------------------------------------------------ #
        risk_amount = None
        if position.stop_loss_price is not None:
            r = trade.quantity * abs(trade.entry_price - position.stop_loss_price)
            risk_amount = r if r > 0 else None
        expected_r = None
        if risk_amount and position.take_profit_price is not None:
            tp_pnl = abs(position.take_profit_price - trade.entry_price) * trade.quantity
            expected_r = tp_pnl / risk_amount

        # ---- exit quality ---------------------------------------------------- #
        exit_delay = None
        exit_dec = exit_dec_by_trade.get(trade.id)
        if exit_dec is not None and exit_dec.market_candle_open_time is not None:
            exit_delay = trade.closed_at.timestamp() - (exit_dec.market_candle_open_time + bar_ms) / 1000.0
        exit_slip = None
        exit_order = exit_orders.get(trade.exit_order_id) if trade.exit_order_id is not None else None
        if exit_order is not None and exit_order.requested_price and exit_order.filled_price:
            if long:
                exit_slip = (exit_order.filled_price - exit_order.requested_price) / exit_order.requested_price * 1e4
            else:
                exit_slip = (exit_order.requested_price - exit_order.filled_price) / exit_order.requested_price * 1e4

        klass = tq.classify_trade(facts, ex, gross_pnl=trade.gross_pnl, net_pnl=trade.net_pnl)

        if ex.peak_crosscheck_ok is False or ex.trough_crosscheck_ok is False:
            result.crosscheck_failures += 1
            result.findings.append(
                f"trade {trade.id} ({trade.exit_reason}): replay peak/through "
                f"({ex.replay_peak!r}/{ex.replay_trough!r}) != persisted "
                f"({position.peak_price!r}/{position.trough_price!r})"
            )
        if ex.peak_crosscheck_ok is None or ex.trough_crosscheck_ok is None:
            result.crosscheck_skipped += 1

        version_id = decision.strategy_version_id if decision is not None else None
        payload = dict(
            trade_id=trade.id, agent_id=trade.agent_id,
            family=family.value if family is not None else None,
            strategy_version_id=version_id, regime=regime, side=str(trade.side).upper(),
            signal_bar_open_time_ms=signal_bar, signal_close_time_ms=signal_close_ms,
            entry_delay_seconds=entry_delay, expected_entry_price=entry_order.requested_price if entry_order is not None else None,
            entry_slippage_bps=entry_slip_bps,
            signal_confidence=decision.agent_signal_confidence if decision is not None else None,
            setup_strength=setup_strength,
            council_bias=(decision.council_bias.value if decision is not None and decision.council_bias is not None else None),
            council_confidence=decision.council_confidence if decision is not None else None,
            council_status=(council_status_by_id.get(decision.council_decision_id)
                             if decision is not None and decision.council_decision_id is not None else None),
            risk_amount=risk_amount,
            planned_risk_amount=entry_order.risk_amount if entry_order is not None else None,
            expected_r=expected_r,
            planned_stop_bps=(abs(trade.entry_price - position.stop_loss_price) / trade.entry_price * 1e4
                              if position.stop_loss_price is not None else None),
            planned_tp_bps=(abs(position.take_profit_price - trade.entry_price) / trade.entry_price * 1e4
                            if position.take_profit_price is not None else None),
            leverage=position.leverage, position_notional=trade.quantity * trade.entry_price,
            mfe_price=ex.mfe_price, mae_price=ex.mae_price, mfe_time_ms=ex.mfe_time_ms, mae_time_ms=ex.mae_time_ms,
            time_to_mfe_seconds=ex.time_to_mfe_seconds, time_to_mae_seconds=ex.time_to_mae_seconds,
            mfe_r=ex.mfe_r, mae_r=ex.mae_r, mfe_bps=ex.mfe_bps, mae_bps=ex.mae_bps,
            max_unrealized_profit=ex.max_unrealized_profit, max_unrealized_loss=ex.max_unrealized_loss,
            mfe_before_mae=ex.mfe_before_mae, exit_delay_seconds=exit_delay, exit_slippage_bps=exit_slip,
            post_exit_mfe_bps_30=ex.post_exit_mfe_bps, post_exit_mae_bps_30=ex.post_exit_mae_bps,
            left_on_table_r=ex.left_on_table_r, trade_quality_class=klass, regime_episode_id=episode_id,
            peak_crosscheck_ok=ex.peak_crosscheck_ok, trough_crosscheck_ok=ex.trough_crosscheck_ok,
            computation_version=computation_version, computed_at=now,
        )

        prev = existing.get(trade.id)
        if prev is not None and prev[0] == computation_version:
            # upsert-in-place: refresh the derived columns, keep the same row
            row_id = prev[1]
            if row_id is not None:
                obj = await db.get(TradeAnalytics, row_id)
                for k, v in payload.items():
                    if k in ("trade_id", "agent_id", "computation_version"):
                        continue
                    setattr(obj, k, v)
                obj.computation_version = computation_version
                result.trades_updated += 1
            else:
                # added earlier in this same run (double-counted trade?): skip
                result.findings.append(f"trade {trade.id}: seen twice in one refresh pass")
        else:
            db.add(TradeAnalytics(**payload))
            existing[trade.id] = (computation_version, None)
            result.trades_processed += 1

    await db.flush()
    return result


async def refresh_strategy_regime_matrix(
    db: AsyncSession, *, computation_version: str = COMPUTATION_VERSION,
) -> RefreshResult:
    """Rebuild the matrix for `computation_version` (derived aggregate: DELETE the
    previous rows of this version, then INSERT — inside the caller's transaction)."""
    from app.models.enums import MarketRegime

    result = RefreshResult()
    now = datetime.now(timezone.utc)
    cfg = ShadowConfig()

    ta_rows = (
        await db.execute(select(TradeAnalytics).where(TradeAnalytics.computation_version == computation_version))
    ).scalars().all()
    ta_by_trade = {ta.trade_id: ta for ta in ta_rows}

    trade_rows = (await db.execute(select(Trade).order_by(Trade.closed_at))).scalars().all()
    pairs = [(t, ta_by_trade.get(t.id)) for t in trade_rows]

    agent_ids = {t.agent_id for t, _ in pairs}
    agent_labels = {
        a.id: a.identifier
        for a in (await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars()
    } if agent_ids else {}

    data_end = max((t.closed_at for t, _ in pairs), default=now)
    windows: dict[str, datetime | None] = {
        "full": None,
        "24h": data_end - timedelta(hours=24),
        "7d": data_end - timedelta(days=7),
    }

    def _bps(t) -> float | None:
        notional = t.quantity * t.entry_price
        return (1e4 * t.net_pnl / notional) if notional > 0 else None

    cells: list[StrategyRegimeMatrix] = []
    for window_key, since in windows.items():
        in_window = [(t, ta) for (t, ta) in pairs if since is None or t.closed_at > since]

        by_key: dict[tuple[str, str, str], list[tuple[Trade, TradeAnalytics]]] = {}
        for t, ta in in_window:
            if ta is None:
                continue
            fam = ta.family or "UNKNOWN"
            regime = ta.regime or "UNKNOWN"
            by_key.setdefault(("family", fam, regime), []).append((t, ta))
            if ta.strategy_version_id is not None:
                by_key.setdefault(("version", str(ta.strategy_version_id), regime), []).append((t, ta))
            by_key.setdefault(("agent", str(ta.agent_id), regime), []).append((t, ta))

        for granularity in ("family", "version", "agent"):
            block = {dim: rows for (g, dim, _), rows in by_key.items() if g == granularity}
            # empirical-Bayes prior over this (window, granularity) block, informed by cells with enough trades
            cell_samples = {
                dim: [v for v in (_bps(t) for t, _ in rows) if v is not None]
                for dim, rows in block.items()
            }
            prior = sr.estimate_cell_prior(cell_samples, cfg)

            for (g, dim_id, regime), rows in sorted(by_key.items()):
                if g != granularity:
                    continue
                rowz = _as_trade_rows(rows)
                metrics = sr.cell_metrics(rowz)
                episodes = {ta.regime_episode_id for _, ta in rows if ta.regime_episode_id is not None}
                samples = [v for v in (_bps(t) for t, _ in rows) if v is not None]
                state = sr.cell_evidence_state(metrics["trade_count"], len(episodes), samples, prior, cfg)
                seed_key = (window_key, granularity, dim_id, regime)
                ci = sr.bootstrap_expectancy_ci(rowz, seed_key=seed_key)
                under = sr.under_sampled_flag(metrics["trade_count"], len(episodes), ci is not None)
                gross_edge, net_edge = sr.edge_flags(rowz, seed_key=seed_key, under_sampled=under)
                dim_label = dim_id if granularity == "family" else (
                    agent_labels.get(uuid.UUID(dim_id)) if granularity == "agent" and _is_uuid(dim_id) else None
                )
                cells.append(StrategyRegimeMatrix(
                    window_key=window_key, granularity=granularity, dim_id=dim_id, dim_label=dim_label,
                    regime=regime,
                    **{k: v for k, v in metrics.items()},
                    expectancy_ci_low=ci[0] if ci else None, expectancy_ci_high=ci[1] if ci else None,
                    episode_count=len(episodes), evidence_state=state, under_sampled=under,
                    gross_edge=gross_edge, net_edge=net_edge,
                    computation_version=computation_version, computed_at=now,
                ))

            # the under-sampled MAP: every (family, regime) combo that never traded
            if granularity == "family":
                traded = {dim for (g, dim, _) in by_key if g == "family"}
                from app.models.enums import MarketRegime, StrategyFamily

                all_families = {f.value for f in StrategyFamily}
                for fam in sorted(all_families - traded):
                    for regime in sorted({r.value for r in MarketRegime}):
                        metrics = sr.cell_metrics([])
                        cells.append(StrategyRegimeMatrix(
                            window_key=window_key, granularity="family", dim_id=fam, dim_label=fam,
                            regime=regime, **metrics,
                            expectancy_ci_low=None, expectancy_ci_high=None,
                            episode_count=0, evidence_state=sr.UNTESTED, under_sampled=True,
                            gross_edge=False, net_edge=False,
                            computation_version=computation_version, computed_at=now,
                        ))

    # replace the previous rows of this computation_version atomically with the new set
    for old in (await db.execute(
        select(StrategyRegimeMatrix).where(StrategyRegimeMatrix.computation_version == computation_version)
    )).scalars().all():
        await db.delete(old)
    await db.flush()          # DELETEs must reach the DB before the new INSERTs (same unique keys)
    for cell in cells:
        db.add(cell)
    await db.flush()
    result.matrix_cells = len(cells)
    return result


def _as_trade_rows(trade_rows) -> list[sr.TradeRow]:
    out = []
    for t, ta in trade_rows:
        if ta is None:
            continue
        out.append(sr.TradeRow(
            net_pnl=t.net_pnl, gross_pnl=t.gross_pnl, fees=t.fees, funding=t.funding,
            slippage=t.slippage_cost, holding_seconds=t.holding_seconds,
            mfe_r=ta.mfe_r, mae_r=ta.mae_r, quality_class=ta.trade_quality_class,
            episode_id=ta.regime_episode_id, closed_at=t.closed_at.timestamp(),
        ))
    return out


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Phase 3: fitness_forward_performance
# --------------------------------------------------------------------------- #
async def refresh_fitness_forward(
    db: AsyncSession, *, grid_minutes: int = 60, computation_version: str = COMPUTATION_VERSION,
) -> RefreshResult:
    """For every recorded FitnessScore snapshot (plus an hourly reconstruction
    grid where snapshots are missing) x every horizon: write the forward window.
    Write-once: rows that exist are never re-inserted or updated."""
    from app.models.correlation import AgentCorrelation
    from app.models.regime_validation import RegimeValidationReport
    from app.models.adversarial import AdversarialTestReport

    result = RefreshResult()
    now = datetime.now(timezone.utc)

    existing = {
        (row[0], row[1].replace(tzinfo=timezone.utc) if row[1].tzinfo is None else row[1], row[2])
        for row in (await db.execute(
            select(FitnessForwardPerformance.agent_id, FitnessForwardPerformance.as_of, FitnessForwardPerformance.horizon_minutes)
        )).all()
    }

    agents = (await db.execute(select(Agent))).scalars().all()
    trades = (await db.execute(select(Trade).order_by(Trade.agent_id, Trade.closed_at))).scalars().all()
    by_agent: dict[uuid.UUID, list[ff.TradePoint]] = {}
    for t in trades:
        by_agent.setdefault(t.agent_id, []).append(
            ff.TradePoint(closed_at=t.closed_at, net_pnl=t.net_pnl,
                          notional=t.quantity * t.entry_price, opened_at=t.opened_at)
        )

    # generation rollover boundaries: the created_at of the NEXT generation
    from app.models.strategy import Generation

    generations = (await db.execute(
        select(Generation.number, Generation.created_at).order_by(Generation.number)
    )).all()
    ordered = [(number, created) for number, created in generations]
    next_gen_created: dict[int, datetime] = {}
    for i, (number, _created) in enumerate(ordered):
        if i + 1 < len(ordered):
            next_gen_created[number] = ordered[i + 1][1]
    data_end = max((t.closed_at for t in trades), default=now)

    # recorded weights (uniform in practice); reconstruction uses the latest recorded weights
    snap_rows = (await db.execute(
        select(FitnessScore).order_by(FitnessScore.as_of)
    )).scalars().all()
    latest_weights_used = snap_rows[-1].weights_used if snap_rows else None
    weights = ff.weights_from_recorded(latest_weights_used)

    # stage evidence per version, time-filterable
    backtest_rows = (await db.execute(
        select(StageMetrics).where(StageMetrics.stage == StrategyStage.BACKTEST).order_by(StageMetrics.computed_at)
    )).scalars().all()
    wfo_rows = (await db.execute(
        select(StageMetrics).where(StageMetrics.stage == StrategyStage.WALK_FORWARD).order_by(StageMetrics.computed_at)
    )).scalars().all()
    regime_rows = (await db.execute(
        select(RegimeValidationReport).order_by(RegimeValidationReport.computed_at)
    )).scalars().all()
    adversarial_rows = (await db.execute(
        select(AdversarialTestReport).order_by(AdversarialTestReport.computed_at)
    )).scalars().all()
    corr_rows = (await db.execute(select(AgentCorrelation).order_by(AgentCorrelation.computed_at))).scalars().all()

    def _latest_upto(rows, version_id, t):
        latest = None
        for r in rows:
            if r.strategy_version_id == version_id and r.computed_at <= t:
                latest = r
        return latest

    def _corr_upto(agent_id, t):
        vals = []
        for r in corr_rows:
            if r.computed_at <= t and agent_id in (r.agent_id_a, r.agent_id_b):
                vals.append(r.composite_correlation)
        return (sum(vals) / len(vals)) if vals else None

    def _stage_evidence_upto(agent, t) -> dict:
        bt = _latest_upto(backtest_rows, agent.strategy_version_id, t) if agent.strategy_version_id else None
        wfo = _latest_upto(wfo_rows, agent.strategy_version_id, t) if agent.strategy_version_id else None
        regime = _latest_upto(regime_rows, agent.strategy_version_id, t) if agent.strategy_version_id else None
        adversarial = _latest_upto(adversarial_rows, agent.strategy_version_id, t) if agent.strategy_version_id else None
        return {
            "oos_score": bt.oos_score if bt is not None else None,
            "walk_forward_consistency": wfo.walk_forward_consistency if wfo is not None else None,
            "regime_classification": regime.classification if regime is not None else None,
            "adversarial_robustness": adversarial.robustness_score if adversarial is not None else None,
            "mean_pairwise_correlation": _corr_upto(agent.id, t),
        }

    recorded: dict[uuid.UUID, list[FitnessScore]] = {}
    for s in snap_rows:
        recorded.setdefault(s.agent_id, []).append(s)

    gen_first_trade_by_gen: dict[int, datetime] = {}
    for a in agents:
        pts = by_agent.get(a.id, [])
        if pts:
            first = min(p.closed_at for p in pts)
            gen_first_trade_by_gen[a.generation] = min(
                gen_first_trade_by_gen.get(a.generation, first), first
            )

    inserted = 0
    for agent in agents:
        points = by_agent.get(agent.id, [])
        if not points:
            continue
        facts = ff.AgentFacts(
            agent_id=agent.id, generation=agent.generation, starting_balance=agent.starting_balance,
            created_at=agent.created_at, death_timestamp=agent.death_timestamp, status=agent.status,
        )
        rollover = next_gen_created.get(agent.generation)

        # snapshot list: recorded + a reconstruction grid from first trade to the
        # rollover/data end (bounded, hourly)
        snapshots: list[tuple[datetime, float, dict, str]] = []
        for s in recorded.get(agent.id, []):
            as_of = s.as_of if s.as_of.tzinfo else s.as_of.replace(tzinfo=timezone.utc)
            snapshots.append((as_of, s.fitness, _components_of(s), "recorded"))
        # population-level reconstruction grid: anchored at the GENERATION's first
        # trade (not per-agent) so every cohort at a given T covers the whole
        # population that had traded by then — the cohort statistics need that.
        gen_first_trade = min((p.closed_at for p in by_agent.get(agent.id, [])), default=None)
        if gen_first_trade is None:
            gen_first_trade = gen_first_trade_by_gen.get(agent.generation)
        else:
            gen_first_trade_by_gen.setdefault(agent.generation, gen_first_trade)
            gen_first_trade = gen_first_trade_by_gen[agent.generation]
        boundary = min(t for t in (rollover, data_end) if t is not None) if (rollover or data_end) else data_end
        if gen_first_trade is not None and gen_first_trade < boundary:
            span_minutes = (boundary - gen_first_trade).total_seconds() / 60.0
            steps = max(1, int(span_minutes // grid_minutes))
            for i in range(1, steps + 1):
                t_point = gen_first_trade + timedelta(minutes=grid_minutes * i)
                if t_point >= boundary:
                    break
                if not any(p.closed_at <= t_point for p in points):
                    continue          # this agent had no evidence at T: nothing to reconstruct
                recon = ff.reconstruct_fitness_at(
                    facts, points, as_of=t_point, weights=weights,
                    stage_evidence=_stage_evidence_upto(agent, t_point),
                )
                snapshots.append((t_point, recon.fitness, recon.components, "reconstructed"))

        for as_of, fitness_at_t, components, source in snapshots:
            for horizon in ff.HORIZONS_MINUTES:
                if (agent.id, as_of, horizon) in existing:
                    result.ffp_existing += 1
                    continue
                window = ff.forward_window(
                    as_of, horizon, death_at=agent.death_timestamp,
                    generation_rollover_at=rollover, data_end=data_end,
                )
                fwd = ff.forward_performance(points, window, starting_balance=facts.starting_balance)
                db.add(FitnessForwardPerformance(
                    agent_id=agent.id, snapshot_source=source, as_of=as_of,
                    fitness_at_t=fitness_at_t, fitness_components_at_t=components,
                    horizon_minutes=horizon, window_start=window.window_start,
                    window_end_planned=window.window_end_planned, window_end_actual=window.window_end_actual,
                    censor_reason=window.censor_reason, window_coverage=window.window_coverage,
                    future_trade_count=fwd.trade_count, future_net_pnl=fwd.net_pnl,
                    future_net_bps=fwd.net_bps, future_expectancy=fwd.expectancy,
                    future_win_rate=fwd.win_rate, future_max_drawdown_currency=fwd.max_drawdown_currency,
                    computation_version=computation_version, computed_at=now,
                ))
                inserted += 1
                existing.add((agent.id, as_of, horizon))
    result.ffp_inserted = inserted
    await db.flush()
    return result


def _components_of(s: FitnessScore) -> dict:
    return {
        "return_score": s.return_score, "risk_score": s.risk_score, "consistency_score": s.consistency_score,
        "robustness_score": s.robustness_score, "oos_score": s.oos_score, "drawdown_penalty": s.drawdown_penalty,
        "instability_penalty": s.instability_penalty, "correlation_penalty": s.correlation_penalty,
        "expectancy_score": s.expectancy_score, "regime_score": s.regime_score, "adversarial_score": s.adversarial_score,
    }