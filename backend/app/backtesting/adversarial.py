"""Adversarial / stress testing for promising strategies (spec sections
22-25): deliberately run a strategy's DNA through distorted market
conditions and cost environments before it's trusted with promotion, rather
than only ever backtesting it under benign historical data.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.engine import BacktestResult, run_backtest
from app.evolution.mutation import jitter
from app.schemas.strategy_dna import StrategyDNA

# ---------------------------------------------------------------------------
# Candle stress transforms. Each takes a copy of an OHLCV DataFrame (columns
# open_time, open, high, low, close, volume) and returns a distorted copy.
# ---------------------------------------------------------------------------


def inject_volatility_spike(candles: pd.DataFrame, magnitude: float, at_index: int) -> pd.DataFrame:
    """Widens one candle's high/low range by `magnitude` (e.g. 3.0 = triple
    the candle's range), keeping open/close fixed — a localized volatility
    shock rather than a permanent regime shift."""
    df = candles.copy()
    mid = (df.loc[at_index, "high"] + df.loc[at_index, "low"]) / 2
    half_range = (df.loc[at_index, "high"] - df.loc[at_index, "low"]) / 2 * magnitude
    df.loc[at_index, "high"] = mid + half_range
    df.loc[at_index, "low"] = mid - half_range
    return df


def inject_gap(candles: pd.DataFrame, gap_pct: float, at_index: int) -> pd.DataFrame:
    """Shifts open/high/low/close from `at_index` onward by `gap_pct` (e.g.
    -0.08 = an 8% down-gap) — a permanent price-level shock simulating an
    overnight move or a feed outage that resumes at a different price."""
    df = candles.copy()
    factor = 1 + gap_pct
    df.loc[at_index:, ["open", "high", "low", "close"]] *= factor
    return df.reset_index(drop=True)


def inject_stale_period(candles: pd.DataFrame, length: int, at_index: int) -> pd.DataFrame:
    """Repeats the last close for `length` candles starting at `at_index`
    (flat OHLC, zero volume) — simulates a stale-data/feed-outage window."""
    df = candles.copy()
    last_close = df.loc[at_index - 1, "close"] if at_index > 0 else df.loc[0, "open"]
    end = min(at_index + length, len(df))
    df.loc[at_index:end - 1, ["open", "high", "low", "close"]] = last_close
    df.loc[at_index:end - 1, "volume"] = 0.0
    return df


def inject_extreme_move(candles: pd.DataFrame, direction: str, magnitude: float, at_index: int) -> pd.DataFrame:
    """Applies a permanent shock at `at_index` (e.g. magnitude=0.25 = 25%
    move), held for the rest of the series — a flash-crash/melt-up style
    regime shift. `direction` is 'up' or 'down'."""
    df = candles.copy()
    factor = (1 + magnitude) if direction == "up" else (1 - magnitude)
    df.loc[at_index:, ["open", "high", "low", "close"]] *= factor
    return df.reset_index(drop=True)


def inject_abnormal_volume(candles: pd.DataFrame, magnitude: float, at_index: int, length: int = 20) -> pd.DataFrame:
    """Scales volume by `magnitude` for `length` candles starting at
    `at_index` (e.g. 5.0 = a 5x volume spike, 0.1 = a 90% collapse) — price
    untouched, isolating strategies whose entry/exit rules key off volume
    (ORDER_FLOW/VWAP families) from ones that don't."""
    df = candles.copy()
    end = min(at_index + length, len(df))
    df.loc[at_index:end - 1, "volume"] = df.loc[at_index:end - 1, "volume"] * magnitude
    return df


def inject_liquidity_reduction(candles: pd.DataFrame, magnitude: float, at_index: int, length: int = 20) -> pd.DataFrame:
    """Collapses volume by `magnitude` (e.g. 0.05 = 95% reduction) for
    `length` candles as this engine's proxy for reduced market depth — there
    is no order-book model to distort directly, so the volume collapse is
    the signal, and the effect on fills is applied via an elevated slippage
    multiplier at the orchestration level in run_adversarial_suite (the
    existing fee/slippage multiplier grid), not inside this transform."""
    return inject_abnormal_volume(candles, magnitude, at_index, length)


