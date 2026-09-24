"""Scheduled research/evolution pipeline (spec phases 22-30, 32).

    Population -> Evaluation -> Fitness -> Correlation -> Regime robustness ->
    Adversarial testing -> Selection -> Mutation/Crossover -> Candidate
    validation -> New generation (+ immutable snapshots, evolution events)

Runs as its own process (`scripts/run_research.py`, own worker lease) so heavy
backtesting never competes with the 1-minute trading cycle. It refuses to run
unless (a) evolution is enabled, (b) the configured interval elapsed,
(c) the current generation is old enough and has enough real paper history,
(d) enough confirmed market data exists. Every skip is recorded as an
experiment with its reason.

Data protection: evaluation, fitness and selection only ever see the
train+validation frame. The final OOS slice is opened solely by
`lockbox.evaluate_oos_once`, and only for survivors nominated for promotion.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lifecycle import create_generation, retire_generation
from app.analytics.fitness_service import compute_and_persist_agent_fitness
from app.backtesting.data import BacktestData, extend_with_specs, prepare_backtest_data
from app.backtesting.engine import run_backtest
from app.backtesting.regime_validation_engine import run_and_persist_regime_validation
from app.backtesting.reality_gap_engine import compute_full_reality_gap_chain, persist_reality_gap_report
from app.backtesting.stage_metrics_service import compute_live_stage_metrics
from app.core.config import get_settings
from app.core.logging import get_logger
from app.evolution.adversarial_service import run_and_persist_adversarial_suite
from app.evolution.breeding import NoValidCandidatesError
from app.evolution.rng import derive_seed
from app.evolution.breeding import select_and_breed_next_generation
from app.evolution.champion_challenger_service import advance_pipeline_stage
from app.evolution.correlation_service import (
    apply_diversity_pressure, compute_generation_correlation_report, persist_generation_correlation,
)
from app.market.feature_engine import InsufficientDataError
from app.models.agent import Agent
from app.models.enums import AgentStatus, StrategyStage
from app.models.research import Experiment
from app.models.strategy import Generation, StrategyVersion
from app.models.trading import Trade
from app.research import dataset as ds
from app.research.evaluation import evaluate_in_sample
from app.research.lockbox import OosAlreadyConsumedError, evaluate_oos_once
from app.research.registry import finish_experiment, register_experiment
from app.research.snapshots import create_agent_snapshot
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import dna_indicator_specs, population_indicator_specs
from app.strategies.factory import generate_population_dna

logger = get_logger(__name__)


@dataclass
class ResearchReport:
    status: str                      # COMPLETED | SKIPPED | FAILED
    reason: str | None = None
    experiment_id: str | None = None
    epoch_id: str | None = None
    generation_from: int | None = None
    generation_to: int | None = None
    counts: dict = field(default_factory=dict)


async def _record_skip(db: AsyncSession, reason: str, generation: int | None) -> ResearchReport:
    s = get_settings()
    exp = await register_experiment(
        db, kind="evolution", seed=s.research_seed, parameters={"skipped": True}, generation=generation, status="SKIPPED"
    )
    await finish_experiment(db, exp, status="SKIPPED", result={"reason": reason})
    await db.commit()
    logger.info("research.skipped", reason=reason, generation=generation)
    return ResearchReport("SKIPPED", reason=reason, experiment_id=exp.experiment_id, generation_from=generation)


async def evaluate_gates(db: AsyncSession, *, force: bool = False, now: datetime | None = None) -> tuple[bool, str | None, Generation | None]:
    """Schedule + readiness gates. Returns (run?, reason_if_not, latest_generation)."""
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not s.evolution_enabled and not force:
        return False, "evolution_disabled", None
    generation = (await db.execute(select(Generation).order_by(Generation.number.desc()).limit(1))).scalar_one_or_none()
    if generation is None:
        return False, "no_generation", None
    if force:
        return True, None, generation
    last = (
        await db.execute(
            select(Experiment.created_at).where(Experiment.kind == "evolution", Experiment.status == "COMPLETED")
            .order_by(Experiment.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if last is not None and now - last < timedelta(hours=s.evolution_interval_hours):
        return False, "interval_not_elapsed", generation
    if now - generation.created_at < timedelta(hours=s.research_min_generation_age_hours):
        return False, "generation_too_young", generation
    closed = (
        await db.execute(
            select(func.count()).select_from(Trade).join(Agent, Agent.id == Trade.agent_id)
            .where(Agent.generation == generation.number)
        )
    ).scalar_one()
    if closed < s.research_min_closed_trades:
        return False, f"insufficient_paper_history ({closed} < {s.research_min_closed_trades} closed trades)", generation
    return True, None, generation


def _make_validator(frame: pd.DataFrame, data: BacktestData, epoch, settings):
    """Candidate validation: a child must survive an in-sample (TRAIN slice)
    backtest through the real Risk Engine before it is allowed to exist."""
    train_end = int((frame["open_time"] > epoch.train_end_ms).idxmax()) if (frame["open_time"] > epoch.train_end_ms).any() else len(frame)

    def validate(dna: StrategyDNA) -> tuple[bool, dict]:
        try:
            extend_with_specs(data, dna_indicator_specs(dna))
            r = run_backtest(
                frame, dna, symbol=epoch.symbol, timeframe=epoch.timeframe, starting_equity=settings.agent_starting_balance,
                fee_rate=settings.paper_fee_rate, slippage_bps=settings.paper_slippage_bps, enforce_risk_engine=True,
                global_max_leverage=settings.max_leverage, global_max_position_size=settings.max_position_size,
                global_max_drawdown=settings.max_drawdown, global_max_daily_loss=settings.max_daily_loss,
                data=data, end_index=train_end,
            )
        except InsufficientDataError as exc:
            return False, {"error": str(exc)}
        ok = len(r.trades) >= settings.research_candidate_min_trades and r.max_drawdown_pct <= settings.research_candidate_max_drawdown and not r.dead
        return ok, {"trades": len(r.trades), "max_drawdown_pct": round(r.max_drawdown_pct, 4), "net_return_pct": round(r.net_return_pct, 4)}

    return validate


async def run_research_cycle(
    db: AsyncSession, *, market_service=None, force: bool = False, now: datetime | None = None,
) -> ResearchReport:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    ok, reason, generation = await evaluate_gates(db, force=force, now=now)
    if not ok:
        if reason in ("evolution_disabled", "no_generation"):
            return ResearchReport("SKIPPED", reason=reason)
        return await _record_skip(db, reason or "gate", generation.number if generation else None)
    assert generation is not None
    symbol, timeframe = s.market_symbol, s.market_timeframe

    # ---- data readiness ----------------------------------------------------- #
    have = await ds.count_confirmed_candles(db, symbol, timeframe)
    if have < s.research_min_candles and market_service is not None:
        interval_ms = market_service.interval_ms
        end_ms = int(now.timestamp() * 1000)
        try:
            await market_service.backfill_history(db, end_ms - interval_ms * s.research_window_candles, end_ms)
        except Exception as exc:
            logger.warning("research.backfill_failed", error=str(exc))
        have = await ds.count_confirmed_candles(db, symbol, timeframe)
    if have < s.research_min_candles:
        return await _record_skip(db, f"insufficient_market_data ({have} < {s.research_min_candles} candles)", generation.number)

    # FROZEN HOLDOUT: the active sealed epoch fixes the OOS range, its fingerprint and the train/validation boundaries.
    # New candles never move it; only an explicit operator renewal (scripts.run_research --new-oos-epoch) replaces it.
    epoch = await ds.get_active_epoch(db, symbol, timeframe)
    if epoch is None:
        recent = await ds.load_confirmed_candles(db, symbol, timeframe, limit=s.research_window_candles)
        epoch = await ds.seal_epoch(db, recent, symbol=symbol, timeframe=timeframe, reason="initial")
        logger.warning("research.oos_epoch_sealed", epoch_id=epoch.epoch_id, oos_start_ms=epoch.oos_start_ms,
                       oos_end_ms=epoch.oos_end_ms)
    try:
        candles = await ds.load_epoch_candles(db, epoch)
    except ds.EpochIntegrityError as exc:
        await db.rollback()
        return await _record_skip(db, f"epoch_integrity_error ({exc})", generation.number)
    epoch_age_days = (now.timestamp() * 1000 - epoch.oos_end_ms) / 86_400_000
    if epoch_age_days > s.research_epoch_max_age_days:
        logger.warning("research.oos_epoch_is_old_consider_renewing", epoch_id=epoch.epoch_id, age_days=round(epoch_age_days, 1))
    exp = await register_experiment(
        db, kind="evolution", seed=derive_seed(s.research_seed, epoch.epoch_id, generation.number), epoch=epoch,
        generation=generation.number,
        parameters={"window_candles": len(candles), "survivor_fraction": s.research_survivor_fraction,
                    "adversarial_top_k": s.research_adversarial_top_k, "forced": force},
    )
    await db.commit()

    try:
        report = await _run(db, s, exp, epoch, generation, candles, market_service, now)
        await finish_experiment(db, exp, status="COMPLETED", result=report.counts)
        await db.commit()
        return report
    except Exception as exc:
        await db.rollback()
        exp = await db.get(Experiment, exp.id) or exp
        await finish_experiment(db, exp, status="FAILED", result={"error": f"{type(exc).__name__}: {exc}"})
        await db.commit()
        logger.exception("research.failed")
        return ResearchReport("FAILED", reason=str(exc), experiment_id=exp.experiment_id, epoch_id=epoch.epoch_id,
                              generation_from=generation.number)


async def _run(db, s, exp, epoch, generation, candles, market_service, now) -> ResearchReport:
    counts: dict = {}
    rng = random.Random(exp.random_seed)
    gen_no = generation.number

    # OOS protection: evolution only ever sees train+validation.
    frame = ds.slice_train_validation(candles, epoch)
    funding = await ds.load_funding(db, epoch.symbol, epoch.start_ms, epoch.end_ms)

    agents = (await db.execute(select(Agent).where(Agent.generation == gen_no))).scalars().all()
    versions = {
        v.id: v
        for v in (await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_({a.strategy_version_id for a in agents})))).scalars().all()
    }
    dnas = {vid: StrategyDNA.model_validate(v.dna) for vid, v in versions.items()}
    specs = population_indicator_specs(dnas.values())
    data = await asyncio.to_thread(prepare_backtest_data, frame, symbol=epoch.symbol, timeframe=epoch.timeframe, specs=specs, funding=funding)

    # ---- 1. in-sample evaluation (BACKTEST + WALK_FORWARD + regime) ------------ #
    evaluated = 0
    for vid, dna in dnas.items():
        try:
            ev = await asyncio.to_thread(evaluate_in_sample, vid, dna, frame, data, epoch)
        except InsufficientDataError:
            continue
        db.add(ev.backtest_metrics)
        if ev.wfo_metrics is not None:
            db.add(ev.wfo_metrics)
        await run_and_persist_regime_validation(
            db, vid, backtest_result=[ev.train, ev.validation],   # train AND validation, bucketed by ENTRY regime
            min_trades_per_regime=s.regime_validation_min_trades_per_regime,
            robust_min_positive_regimes_pct=s.regime_validation_robust_min_positive_regimes_pct,
            specialist_min_pnl_share=s.regime_validation_specialist_min_pnl_share,
        )
        evaluated += 1
    await db.commit()
    counts["versions_evaluated"] = evaluated

    # ---- 2. correlation (diversity pressure) ------------------------------- #
    pressure = None
    correlation_by_agent: dict = {}
    if s.correlation_diversity_pressure_enabled:
        creport = await compute_generation_correlation_report(
            db, generation=gen_no, bucket=s.correlation_time_bucket, lookback_days=s.correlation_lookback_days,
            max_strategy_correlation=s.max_strategy_correlation,
        )
        await persist_generation_correlation(db, creport)
        pressure = await apply_diversity_pressure(
            db, report=creport, max_strategy_correlation=s.max_strategy_correlation, min_strategy_diversity=s.min_strategy_diversity,
        )
        correlation_by_agent = creport.agent_mean_correlation
        counts["mean_pairwise_correlation"] = round(creport.mean_pairwise_correlation, 4)
        await db.commit()

    # ---- 3. preliminary fitness -> adversarial on the top-K -> final fitness ----- #
    await compute_and_persist_agent_fitness(db, generation=gen_no, correlation_by_agent=correlation_by_agent,
                                            oos_window_ms=(epoch.oos_start_ms, epoch.oos_end_ms))
    await db.commit()
    ranked = sorted((a for a in agents if a.status == AgentStatus.ACTIVE), key=lambda a: a.fitness or -1e9, reverse=True)
    top_versions = list(dict.fromkeys(a.strategy_version_id for a in ranked))[: s.research_adversarial_top_k]
    adv_frame = frame.iloc[-min(len(frame), s.research_adversarial_bars):].reset_index(drop=True)
    adv_done = 0
    for vid in top_versions:
        try:
            report = await _adversarial(db, s, vid, adv_frame, epoch, exp.experiment_id, funding)
            adv_done += 1 if report else 0
        except InsufficientDataError:
            continue
    await db.commit()
    counts["adversarial_suites"] = adv_done
    await compute_and_persist_agent_fitness(db, generation=gen_no, correlation_by_agent=correlation_by_agent,
                                            oos_window_ms=(epoch.oos_start_ms, epoch.oos_end_ms))
    await db.commit()

    # ---- 4. nominate the top-K for promotion: PAPER metrics, final OOS (once), pipeline ---- #
    ranked = sorted((a for a in agents if a.status == AgentStatus.ACTIVE), key=lambda a: a.fitness or -1e9, reverse=True)
    nominees = list(dict.fromkeys(a.strategy_version_id for a in ranked))[: s.research_adversarial_top_k]
    oos_consumed = advanced = 0
    for vid in nominees:
        version = versions[vid]
        try:
            await evaluate_oos_once(db, version, epoch, candles, funding=funding, seed=exp.random_seed)
            oos_consumed += 1
        except OosAlreadyConsumedError:
            pass
        except InsufficientDataError:
            pass
        for live_stage in (StrategyStage.PAPER, StrategyStage.SHADOW):
            stage_metrics = await compute_live_stage_metrics(db, strategy_version_id=vid, stage=live_stage)
            # PAPER always (evidence gate); SHADOW only when shadow mode actually produced trades.
            if live_stage == StrategyStage.PAPER or stage_metrics.trade_count > 0:
                db.add(stage_metrics)
        await db.flush()
        chain = await compute_full_reality_gap_chain(db, vid)
        if chain.transitions:
            await persist_reality_gap_report(db, chain)
        for _ in range(6):  # walk the pipeline as far as evidence allows this cycle
            row = await advance_pipeline_stage(db, vid, promotion_stage=StrategyStage.PAPER)
            await db.flush()
            if row.blocking_reasons or row.pipeline_stage in ("promoted", "rejected"):
                break
            advanced += 1
        await db.commit()
    counts["oos_consumed"] = oos_consumed
    counts["pipeline_advances"] = advanced

    # ---- 5. selection -> mutation/crossover -> candidate validation -> new generation -- #
    alive = [a for a in agents if a.status != AgentStatus.DEAD]
    survivor_count = max(1, int(len(agents) * s.research_survivor_fraction))
    counts["alive_agents"] = len(alive)
    validator = _make_validator(frame, data, epoch, s)
    if alive:
        result = await select_and_breed_next_generation(
            db, generation_number=gen_no, survivor_count=min(survivor_count, len(alive)), next_generation_size=s.agent_count,
            rng=rng, preserve_family_codes=pressure.preserve_family_codes if pressure else None,
            mutation_rate_multiplier=pressure.mutation_rate_multiplier if pressure else 1.0,
            max_family_survivor_fraction=s.max_family_survivor_fraction, candidate_validator=validator,
            max_validation_attempts=s.research_max_child_attempts, experiment_id=exp.experiment_id,
            elite_slots=s.champion_elite_slots,
        )
        new_ids = result.strategy_version_ids
        counts.update(children=len(new_ids) - len(result.elite_version_ids), elites_carried=len(result.elite_version_ids),
                      validation_rejected=result.validation_rejected_count, dropped_candidates=result.dropped_candidates,
                      injected_fresh=result.injected_fresh_count, diversity_score=round(result.diversity_score, 4))
    else:  # extinction: restart from fresh, validated founders (never revive the dead)
        new_ids = await _spawn_founders(db, s, gen_no + 1, rng, exp.experiment_id, validator)
        counts.update(children=len(new_ids), extinction_restart=True)

    # ---- 6. freeze the finished generation, then start the next ------------------ #
    for agent in ranked[: s.research_adversarial_top_k * 2]:
        await create_agent_snapshot(db, agent, versions[agent.strategy_version_id], experiment_id=exp.experiment_id,
                                    dataset_fingerprint=epoch.dataset_fingerprint)
    last_close = float(candles["close"].iloc[-1])
    counts["retired"] = await retire_generation(db, gen_no, mark_price=last_close, at=now, fee_rate=s.paper_fee_rate)
    new_gen = await create_generation(
        db, generation_number=gen_no + 1, strategy_version_ids=new_ids, starting_balance=s.agent_starting_balance,
        triggered_by=f"research:{exp.experiment_id}",
    )
    return ResearchReport("COMPLETED", experiment_id=exp.experiment_id, epoch_id=epoch.epoch_id,
                          generation_from=gen_no, generation_to=new_gen.number, counts=counts)


async def _adversarial(db, s, version_id, frame, epoch, experiment_id=None, funding=None):
    return await run_and_persist_adversarial_suite(
        db, version_id, frame, symbol=epoch.symbol, timeframe=epoch.timeframe, starting_equity=s.agent_starting_balance,
        base_fee_rate=s.paper_fee_rate, base_slippage_bps=s.paper_slippage_bps, n_dna_variants=s.adversarial_n_dna_variants,
        global_max_leverage=s.max_leverage, global_max_position_size=s.max_position_size,
        global_max_drawdown=s.max_drawdown, global_max_daily_loss=s.max_daily_loss,
        experiment_id=experiment_id, funding=funding,
    )


FOUNDER_ATTEMPTS_PER_SLOT = 5   # candidate founders generated per population slot before giving up on the slot


async def _spawn_founders(db, s, generation_number, rng, experiment_id, validator) -> list:
    """Extinction restart: fresh founders, each through the SAME gate as bred children (schema + in-sample validator).
    A founder that fails is replaced (bounded attempts) and never inserted; if none pass, nothing is born."""
    from app.evolution.breeding import check_candidate_schema
    from app.models.strategy import Strategy

    def gate(dna: StrategyDNA) -> bool:
        if check_candidate_schema(dna):
            return False
        return True if validator is None else bool(validator(dna)[0])

    def make_valid() -> list[StrategyDNA]:
        accepted: list[StrategyDNA] = []
        budget = s.agent_count * FOUNDER_ATTEMPTS_PER_SLOT
        while len(accepted) < s.agent_count and budget > 0:
            batch = generate_population_dna(min(s.agent_count, budget), seed=rng.randint(0, 2**31 - 1))
            for dna in batch:
                budget -= 1
                if gate(dna):
                    accepted.append(dna)
                    if len(accepted) >= s.agent_count:
                        break
        return accepted

    accepted = await asyncio.to_thread(make_valid)   # a backtest per founder: never on the event loop
    if not accepted:
        raise NoValidCandidatesError("no extinction-restart founder passed the validation gate")
    ids: list = []
    for dna in accepted:
        strat = Strategy(code=f"STRAT-{dna.strategy_family.value.upper()}-GEN{generation_number:02d}-{len(ids):05d}-{rng.getrandbits(16):04x}",
                         family=dna.strategy_family, name="founder")
        db.add(strat)
        await db.flush()
        strat.lineage_id = strat.id
        v = StrategyVersion(strategy_id=strat.id, version=1, generation=generation_number, dna=dna.model_dump(mode="json"),
                            stage=StrategyStage.PAPER, stage_entered_at=datetime.now(timezone.utc), experiment_id=experiment_id,
                            proposed_by="system")
        db.add(v)
        await db.flush()
        ids.append(v.id)
    return ids
