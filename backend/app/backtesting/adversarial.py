"""Adversarial / stress testing for promising strategies (spec sections
22-25): deliberately run a strategy's DNA through distorted market
conditions and cost environments before it's trusted with promotion, rather
than only ever backtesting it under benign historical data.
"""
from __future__ import annotations

import random

from app.evolution.rng import derived_rng
import statistics
import zlib
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.data import prepare_backtest_data
from app.backtesting.engine import BacktestResult, run_backtest
from app.evolution.mutation import jitter
from app.market.feature_engine import InsufficientDataError
from app.schemas.strategy_dna import StrategyDNA
from app.strategies.engine import dna_indicator_specs

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


def drop_random_candles(candles: pd.DataFrame, fraction: float, seed: int = 0) -> pd.DataFrame:
    """Removes `fraction` of bars at random (missing-candle feed gaps): the
    indicator windows then span discontinuous time, exactly as they would if
    the worker traded through an unrecovered gap."""
    keep = candles.sample(frac=1.0 - fraction, random_state=seed).sort_index()
    return keep.reset_index(drop=True)


def duplicate_random_candles(candles: pd.DataFrame, fraction: float, seed: int = 0) -> pd.DataFrame:
    """Re-emits `fraction` of bars twice in a row (duplicate feed messages)."""
    dup = candles.sample(frac=fraction, random_state=seed)
    return pd.concat([candles, dup]).sort_index(kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# DNA parameter perturbation, reusing mutation.py's jitter helper.
# ---------------------------------------------------------------------------


def perturb_dna_variants(dna: StrategyDNA, n: int, rng: random.Random | None = None) -> list[StrategyDNA]:
    """Generates `n` independently-jittered DNA variants for parameter-
    robustness testing — every listed field is touched on every variant
    (unlike mutation.py's mutate(), which only touches each field with
    probability MUTATION_RATE)."""
    rng = rng or derived_rng(dna)
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


@dataclass(frozen=True)
class AdversarialConfig:
    """Every scenario parameter. `from_settings()` is the production source; the defaults equal the historical constants."""

    volatility_spike_magnitude: float = 3.0
    gap_pct: float = -0.08
    stale_bars: int = 20
    extreme_move_pct: float = 0.25
    volume_spike_magnitude: float = 5.0
    liquidity_reduction: float = 0.05
    missing_candle_fraction: float = 0.02
    duplicate_candle_fraction: float = 0.02
    execution_delay_bars: int = 3
    partial_fill_fraction: float = 0.5
    reject_probability: float = 0.3
    max_acceptable_drawdown: float = 0.40
    min_acceptable_worst_case_return: float = -0.20

    @classmethod
    def from_settings(cls, s=None) -> "AdversarialConfig":
        from app.core.config import get_settings
        s = s or get_settings()
        return cls(
            volatility_spike_magnitude=s.adversarial_volatility_spike_magnitude, gap_pct=s.adversarial_gap_pct,
            stale_bars=s.adversarial_stale_bars, extreme_move_pct=s.adversarial_extreme_move_pct,
            volume_spike_magnitude=s.adversarial_volume_spike_magnitude,
            liquidity_reduction=s.adversarial_liquidity_reduction,
            missing_candle_fraction=s.adversarial_missing_candle_fraction,
            duplicate_candle_fraction=s.adversarial_duplicate_candle_fraction,
            execution_delay_bars=s.adversarial_execution_delay_bars, partial_fill_fraction=s.adversarial_partial_fill_fraction,
            reject_probability=s.adversarial_reject_probability,
            max_acceptable_drawdown=s.adversarial_max_acceptable_drawdown,
            min_acceptable_worst_case_return=s.adversarial_min_acceptable_worst_case_return,
        )

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _pct(x: float) -> str:
    return f"{round(abs(x) * 100, 6):g}"


@dataclass
class AdversarialReport:
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    # Provenance: everything needed to reproduce this exact run.
    seed: int = 0
    scenario_config: dict = field(default_factory=dict)
    max_drawdown_limit: float = 0.40
    min_return_limit: float = -0.20
    total_trades: int = 0
    # Scenario combinations that raised an unexpected error. These are FAILURES
    # of the strategy under stress (recorded and failing the suite), never
    # silently dropped from the worst-case statistics.
    scenario_errors: list[str] = field(default_factory=list)
    worst_case_max_drawdown_pct: float = 0.0
    worst_case_net_return_pct: float = 0.0
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)


