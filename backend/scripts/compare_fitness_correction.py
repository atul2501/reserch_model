"""READ-ONLY before/after comparison for the lockbox.py compute_oos_score fix
(confidence-scaling by the scored slice's own trade count).

The fix lives upstream of persistence: StageMetrics.oos_score in the DB was
already computed by the OLD formula whenever the research pipeline last ran,
so it can't be corrected retroactively without re-running the validation
backtest. This script does exactly that, for a sample of the current
generation's strategy versions, against the SAME candles/epoch boundaries
the real pipeline used -- so the comparison is real, not synthetic.

Never writes to the DB. Point it at a *snapshot copy* of trading_lab.db:

    python -m scripts.compare_fitness_correction /path/to/snapshot/trading_lab.db [--sample 30]
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.backtesting.data import prepare_backtest_data
from app.models.agent import Agent
from app.models.research import ResearchEpoch
from app.models.strategy import StrategyVersion
from app.research import dataset as ds
from app.research.evaluation import evaluate_in_sample
from app.research.lockbox import FULL_CONFIDENCE_TRADES, _clip
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import dna_indicator_specs


def _old_compute_oos_score(result, *, min_trades: int) -> float:
    """The formula exactly as it stood before the confidence-scaling fix."""
    if len(result.trades) < min_trades:
        return 0.0
    pf = result.profit_factor
    pf = 3.0 if pf is None and result.net_return_pct > 0 else (1.0 if pf is None else min(pf, 3.0))
    return 0.4 * _clip(pf - 1.0) + 0.3 * _clip(1.0 - result.max_drawdown_pct / 0.30) + 0.3 * _clip(result.net_return_pct / 0.05)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_path")
    parser.add_argument("--sample", type=int, default=30)
    args = parser.parse_args()

    engine = create_async_engine(f"sqlite+aiosqlite:///{args.snapshot_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        epoch = (await db.execute(select(ResearchEpoch).order_by(ResearchEpoch.created_at.desc()))).scalars().first()
        if epoch is None:
            print("no ResearchEpoch found in this snapshot -- nothing to evaluate")
            return
        full_candles = await ds.load_epoch_candles(db, epoch)
        frame = ds.slice_train_validation(full_candles, epoch)

        latest_gen = (await db.execute(select(func.max(Agent.generation)))).scalar_one()
        version_ids = list({
            a.strategy_version_id for a in
            (await db.execute(select(Agent).where(Agent.generation == latest_gen))).scalars().all()
        })[: args.sample]
        versions = {
            v.id: v for v in
            (await db.execute(select(StrategyVersion).where(StrategyVersion.id.in_(version_ids)))).scalars().all()
        }

        print(f"epoch {epoch.epoch_id}: {len(frame)} train+validation candles "
              f"(train_end_ms={epoch.train_end_ms}, validation_end_ms={epoch.validation_end_ms})")
        print(f"generation {latest_gen}: evaluating {len(versions)} sampled strategy versions\n")

        rows = []
        for vid, version in versions.items():
            dna = StrategyDNA.model_validate(version.dna)
            try:
                data = prepare_backtest_data(frame, symbol=epoch.symbol, timeframe=epoch.timeframe, specs=dna_indicator_specs(dna))
                ev = evaluate_in_sample(vid, dna, frame, data, epoch)
            except Exception as exc:  # noqa: BLE001 - report and skip, don't let one bad DNA kill the sample
                print(f"  {vid}: SKIPPED ({exc!r})")
                continue
            old_score = _old_compute_oos_score(ev.validation, min_trades=1)
            new_score = ev.validation_score
            n_trades = len(ev.validation.trades)
            rows.append((str(vid)[:8], n_trades, old_score, new_score))
    await engine.dispose()

    if not rows:
        print("no versions evaluated")
        return

    print(f"{'version':10s} {'val_trades':>10s} {'old_score':>10s} {'new_score':>10s} {'delta':>8s}")
    for vid, n, old, new in sorted(rows, key=lambda r: r[2] - r[3], reverse=True):
        print(f"{vid:10s} {n:>10d} {old:>10.4f} {new:>10.4f} {new - old:>+8.4f}")

    deltas = [new - old for _, _, old, new in rows]
    below_threshold = sum(1 for _, n, _, _ in rows if n < FULL_CONFIDENCE_TRADES)
    print(f"\n{len(rows)} versions evaluated; {below_threshold} below the "
          f"{FULL_CONFIDENCE_TRADES}-trade full-confidence threshold on their validation slice")
    print(f"mean delta (new - old): {sum(deltas) / len(deltas):+.4f}")
    print(f"max reduction: {min(deltas):+.4f}   max increase: {max(deltas):+.4f}")
    unaffected = sum(1 for d in deltas if abs(d) < 1e-9)
    print(f"unaffected (>= {FULL_CONFIDENCE_TRADES} validation trades): {unaffected}/{len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