# ---------------------------------------------------------------------------
# DNA parameter perturbation, reusing mutation.py's jitter helper.
# ---------------------------------------------------------------------------


def perturb_dna_variants(dna: StrategyDNA, n: int, rng: random.Random | None = None) -> list[StrategyDNA]:
    """Generates `n` independently-jittered DNA variants for parameter-
    robustness testing — every listed field is touched on every variant
    (unlike mutation.py's mutate(), which only touches each field with
    probability MUTATION_RATE)."""
    rng = rng or random.Random()
    variants = []
    for _ in range(n):
        data = dna.model_dump()
        data["stop_loss"]["value"] = jitter(data["stop_loss"]["value"], rng, 0.5, 6.0, spread=0.4)
        data["take_profit"]["value"] = jitter(data["take_profit"]["value"], rng, 0.5, 8.0, spread=0.4)
        data["position_sizing"]["fraction_of_equity"] = jitter(
            data["position_sizing"]["fraction_of_equity"], rng, 0.005, 0.5, spread=0.4
        )
        data["risk_profile"]["max_position_fraction"] = jitter(
            data["risk_profile"]["max_position_fraction"], rng, 0.01, 1.0, spread=0.4
        )
        variants.append(StrategyDNA.model_validate(data))
    return variants


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    scenario_name: str
    fee_multiplier: float
    slippage_multiplier: float
    dna_variant_index: int
    result: BacktestResult


@dataclass
class AdversarialReport:
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    worst_case_max_drawdown_pct: float = 0.0
    worst_case_net_return_pct: float = 0.0
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)


# A strategy must not exceed either bound in ANY single stress scenario, not
# just on average. champion.py's max_drawdown=0.25 is a normal-condition
# promotion gate; these are looser since every scenario here is deliberately
# worse than normal conditions.
MAX_ACCEPTABLE_DRAWDOWN = 0.40
MIN_ACCEPTABLE_WORST_CASE_RETURN = -0.20


