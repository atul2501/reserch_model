"""Pre-trade decision architecture prototype (app.pretrade) — isolation, freshness, look-ahead, gate, cache."""
from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from app.pretrade import (
    CouncilSnapshot, CouncilView, DecisionCache, ExecutionGate, GateConfig, InvalidationReason, LatencyTrace,
    MarketSnapshot, PreTradeDecision, new_decision,
)

BAR = 1_790_000_040_000          # an arbitrary bar open (ms); its close/cutoff is BAR + 59_999
CLOSE = BAR + 59_999


def mk(direction="LONG", price=100.0, now=CLOSE + 2_500, **kw) -> PreTradeDecision:
    return new_decision(agent_id="a1", symbol="SOL", direction=direction, signal_bar_open_time_ms=BAR,
                        reference_price=price, strategy="vwap", feature_version="fe_v2", now_ms=now, **kw)


def snap(now=CLOSE + 3_000, bar=BAR, price=100.0, **kw) -> MarketSnapshot:
    return MarketSnapshot(now_ms=now, current_signal_bar_ms=bar, current_price=price, **kw)


GATE = ExecutionGate(GateConfig(max_decision_age_ms=5_000, max_entry_drift_bps=10.0))


# ---------------------------------------------------------------- isolation
def _pretrade_imports(tree: ast.AST):
    """(import node, enclosing function name or None) for every import of app.pretrade."""
    out = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            f = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            mods = [n.name for n in child.names] if isinstance(child, ast.Import) else \
                   [child.module or ""] if isinstance(child, ast.ImportFrom) else []
            if any(m.startswith("app.pretrade") for m in mods):
                out.append((child, f))
            visit(child, f)
    visit(tree, None)
    return out