# Fallback limits when a report carries none (hand-built reports in tests). Production runs take BOTH limits from
# settings (`adversarial_max_acceptable_drawdown` / `adversarial_min_acceptable_worst_case_return`) and store them on
# the report, so the pass/fail decision and the robustness normalisers can never disagree.
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
    max_acceptable_drawdown: float | None = None,
    min_acceptable_worst_case_return: float | None = None,
    cost_multipliers: list[tuple[float, float]] | None = None,
    seed: int = 0,
    config: AdversarialConfig | None = None,
    funding: list[tuple[int, float]] | None = None,
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
    cfg = config or AdversarialConfig()
    # REPRODUCIBLE: with no explicit rng the DNA perturbations come from `seed`; every candle transform derives its
    # own seed from it and the per-scenario reject stream is keyed on (scenario, variant) - so (seed, config, dataset,
    # DNA) fully determines the report.
    rng = rng or random.Random(seed)
    variants = [dna] + perturb_dna_variants(dna, n_dna_variants, rng)
    max_dd_limit = max_acceptable_drawdown if max_acceptable_drawdown is not None else cfg.max_acceptable_drawdown
    min_ret_limit = min_acceptable_worst_case_return if min_acceptable_worst_case_return is not None else cfg.min_acceptable_worst_case_return

    mid = len(candles) // 2
    # (name, frame, execution kwargs)
    scenarios: list[tuple[str, pd.DataFrame, dict]] = [
        ("baseline", candles, {}),
        ("volatility_spike", inject_volatility_spike(candles, magnitude=cfg.volatility_spike_magnitude, at_index=mid), {}),
        (f"gap_{'down' if cfg.gap_pct < 0 else 'up'}_{_pct(cfg.gap_pct)}pct", inject_gap(candles, gap_pct=cfg.gap_pct, at_index=mid), {}),
        (f"stale_period_{cfg.stale_bars}", inject_stale_period(candles, length=cfg.stale_bars, at_index=mid), {}),
        (f"extreme_move_down_{_pct(cfg.extreme_move_pct)}pct",
         inject_extreme_move(candles, direction="down", magnitude=cfg.extreme_move_pct, at_index=mid), {}),
        (f"abnormal_volume_spike_{cfg.volume_spike_magnitude:g}x",
         inject_abnormal_volume(candles, magnitude=cfg.volume_spike_magnitude, at_index=mid, length=20), {}),
        ("liquidity_reduction", inject_liquidity_reduction(candles, magnitude=cfg.liquidity_reduction, at_index=mid, length=20), {}),
        (f"missing_candles_{_pct(cfg.missing_candle_fraction)}pct",
         drop_random_candles(candles, cfg.missing_candle_fraction, seed=seed + 1), {}),
        (f"duplicate_candles_{_pct(cfg.duplicate_candle_fraction)}pct",
         duplicate_random_candles(candles, cfg.duplicate_candle_fraction, seed=seed + 2), {}),
        (f"delayed_execution_{cfg.execution_delay_bars}bars", candles, {"execution_delay_bars": cfg.execution_delay_bars}),
        (f"partial_fills_{_pct(cfg.partial_fill_fraction)}pct", candles, {"fill_fraction": cfg.partial_fill_fraction}),
        (f"rejected_or_unknown_orders_{_pct(cfg.reject_probability)}pct", candles,
         {"entry_reject_probability": cfg.reject_probability}),
    ]
    fee_slippage_multipliers = list(cost_multipliers) if cost_multipliers else [(1.0, 1.0), (2.0, 3.0)]

    results: list[ScenarioResult] = []
    errors: list[str] = []
    specs = dna_indicator_specs(dna)
    for scenario_name, stressed_candles, exec_kwargs in scenarios:
        try:
            # Features are computed ONCE per scenario frame and shared by every
            # cost multiplier x DNA-variant run (variants only perturb
            # stops/sizing, never the declared indicators).
            shared = prepare_backtest_data(stressed_candles, symbol=symbol, timeframe=timeframe, specs=specs, funding=funding)
        except InsufficientDataError:
            continue  # the stress transform left too few bars for warm-up: not evaluable
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
                        data=shared, funding=funding,
                        rng=random.Random(zlib.crc32(f"{seed}:{scenario_name}:{idx}".encode())),  # stable across processes
                        **exec_kwargs,
                    )
                except InsufficientDataError:
                    continue
                except Exception as exc:  # unexpected: recorded as a failure, never swallowed
                    errors.append(f"{scenario_name}[x{fee_mult}/{slip_mult}, v{idx}]: {type(exc).__name__}: {exc}"[:300])
                    continue
                results.append(ScenarioResult(scenario_name, fee_mult, slip_mult, idx, result))

    worst_dd = max((r.result.max_drawdown_pct for r in results), default=1.0)
    worst_return = min((r.result.net_return_pct for r in results), default=-1.0)

    failure_reasons = []
    if worst_dd > max_dd_limit:
        failure_reasons.append(f"worst_case_max_drawdown {worst_dd:.2%} > {max_dd_limit:.0%}")
    if worst_return < min_ret_limit:
        failure_reasons.append(f"worst_case_net_return {worst_return:.2%} < {min_ret_limit:.0%}")
    total_trades = sum(len(r.result.trades) for r in results)
    if not results:
        failure_reasons.append("no_scenario_produced_a_result")
    elif total_trades == 0:
        # A strategy that never trades has no drawdown - and no evidence of robustness either. It must not "pass".
        failure_reasons.append("strategy_never_traded_in_any_scenario")
    if errors:
        failure_reasons.append(f"{len(errors)} scenario run(s) raised errors: {errors[0]}")

    return AdversarialReport(
        scenario_errors=errors,
        scenario_results=results,
        worst_case_max_drawdown_pct=worst_dd,
        worst_case_net_return_pct=worst_return,
        passed=not failure_reasons,
        failure_reasons=failure_reasons,
        seed=seed, scenario_config={**cfg.as_dict(), "max_acceptable_drawdown": max_dd_limit,
                                    "min_acceptable_worst_case_return": min_ret_limit,
                                    "scenarios": [name for name, _, _ in scenarios], "cost_multipliers": fee_slippage_multipliers,
                                    "n_dna_variants": n_dna_variants, "funding_events": len(funding or []),
                                    "risk_engine_enforced": not bypass_risk_engine},
        max_drawdown_limit=max_dd_limit, min_return_limit=min_ret_limit, total_trades=total_trades,
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
    if report.scenario_config and report.total_trades == 0:
        return 0.0   # a real suite run in which nothing ever traded: no evidence of robustness

    dd_limit = report.max_drawdown_limit or MAX_ACCEPTABLE_DRAWDOWN
    ret_limit = report.min_return_limit if report.min_return_limit else MIN_ACCEPTABLE_WORST_CASE_RETURN
    drawdown_component = _clip01(1.0 - report.worst_case_max_drawdown_pct / dd_limit)
    return_component = _clip01((report.worst_case_net_return_pct - ret_limit) / abs(ret_limit))

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