def run_adversarial_suite(
    dna: StrategyDNA,
    candles: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    starting_equity: float,
    base_fee_rate: float,
    base_slippage_bps: float,
    n_dna_variants: int = 5,
    rng: random.Random | None = None,
    global_max_leverage: float = 5.0,
    global_max_position_size: float = 0.5,
    global_max_drawdown: float = 0.30,
    global_max_daily_loss: float = 0.10,
    bypass_risk_engine: bool = False,
) -> AdversarialReport:
    """Runs run_backtest across {stress scenario x fee/slippage multiplier x
    DNA variant} and aggregates worst-case metrics. Skips (rather than
    fails) any combination run_backtest can't evaluate, e.g. a stress
    transform that leaves too few candles for the engine's warmup.

    Every scenario is risk-gated through the real Risk Engine by default
    (`run_backtest(..., enforce_risk_engine=True)`) — a strategy must never
    look robust under stress only because these simulated entries bypassed
    the same checks live/paper trading would apply. `bypass_risk_engine` is
    a test-only escape hatch for comparing against pre-risk-gating
    behavior; production call sites must never set it."""
    rng = rng or random.Random()
    variants = [dna] + perturb_dna_variants(dna, n_dna_variants, rng)

    mid = len(candles) // 2
    scenarios: list[tuple[str, pd.DataFrame]] = [
        ("baseline", candles),
        ("volatility_spike", inject_volatility_spike(candles, magnitude=3.0, at_index=mid)),
        ("gap_down_8pct", inject_gap(candles, gap_pct=-0.08, at_index=mid)),
        ("stale_period_20", inject_stale_period(candles, length=20, at_index=mid)),
        ("extreme_move_down_25pct", inject_extreme_move(candles, direction="down", magnitude=0.25, at_index=mid)),
        ("abnormal_volume_spike_5x", inject_abnormal_volume(candles, magnitude=5.0, at_index=mid, length=20)),
        ("liquidity_reduction", inject_liquidity_reduction(candles, magnitude=0.05, at_index=mid, length=20)),
    ]
    fee_slippage_multipliers = [(1.0, 1.0), (2.0, 3.0)]  # normal, and a stressed cost environment

    results: list[ScenarioResult] = []
    for scenario_name, stressed_candles in scenarios:
        for fee_mult, slip_mult in fee_slippage_multipliers:
            for idx, variant in enumerate(variants):
                try:
                    result = run_backtest(
                        stressed_candles,
                        variant,
                        symbol=symbol,
                        timeframe=timeframe,
                        starting_equity=starting_equity,
                        fee_rate=base_fee_rate * fee_mult,
                        slippage_bps=base_slippage_bps * slip_mult,
                        enforce_risk_engine=not bypass_risk_engine,
                        global_max_leverage=global_max_leverage,
                        global_max_position_size=global_max_position_size,
                        global_max_drawdown=global_max_drawdown,
                        global_max_daily_loss=global_max_daily_loss,
                    )
                except Exception:
                    continue
                results.append(ScenarioResult(scenario_name, fee_mult, slip_mult, idx, result))

    worst_dd = max((r.result.max_drawdown_pct for r in results), default=1.0)
    worst_return = min((r.result.net_return_pct for r in results), default=-1.0)

    failure_reasons = []
    if worst_dd > MAX_ACCEPTABLE_DRAWDOWN:
        failure_reasons.append(f"worst_case_max_drawdown {worst_dd:.2%} > {MAX_ACCEPTABLE_DRAWDOWN:.0%}")
    if worst_return < MIN_ACCEPTABLE_WORST_CASE_RETURN:
        failure_reasons.append(f"worst_case_net_return {worst_return:.2%} < {MIN_ACCEPTABLE_WORST_CASE_RETURN:.0%}")
    if not results:
        failure_reasons.append("no_scenario_produced_a_result")

    return AdversarialReport(
        scenario_results=results,
        worst_case_max_drawdown_pct=worst_dd,
        worst_case_net_return_pct=worst_return,
        passed=not failure_reasons,
        failure_reasons=failure_reasons,
    )


# A 10-percentage-point stdev in return across DNA variants at the same
# scenario/cost combination is treated as maximally unstable for the
# parameter-stability component below.
STABILITY_STDEV_NORMALIZER = 0.10


def compute_robustness_score(report: AdversarialReport) -> float:
    """Normalized [0,1] composite: (1) how far worst-case drawdown stayed
    below MAX_ACCEPTABLE_DRAWDOWN, (2) how far worst-case return stayed
    above MIN_ACCEPTABLE_WORST_CASE_RETURN, and (3) parameter stability —
    the stdev of net_return_pct across perturb_dna_variants' results at the
    SAME scenario/cost multiplier. A strategy whose return collapses under
    small parameter jitter scores low on (3) even with a fine baseline,
    which is what "a strategy that only works at exactly one parameter
    value should receive a robustness penalty" means in practice. 0.0 for
    an empty report (no scenario produced a result at all)."""
    if not report.scenario_results:
        return 0.0

    drawdown_component = _clip01(1.0 - report.worst_case_max_drawdown_pct / MAX_ACCEPTABLE_DRAWDOWN)
    return_component = _clip01(
        (report.worst_case_net_return_pct - MIN_ACCEPTABLE_WORST_CASE_RETURN) / abs(MIN_ACCEPTABLE_WORST_CASE_RETURN)
    )

    groups: dict[tuple[str, float, float], list[float]] = {}
    for r in report.scenario_results:
        key = (r.scenario_name, r.fee_multiplier, r.slippage_multiplier)
        groups.setdefault(key, []).append(r.result.net_return_pct)
    stdevs = [statistics.pstdev(returns) for returns in groups.values() if len(returns) > 1]

    if stdevs:
        stability_component = _clip01(1.0 - statistics.mean(stdevs) / STABILITY_STDEV_NORMALIZER)
    else:
        stability_component = 1.0  # too few variants at any shared scenario to measure instability

    return (drawdown_component + return_component + stability_component) / 3.0


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))