def test_live_path_does_not_import_pretrade():
    """The live path never depends on app.pretrade. The ONLY exception is worker/cycle.py, which may import it lazily
    inside its PRETRADE_MODE=shadow hook functions (never at module level), so PRETRADE_MODE=off never loads it."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    allowed_functions = {"_pretrade", "_pretrade_shadow_step", "_pretrade_publish_council", "_pretrade_old_path_point"}
    for sub in ("worker", "agents", "execution", "risk", "council", "strategies", "market"):
        for py in (root / sub).rglob("*.py"):
            found = _pretrade_imports(ast.parse(py.read_text(encoding="utf-8")))
            if py.relative_to(root).as_posix() == "worker/cycle.py":
                assert found, "expected the lazy shadow-hook imports in worker/cycle.py"
                assert all(func in allowed_functions for _, func in found), [func for _, func in found]
            else:
                assert not found, f"{py} imports app.pretrade"


def test_pretrade_off_does_not_load_pretrade_package():
    import subprocess, sys
    code = ("import sys; import app.worker.cycle, app.agents.decision_loop; "
            "print(any(m.startswith('app.pretrade') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=pathlib.Path(__file__).resolve().parents[1], check=True)
    assert out.stdout.strip().splitlines()[-1] == "False"


# ---------------------------------------------------------------- decision record / no look-ahead
def test_information_cutoff_is_bar_close_and_age_counts_from_it():
    d = mk()
    assert d.information_cutoff_ms == CLOSE
    assert d.age_ms(CLOSE + 4_000) == 4_000


def test_features_after_cutoff_are_rejected_at_construction():
    with pytest.raises(ValueError, match="look-ahead"):
        mk(features_as_of_ms=CLOSE + 1)


def test_council_output_from_a_later_bar_is_rejected():
    with pytest.raises(ValueError, match="look-ahead"):
        mk(council_bias="LONG", council_confidence=0.7, council_cutoff_ms=CLOSE + 60_000)


def test_expected_move_and_horizon_are_not_fabricated():
    d = mk()
    assert d.expected_move_bps is None and d.horizon_seconds is None and d.model_version is None


def test_bad_direction_rejected():
    with pytest.raises(ValueError):
        mk(direction="BUY")


# ---------------------------------------------------------------- gate
def test_fresh_valid_decision_is_allowed_and_flags_missing_cost_inputs():
    r = GATE.validate(mk(), snap())
    assert r.allowed and r.reasons == ()
    assert "cost_check_unavailable" in r.flags and "spread_not_checked" in r.flags


@pytest.mark.parametrize("age_s,allowed", [(1, True), (5, True), (6, False), (45, False)])
def test_freshness(age_s, allowed):
    r = GATE.validate(mk(), snap(now=CLOSE + age_s * 1000))
    assert r.allowed is allowed
    assert ("decision_too_old" in r.reasons) is (not allowed)


def test_stale_signal_bar_rejected_even_if_young():
    r = GATE.validate(mk(), snap(bar=BAR + 60_000))
    assert not r.allowed and "stale_signal_bar" in r.reasons


def test_decision_made_before_bar_close_is_lookahead():
    d = mk(now=CLOSE - 5_000)      # "decided" while the bar was still forming
    r = GATE.validate(d, snap())
    assert "decision_predates_its_information" in r.reasons


def test_execution_before_cutoff_rejected():
    r = GATE.validate(mk(now=CLOSE), snap(now=CLOSE - 1))
    assert "execution_before_information_cutoff" in r.reasons


@pytest.mark.parametrize("price,ok", [(100.05, True), (100.11, False), (99.89, False)])
def test_price_drift_both_directions(price, ok):
    r = GATE.validate(mk(), snap(price=price))
    assert r.allowed is ok


def test_drift_sign_is_relative_to_trade_direction():
    assert GATE.validate(mk("LONG"), snap(price=100.05)).price_drift_bps == pytest.approx(5.0)
    assert GATE.validate(mk("SHORT"), snap(price=100.05)).price_drift_bps == pytest.approx(-5.0)


def test_risk_position_pending_conflict_spread_cost():
    g = ExecutionGate(GateConfig(max_spread_bps=3.0, require_spread=True, require_expected_move=True))
    r = g.validate(mk(), snap(risk_ok=False, position_open=True, pending_order=True, conflicting_signal=True))
    for reason in ("risk_rejected", "position_already_open", "order_already_pending", "conflicting_signal",
                   "spread_unknown", "expected_move_unavailable"):
        assert reason in r.reasons
    assert "spread_too_wide" in g.validate(mk(expected_move_bps=30.0), snap(spread_bps=5.0)).reasons
    assert "expected_move_below_cost" in g.validate(mk(expected_move_bps=10.0), snap(spread_bps=1.0)).reasons
    assert g.validate(mk(expected_move_bps=20.0), snap(spread_bps=1.0)).allowed


def test_llm_alone_can_never_authorise_execution():
    """A maximally confident council does not bypass any deterministic check."""
    d = mk(council_bias="LONG", council_confidence=0.99, council_cutoff_ms=CLOSE, confidence=0.95)
    assert not GATE.validate(d, snap(now=CLOSE + 40_000)).allowed           # too old
    assert not GATE.validate(d, snap(risk_ok=False)).allowed                # risk says no


def test_council_requirement_and_age():
    g = ExecutionGate(GateConfig(require_council=True, max_council_age_ms=10_000))
    assert "council_unavailable" in g.validate(mk(), snap()).reasons
    old = mk(council_bias="LONG", council_confidence=0.7, council_cutoff_ms=CLOSE - 60_000)
    assert "council_too_old" in g.validate(old, snap()).reasons


def test_gate_is_deterministic_and_fast():
    d, m = mk(), snap()
    results = [GATE.validate(d, m) for _ in range(2_000)]
    assert len({(r.allowed, r.reasons, r.flags) for r in results}) == 1
    assert sorted(r.validation_us for r in results)[1_000] < 1_000      # median well under 1 ms


# ---------------------------------------------------------------- cache
def test_cache_returns_valid_and_invalidates_with_reasons():
    c = DecisionCache(max_age_ms=5_000, max_drift_bps=10.0)
    d = mk(regime="RANGE")
    c.put(d, position_state="FLAT", risk_epoch=1)
    kw = dict(current_signal_bar_ms=BAR, position_state="FLAT", risk_epoch=1)
    assert c.get("a1", now_ms=CLOSE + 1_000, **kw) is d
    cases = [
        (dict(now_ms=CLOSE + 9_000), InvalidationReason.TOO_OLD),
        (dict(now_ms=CLOSE + 1_000, current_signal_bar_ms=BAR + 60_000), InvalidationReason.NEW_SIGNAL_BAR),
        (dict(now_ms=CLOSE + 1_000, position_state="LONG"), InvalidationReason.POSITION_CHANGED),
        (dict(now_ms=CLOSE + 1_000, risk_epoch=2), InvalidationReason.RISK_CHANGED),
        (dict(now_ms=CLOSE + 1_000, current_regime="TREND_UP"), InvalidationReason.REGIME_CHANGED),
        (dict(now_ms=CLOSE + 1_000, current_direction="SHORT"), InvalidationReason.DIRECTION_CHANGED),
        (dict(now_ms=CLOSE + 1_000, conditions_hold=False), InvalidationReason.CONDITIONS_GONE),
        (dict(now_ms=CLOSE + 1_000, current_price=100.2), InvalidationReason.PRICE_MOVED),
    ]
    for override, reason in cases:
        c.put(d, position_state="FLAT", risk_epoch=1)
        assert c.get("a1", **{**kw, **override}) is None
        assert c.invalidations[-1][2] == reason
        assert len(c) == 0                                   # an invalidated decision is gone, not hidden


def test_conflicting_decision_replaces_and_records():
    c = DecisionCache(max_age_ms=5_000)
    c.put(mk("LONG"), position_state="FLAT", risk_epoch=1)
    c.put(mk("SHORT"), position_state="FLAT", risk_epoch=1)
    assert c.invalidations[-1][2] == InvalidationReason.CONFLICTING_SIGNAL and len(c) == 1


def test_consume_is_single_use_and_new_bar_sweeps():
    c = DecisionCache(max_age_ms=5_000)
    c.put(mk(), position_state="FLAT", risk_epoch=1)
    c.consume("a1")
    assert c.get("a1", now_ms=CLOSE + 1, current_signal_bar_ms=BAR, position_state="FLAT", risk_epoch=1) is None
    c.put(mk(), position_state="FLAT", risk_epoch=1)
    c.on_new_bar(BAR + 60_000)
    assert len(c) == 0 and c.invalidations[-1][2] == InvalidationReason.NEW_SIGNAL_BAR


# ---------------------------------------------------------------- council view (non-blocking)
def test_council_view_never_blocks_and_ages_out():
    async def scenario():
        view = CouncilView()
        release = asyncio.Event()

        async def slow_council():
            await release.wait()
            return CouncilSnapshot("LONG", 0.7, CLOSE, CLOSE + 9_000, "gpt-oss:120b", "council_v1", "COMPLETE")

        assert view.launch(slow_council)
        assert view.launch(slow_council) is False                    # never stacks runs behind a slow LLM
        assert view.latest(now_ms=CLOSE + 1_000, max_age_ms=30_000) is None   # read returns immediately: no result yet
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert view.latest(now_ms=CLOSE + 10_000, max_age_ms=30_000).bias == "LONG"
        assert view.latest(now_ms=CLOSE + 31_000, max_age_ms=30_000) is None  # aged out
    asyncio.run(scenario())


def test_council_view_ignores_failures_and_incomplete():
    async def scenario():
        view = CouncilView()

        async def boom():
            raise RuntimeError("llm down")

        view.launch(boom)
        await asyncio.sleep(0); await asyncio.sleep(0)
        assert view.latest(now_ms=CLOSE, max_age_ms=10**9) is None

        async def incomplete():
            return CouncilSnapshot("NEUTRAL", 0.0, CLOSE, CLOSE + 1, None, None, "INCOMPLETE")

        view.launch(incomplete)
        await asyncio.sleep(0); await asyncio.sleep(0)
        assert view.latest(now_ms=CLOSE + 2, max_age_ms=10**9) is None
    asyncio.run(scenario())


# ---------------------------------------------------------------- latency trace
def test_latency_trace_derivation_and_monotonicity():
    t = LatencyTrace()
    for i, stage in enumerate(["market_event_at", "features_started_at", "features_completed_at", "signal_created_at",
                               "decision_created_at", "execution_validation_at", "order_submitted_at", "fill_at"]):
        t.mark(stage, CLOSE + i * 10)
    d = t.derived()
    assert d["feature_latency_ms"] == 10 and d["total_signal_to_fill_ms"] == 70 and d["llm_latency_ms"] is None
    assert t.is_monotonic()
    t.mark("fill_at", CLOSE - 1)
    assert not t.is_monotonic()
    with pytest.raises(ValueError):
        t.mark("bogus")
