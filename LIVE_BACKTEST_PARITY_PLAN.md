# Live/Backtest Orchestration — Investigation (Initiative 1, Phase 1)

**Status: investigation only. No production code modified.** This is independent of the completed
Phase 1-4 work (`REFACTOR_PLAN.md`/`REFACTOR_PROGRESS.md`), which is closed. This document responds
to the one genuine remaining finding from `ARCHITECTURE_REVIEW.md` §12.

Baseline established by running the full existing suite before any change was even considered:
`tests/test_live_backtest_parity.py`, `test_backtest_parity.py`, `test_walk_forward_parity.py`,
`test_sizing.py`, `test_margin_liquidation.py`, `test_min_notional_decision_time.py`,
`test_risk_engine.py` → **60 passed, 0 failed, 109.18s.** This is the parity contract's current,
working state, against which any future change must be measured.

---

## Phase 1.1 — Missing characterization test (done, test-only, no production code changed)

**Added:** `tests/test_min_notional_decision_time.py::test_backtest_currently_agrees_with_below_min_order_notional_at_a_real_nonzero_threshold`

**Purpose:** §10.1 above identified that the existing parity suite provides **zero evidence** about
minimum-notional handling, because `test_live_backtest_parity.py`'s own `deterministic` fixture sets
`paper_min_order_notional = 0.0` before every live-vs-backtest comparison. This test closes that gap
by exercising a **real, non-zero** threshold directly against `app.backtesting.engine.run_backtest`,
using `below_min_order_notional()` (the shared function backtest does *not* currently call) as the
behavioral reference - exactly as instructed, without modifying that function or any production code.

**What it does:**
1. Runs a real, proven-to-trade backtest scenario (`ema_cross_dna(5, 20)` over `candles(seed=3)`,
   reused from `test_backtest_parity.py` - the same fixtures `test_declared_indicator_periods_drive_backtest_behaviour`
   already relies on) with `paper_min_order_notional` at its normal default, and records the first
   real trade's notional (`entry_price * quantity`).
2. **At the minimum (inclusive boundary):** re-runs the identical scenario with
   `paper_min_order_notional` set to *exactly* that notional. Asserts the same trade still opens,
   unchanged (same entry index, price, quantity) - and that `below_min_order_notional()`, given the
   same notional/price under the same setting, independently agrees it is *not* below the minimum.
3. **Below the minimum:** re-runs with the threshold set to 1,000× that notional (far above anything
   attainable in this scenario). Asserts **zero** trades occur anywhere in the run - and that
   `below_min_order_notional()` independently agrees this notional *is* below the minimum.
4. **A methodological note worth recording**: the first version of this test used the stored
   `BacktestTrade.entry_price` (the *post-slippage* fill price) to compute the boundary threshold,
   and failed - not because backtest's min-notional logic was wrong, but because the engine's actual
   gate checks the *pre-slippage* `next_open` reference price, and a few bps of slippage was enough
   to flip which side of an exact boundary the comparison landed on. The fix was to zero both
   `slippage_bps` (a `run_backtest` parameter) and `paper_slippage_impact_bps_per_10k` (a `Settings`
   field the size-aware slippage component reads directly, not exposed as a parameter) for this test
   only, making `entry_price` bit-identical to `next_open`. This was a bug in the **test's own
   arithmetic**, caught and fixed before the test was considered complete - not a finding about
   production behavior, and worth keeping in mind for Phase 1.2's implementation: any future
   assertion comparing a stored fill price against a pre-fill reference price must account for this.

**Result: PASSES against the current, unmodified `backtesting/engine.py`.** This confirms backtest's
inline minimum-notional logic already agrees with the shared `below_min_order_notional()` function at
both tested boundaries - the duplication identified in §3-6 is a *maintenance* risk (two
implementations of one rule, kept in sync only by convention), not a *currently-manifesting behavior
difference*. This is exactly the evidence Phase 1.2 needs before treating the proposed swap as a
verified no-op.

**Verification:**
- New test alone: **1 passed.**
- Full `test_min_notional_decision_time.py`: **5 passed** (4 pre-existing + 1 new).
- Full Phase-1 baseline re-run: **61 passed, 0 failed, 110.86s** (60 pre-existing + 1 new; zero
  change to any pre-existing test's outcome).
- `git status`: only `tests/test_min_notional_decision_time.py` changed. `backtesting/engine.py`,
  `execution/sizing.py`, `execution/margin.py`, `risk/risk_engine.py`, `decision_loop.py` are
  untouched, confirmed.

**STOPPING here as instructed. Phase 1.2 (swapping backtest's inline check for a direct call to
`below_min_order_notional`) has not been implemented and awaits explicit approval.**

---

## 1. Live execution flow (complete trace)

`app/agents/decision_loop.py::_process_agent_inner`, "step 4" (signal already matched, priced at the
signal bar's **close** - the only price known at decision time):

1. `stop_distance_pct(dna, price, atr, swing_low, swing_high, side)` → fractional stop distance.
2. `requested_notional(dna, equity=agent.equity, price, atr, stop_dist_pct)` → DNA's raw ask, then
   scaled by the council's `size_modifier` (unless the council was itself incomplete).
3. `margin_state(balance=agent.balance, maintenance_margin_rate=...)` → flat-account
   `available_margin` (no position yet).
4. `check_trade(RiskCheckInput(..., proposed_notional, available_margin, stop_distance_pct, ...))`
   → `RiskCheckResult(decision, approved_notional, approved_leverage, reasons)` - the single
   enforcement point, **always invoked** for a real agent (no flag to skip it).
5. `approve_against_margin(risk_result.approved_notional, leverage, available_margin)` → caps
   **again** against the same margin snapshot.
6. `below_min_order_notional(approved, price)` → decision-time replica of what
   `PaperExecutionAdapter` will do at fill time (lot-step rounding, exchange minimum). Rejects here,
   before persistence, if it would fail there.
7. `build_sizing_result(...)` → final `SizingResult` (quantity, margin, risk_amount).
8. **Persist**: `Order` row (`requested_notional`, `approved_notional`, `initial_margin`,
   `risk_amount`, `leverage`, `quantity`) + `Decision.risk_reasoning` (full audit: reasons, notional,
   margin, leverage, sizing method, council audit). Status `PENDING` (next-open mode, the default).
9. **A full bar later** (`_execute_pending_entry` → `_fill_entry`, `decision_loop.py`): re-derives
   `margin_state`/`approve_against_margin` **again**, this time against the agent's **current**
   balance (which may have moved since the decision), recomputes `quantity = notional /
   reference_price` at the **fill** price, then calls `cc.engine.submit_order(...)` -
   `ExecutionEngine.submit_order()`, the abstract port.
10. `PaperExecutionAdapter.submit_order()` (the concrete implementation reached through the port):
    idempotency check (`_SEEN_ORDER_IDS` + DB unique constraint), simulated latency (+ optional
    Gaussian jitter and price drift), lot-size floor rounding (skipped for reduce-only exits),
    minimum-notional reject, random reject (entries only), partial fill (entries only), slippage via
    `app.execution.fillmodel.slipped_price`/`slippage_bps`, fee via `fillmodel.fee_rate_for`. Fully
    deterministic per `client_order_id` (seeded RNG), no real I/O.
11. Back in `decision_loop.py`: `Position` created from the fill; `accounting.entry_levels` computes
    stop/TP/trailing levels; `agent.balance -= fee`; `agent.trade_count`/`daily_trade_count`
    incremented.
12. Every subsequent bar: `_manage_open_position` → `_accrue_funding` (real settlement events from
    `FundingRate` rows) → `margin_state` (position-bearing form, live mark-to-market) →
    `evaluate_bar` (stop/TP/trailing trigger) → on trigger, `_close_position`: submits a reduce-only
    order through the **same** `ExecutionEngine.submit_order()` port, applies
    `accounting.liquidation_penalty` if relevant, `compute_trade_pnl`, `accounting.settle_close`
    (bad debt recorded, not hidden), `accounting.cooldown_bars_after`/`cooldown_expiry_ms`.

## 2. Backtest execution flow (complete trace)

`app/backtesting/engine.py::run_backtest`, single-threaded event loop over precomputed bars, entirely
in-process (no DB, no `ExecutionEngine`, no `Decision`/`Order`/`Position` rows):

1. **(a) Manage the open position on this bar** (if one exists and its `entry_index <= i`): apply due
   funding settlements inline (`accounting.funding_payment`), recompute `compute_liquidation_price`,
   build the same `PositionLevels`, call the **same** `evaluate_bar` - on trigger, call the local
   `close()` helper (see below); else `advance_extremes` and `margin_state` (position-bearing form)
   for a liquidation check.
2. **(b) Signal at this bar's close**: build the same `FeatureView`, call the **same**
   `evaluate_signal`.
3. **(c)/(d) Exit or entry fills at the next bar's open** (`fill_idx = i + 1 +
   execution_delay_bars`, default delay 0): for an entry, `stop_distance_pct` →
   `requested_notional` (using **the signal bar's own `balance`**, no margin snapshot object) →
   **optionally** `backtest_risk_check` (only if `enforce_risk_engine=True` - **off by default**) →
   `approve_against_margin(notional, leverage, available_margin=eq_now)` (note: `eq_now` here is
   plain `balance`, not a `MarginState.available_margin`, since a flat account's available margin
   *is* its balance - mathematically equivalent to live's flat-account `margin_state` call, but
   computed as a bare float instead of constructing a `MarginState`) → quantity computed via
   `qty = (notional * fill_fraction) / next_open` **directly from the decision-time approved
   notional - no re-check against balance at the fill bar** → own inline lot-step rounding
   (`int(qty / step + 1e-9) * step`, not `math.floor`) → own inline minimum-notional check (does
   **not** call `below_min_order_notional`) → own inline `slip()`/fee calculation using the
   **same** `app.execution.fillmodel` functions → `accounting.entry_levels` for stop/TP/trailing.
4. **(e) Mark-to-market equity**: `balance + unrealized_pnl` appended to the equity curve; a
   bankruptcy/liquidation check identical in intent to live's.
5. `close()` (the local helper used by both the position-management step and the final
   close-at-end-of-data step): slippage via `fillmodel.slipped_price`, fee via `fillmodel.fee_rate_for`,
   liquidation penalty via `accounting.liquidation_penalty`, PnL via `compute_trade_pnl`, settlement
   via `accounting.settle_close`, cooldown via `accounting.cooldown_bars_after`.

## 3. Side-by-side comparison

| Step | Live (`decision_loop.py` + `PaperExecutionAdapter`) | Backtest (`engine.py`) | Same code? |
|---|---|---|---|
| Stop distance | `stop_distance_pct(...)` | `stop_distance_pct(...)` | **Yes**, identical call |
| Requested notional | `requested_notional(...)` | `requested_notional(...)` | **Yes**, identical call |
| Available margin (flat) | `margin_state(balance=...)` → `.available_margin` | bare `balance` passed directly | Same **math** (a flat account's available margin *is* its balance - see `margin.py::margin_state`'s own flat-account branch), different **shape** (object vs. float) |
| Risk enforcement | `check_trade(...)` - **always** | `backtest_risk_check(...)` (thin adapter around the same `check_trade`) - **only if `enforce_risk_engine=True`** | **Yes** when enabled, via the existing adapter; **optional** in backtest, mandatory in live |
| Margin approval | `approve_against_margin(...)` | `approve_against_margin(...)` | **Yes**, identical call |
| Minimum-notional (decision-time) | `below_min_order_notional(...)` (shared function) | own inline equivalent (does not call the shared function) | **No** - same rule, reimplemented |
| Sizing result construction | `build_sizing_result(...)` | none - quantity computed inline | Backtest-only shortcut (no `Order`/`Decision` row to populate) |
| Lot-step rounding | `PaperExecutionAdapter._floor_to_step` (`math.floor`) | inline (`int(...)`) | Same rule, reimplemented, **relies on quantities always being non-negative** for the two to agree |
| Fill timing | `PENDING` at signal close → filled at next bar's open (`_execute_pending_entry`/`_fill_entry`) | `fill_idx = i + 1 (+ execution_delay_bars)`, filled at `next_open` inline | **Yes**, same next-open rule; live persists the intermediate `PENDING` state, backtest doesn't need to (single in-process loop) |
| Margin re-check at fill | **Yes** - `_fill_entry` re-runs `margin_state`/`approve_against_margin` against **current** balance | **No** - uses the decision-bar's already-approved notional directly | **Genuine difference** (see §4) |
| Slippage/fee | `fillmodel.slipped_price`/`slippage_bps`/`fee_rate_for`, called from inside `PaperExecutionAdapter.submit_order` | same `fillmodel` functions, called directly from `engine.py`'s own `slip()`/`close()` | **Yes**, fully shared math; different caller |
| Latency, random reject, partial fill | Yes, deterministic-per-order RNG (`PaperExecutionAdapter`) | No, unless the caller explicitly sets `execution_delay_bars`/`entry_reject_probability`/`fill_fraction` (adversarial testing only) | **Live-only by default**; backtest opts in via explicit stress knobs, never by accident |
| Idempotency (`client_order_id`) | Yes - `_SEEN_ORDER_IDS` + DB unique constraint | N/A - no `Order` rows, no concurrent workers, no retries | **Live-only**, structurally not applicable to a single in-process loop |
| Entry/close levels, cooldown, settlement, liquidation penalty | `app.execution.accounting.*` | `app.execution.accounting.*` | **Yes**, fully shared, zero duplication |
| Position/balance bookkeeping | Real `Agent`/`Position`/`Order`/`Trade`/`Decision` ORM rows, committed per bar | Local `_Pos` dataclass + plain floats (`balance`, `peak_equity`, ...), never touches the DB | **Structurally different** (real system vs. simulation), not a duplication - a database-backed live loop and a hot in-memory simulation loop over thousands of backtest windows cannot share a persistence model without an unacceptable performance cost to research (per `docs/architecture.md`: hundreds of backtests run per generation) |

## 4. Classification of every difference

**Genuinely duplicated calculations (same math, written twice):**
- Minimum-notional check (`below_min_order_notional` vs. backtest's inline equivalent) - identical
  rule, two implementations.
- Lot-step rounding (`math.floor` in the adapter vs. `int()` in the backtest) - identical *result*
  for the domain's always-non-negative quantities, but a latent fragility: they are not provably the
  same function, just currently equivalent by convention.
- Flat-account "available margin equals balance" - expressed once as `MarginState.available_margin`
  (via `margin_state()`), once as a bare variable (`eq_now`) - same fact, two representations.

**Genuinely duplicated sequencing (the same recipe, hand-written twice):**
- The overall "stop-distance → requested-notional → margin → risk → margin-approve → quantity"
  order is independently maintained in both files. Not a difference in *result* for any of the four
  parity scenarios tested, but two places that must be kept in step by hand if the recipe ever
  changes (e.g., a new risk clamp, a new sizing method needing an extra input).

**Intentionally different behavior:**
- Risk-engine enforcement is optional in backtest (`enforce_risk_engine` flag), mandatory in live.
  This is correct: a quick DNA-validation backtest (e.g. `test_declared_indicator_periods_drive_backtest_behaviour`)
  has no reason to pay the Risk Engine's cost or reasoning, whereas a live agent trading real
  (paper) capital must always be checked. The **research pipeline and adversarial suite always pass
  `enforce_risk_engine=True`** (confirmed: `app/research/pipeline.py` and
  `app/backtesting/adversarial.py` both do), so the *validated, promotion-relevant* backtest path
  does enforce it - the flag exists for cheaper, non-decision-relevant backtests only.
- Exit-reason string naming: live's signal-exit reason resolves to `"exit_rules"` (from the strategy
  engine's own reasoning payload), backtest's hardcodes `"signal"`. **Explicitly tolerated by the
  parity test itself** (`test_live_backtest_parity.py` line 114's special-case comparison) - a
  cosmetic naming difference, not a behavioral one, already accepted as such by the existing test.

**Live-only behavior:**
- Latency simulation, random order rejection, partial fills, `client_order_id` idempotency,
  SAVEPOINT-per-agent isolation, worker fencing, `Decision`/`Order`/`Position`/`Trade` persistence.
  None of these have (or should have) a backtest equivalent in the *default* path - they exist
  because live is a real, concurrent, crash-recoverable system and backtest is a deterministic,
  single-threaded simulation. The **parity test's own `deterministic` fixture explicitly disables
  every one of these on the live side** before comparing, which is the correct scope for the parity
  contract: it is a contract about *decision and cost-model* equivalence, not about live's
  operational-realism features.

**Backtest-only behavior:**
- `execution_delay_bars`, `fill_fraction`, `entry_reject_probability` (adversarial stress knobs),
  `position_fraction_override` (walk-forward/adversarial sizing override), shared precomputed
  `BacktestData` across many windows (a performance necessity - `docs/architecture.md` confirms
  hundreds of backtests run per research generation).

**Differences caused by next-open execution:**
- None found beyond the mechanism itself, which both paths implement identically (signal at bar
  N's close, fill at bar N+1's open) - this is exactly what `test_live_backtest_parity.py` verifies
  and what currently passes for all 4 scenarios.

**Rounding differences:** see "lot-step rounding" above - functionally equivalent today, not
provably identical (two call sites, one fact).

**Minimum-notional handling:** **explicitly excluded from the current parity contract.** The
`deterministic` fixture in `test_live_backtest_parity.py` sets `paper_min_order_notional = 0.0`
before every comparison - meaning **no existing test proves live and backtest agree on
minimum-notional rejection**, only that they agree when it's turned off. This is the single most
important scoping fact for any future work here (see §9).

**Margin timing differences:** the one clear, structural difference. Live re-validates
`available_margin` against the agent's balance **at the fill bar**, not just the decision bar;
backtest does not re-validate at all between decision and fill - it uses the decision-bar's approved
notional directly. In practice, nothing changes a flat agent's balance between its own entry
decision and its own entry fill (no funding accrues on a position that doesn't exist yet, and this
is single-position-per-agent), so this has not been observed to cause a divergence in any of the 4
tested scenarios - but it is a real architectural asymmetry, not a proven-safe one, since it has
never been stress-tested against a scenario where it *would* matter (e.g., a cross-agent funding or
correlated-balance event landing between decision and fill - which cannot happen per-agent today,
but the asymmetry exists structurally regardless).

**Risk differences:** `enforce_risk_engine` default (see "intentionally different" above) - already
correctly handled for every promotion-relevant backtest path.

**Fees/slippage differences:** none - `app.execution.fillmodel` is fully shared, called identically
by both paths (confirmed: identical function signatures, identical formulas, verified by the
passing parity assertions on `fees`/`net_pnl` at `rel=1e-9`/`rel=1e-7` tolerance).

**Position/balance differences:** structural only (ORM rows with DB transactions vs. an in-memory
dataclass and plain floats) - not a duplication, a necessary consequence of live being a persistent,
crash-recoverable system and backtest being a fast, disposable simulation run many times per
research generation.

## 5. Existing adapter pattern - can it extend to sizing/margin?

`app/backtesting/risk_adapter.py::backtest_risk_check` works by constructing a minimal, duck-typed
`_SyntheticAgentState` (only the three fields `check_trade` actually reads:
`peak_equity`/`starting_balance`/`equity`) so the backtester can call the **real, unmodified**
`check_trade` without a database-backed `Agent` row.

**This pattern extends cleanly to the one genuine duplication that matters (minimum-notional), and
does not extend usefully to the sizing/margin *sequence* as a whole:**

- `stop_distance_pct`, `requested_notional`, `margin_state`, `approve_against_margin` are already
  called identically by both paths with plain scalar arguments - there is no `Agent`-shaped object
  to adapt away, because none of these functions take one. The adapter pattern solves "a pure
  function needs a domain object I don't have" - that problem does not exist here.
- `below_min_order_notional(notional, price)` also takes plain scalars. It doesn't need an adapter;
  it needs **backtest to call it instead of reimplementing it inline** - a direct import, not a new
  abstraction.

## 6. Proposed shared boundary (smallest possible)

**One function call, not a new module, not a new class:**

Replace backtest's inline minimum-notional check (`engine.py` line 374's
`not (settings.paper_min_order_notional and qty * next_open < settings.paper_min_order_notional)`)
with a direct call to the existing `app.execution.sizing.below_min_order_notional(qty * next_open,
next_open)`, which `engine.py` would need to import (it already imports three sibling functions from
the same module). This:

- Removes the one duplicated *rule* that isn't already provably shared.
- Adds **zero** new abstractions, services, or files - satisfies "do not create a generic
  service/repository layer" and "do not move logic simply to reduce duplication" (this moves
  *nothing*; it deletes a duplicate and calls the original).
- Does **not** touch the lot-rounding duplication (`math.floor` vs `int()`) - that is a smaller,
  lower-value, higher-risk-of-being-called-"line-count reduction" change; recommend leaving it, see
  §12.
- Does **not** touch the margin-timing asymmetry (§4) - that is a behavioral question (should
  backtest re-validate margin at the fill bar?), not a duplication question, and changing it would
  be "making backtest conform to live" territory that needs its own explicit decision, not a
  drive-by fix bundled into a duplication cleanup.
- Does **not** touch `enforce_risk_engine`'s optionality - that is intentional, already correctly
  used everywhere that matters (§4).

**Nothing about the broader sequencing "duplication" (stop-distance → notional → margin → risk →
approve) is proposed to change.** Both files already call the exact same four functions in the exact
same order for that part; there is no *code* to unify, only a hand-maintained convention to keep in
sync, which a comment/test can guard against more cheaply and safely than an extraction.

## 7. Dependency direction

No change to dependency direction: `app/backtesting/engine.py` already imports from
`app.execution.sizing`; adding one more import from the same module doesn't cross any new boundary.
`app.execution.sizing` remains dependency-free of both `decision_loop.py` and `backtesting/engine.py`
(neither is imported by it) - the proposed change is a strict subset of the existing, already-correct
dependency graph.

## 8. Expected blast radius

- **Files touched:** `app/backtesting/engine.py` (one import line, one conditional expression
  replaced with a function call). Nothing else.
- **Tests affected:** `test_live_backtest_parity.py` (currently doesn't exercise this path at all,
  due to the `deterministic` fixture zeroing `paper_min_order_notional` - see §9), `test_backtest_parity.py`,
  `test_sizing.py`, any adversarial test that sets a non-zero minimum notional.
- **Behavioral change:** in the *default* parity-tested configuration (`paper_min_order_notional =
  0`), **none** - `below_min_order_notional` returns `False` unconditionally when the setting is
  zero (see its own source), identical to backtest's current inline check's behavior in that case.
  In a configuration with a non-zero minimum, backtest's rejection threshold would become
  **exactly** live's (byte-identical lot-rounding via `math.floor` inside the shared function,
  rather than backtest's own `int()`-based rounding) - a **correctness improvement**, not a
  behavior change relative to what the parity contract actually promises.

## 9. Risk assessment

| Risk | Severity | Notes |
|---|---|---|
| Regression in the 4 already-passing parity scenarios | Low | They run with `paper_min_order_notional=0`, where both old and new code paths behave identically |
| Silent behavior change in an *existing* backtest that sets a non-zero minimum | Low-Medium | No such backtest was found in the research pipeline or adversarial suite (both accept the default, which several `.env`/`Settings` defaults likely set - **must be verified** in the implementation phase, not assumed) |
| Scope creep into the margin-timing or `enforce_risk_engine` questions | Medium if not disciplined | Explicitly out of scope for this initiative's first step (§6) |
| The lot-rounding `int()`/`math.floor()` duplication remains | Low | Both are correct today for non-negative inputs; flagged, not fixed, in this phase (§12) |

## 10. Required characterization/parity tests before implementation

1. **A new, explicit test** exercising a non-zero `paper_min_order_notional` in both live and
   backtest for the same near-threshold order size, since the current parity suite deliberately
   zeroes this setting and therefore provides **no evidence either way** for this specific path.
   This must be written and passing **against the current, unmodified code** first, to establish
   whether backtest's existing inline check already agrees with `below_min_order_notional` in
   practice (it should, since both perform the same floor-then-compare logic) - only once that's
   confirmed does swapping the implementation become a verified no-op change rather than an assumed one.
2. Re-run the existing baseline in full (`test_live_backtest_parity.py`,
   `test_backtest_parity.py`, `test_walk_forward_parity.py`, `test_sizing.py`,
   `test_min_notional_decision_time.py`) after the change and confirm identical pass/fail counts.
3. Grep the research pipeline and adversarial suite for any call to `run_backtest` that passes a
   non-default, non-zero minimum-notional-relevant setting, to rule out an unnoticed dependency on
   backtest's current inline rounding behavior before touching it.

## 11. Proposed implementation phases (NOT started - awaiting explicit approval)

| Phase | Scope |
|---|---|
| 1.1 | Write the new non-zero-minimum-notional live-vs-backtest test (§10.1) against the **current, unmodified** code; confirm it already passes (establishing that backtest's inline logic and the shared function agree today) or document precisely how it doesn't (which would itself be a new, real finding requiring its own decision before proceeding) |
| 1.2 | If 1.1 passes cleanly: replace backtest's inline minimum-notional check with a call to `below_min_order_notional` (§6), one import + one line changed in `engine.py` |
| 1.3 | Re-run the full baseline (§10.2) plus the new test; confirm zero change in pass/fail counts anywhere |

No phase beyond 1.3 is proposed. The lot-rounding duplication, the margin-timing asymmetry, and
`enforce_risk_engine`'s optionality are documented (§4, §12) but **not** recommended for action as
part of this initiative.

## 12. What should explicitly remain duplicated (source of truth: existing production behavior)

- **Lot-step rounding** (`math.floor` vs `int()`): functionally identical for this domain's
  always-non-negative quantities. Unifying it would require either (a) backtest importing
  `PaperExecutionAdapter._floor_to_step`, a **private method of an execution adapter class**, which
  would be backwards (backtest reaching into a live-only concrete class), or (b) extracting a new
  shared `floor_to_step()` function - technically easy, but this is "moving logic to reduce
  duplication" for a line of code that isn't wrong, isn't tested as divergent, and isn't the
  duplication `ARCHITECTURE_REVIEW.md` flagged. Left alone, explicitly, per instruction not to fix
  duplication that isn't demonstrated to be a problem.
- **Margin re-validation timing**: live re-checks at the fill bar, backtest doesn't. **This is not
  proposed to change** in either direction. Making backtest re-check would be "making backtest
  conform to live" without the parity contract requiring it (§10.1's new test, if it reveals a real
  divergence, would be the trigger for revisiting this - not this document, in advance of evidence).
  Making live *stop* re-checking would remove a real correctness safeguard for no benefit.
- **`enforce_risk_engine`'s optionality**: intentional, already correctly used everywhere it matters
  in production research/promotion paths. Not proposed to change.
- **The overall sizing/margin/risk *sequence***: identical today, hand-maintained in two places.
  Recommend a **comment, not a code change**: a docstring note in each of `decision_loop.py`'s step
  4 and `engine.py`'s step (d), cross-referencing the other and this document, so a future change to
  one prompts a check of the other. This is explicitly a documentation recommendation, not part of
  the code-change scope of Phase 1.1-1.3.

---

## Conclusion

**The duplication is real but narrow.** Of everything traced, exactly one calculation
(minimum-notional handling) is genuinely reimplemented rather than shared, and the existing
`backtest_risk_check` adapter pattern - while it doesn't extend to this specific case (no `Agent`-
shaped object needs adapting) - correctly establishes that the codebase's philosophy is "call the
shared function directly when possible," which this proposal follows for the one place it applies.
Everything else examined (margin-timing asymmetry, `enforce_risk_engine`'s optionality, lot-rounding)
is either already shared, intentionally different, or a theoretically-narrower duplication not worth
the risk of touching without new evidence.

**Recommendation: proceed to implementation, but strictly scoped to §11's three phases** (the
minimum-notional unification alone), gated by the new test in §10.1 written and run against
unmodified code first. Everything in §12 should explicitly remain as-is.

*(This conclusion predates Phases 1.1 and 1.2 below, both now complete - kept here unedited as the
original investigation record. See the top of this document for Phase 1.1, and the section below
for Phase 1.2.)*

---

## Phase 1.2 — Minimum-notional deduplication (done, production code changed)

**Status: implemented, verified, no new failures.** Scope strictly limited to the one duplicated
calculation identified in §3-6 above.

### Exact inline logic before the change

`app/backtesting/engine.py`, inside the entry branch of the main loop:

```python
if qty > 0 and not (settings.paper_min_order_notional and qty * next_open < settings.paper_min_order_notional):
```

`qty` at this point is already lot-step-rounded (the two lines immediately above it). This inline
expression duplicated exactly what `app.execution.sizing.below_min_order_notional()` already does
for the live/paper path - a hand-written re-statement of the same rule, not called through the
shared function.

### Exact production change

**Files changed:** `app/backtesting/engine.py` only. One import line, one conditional expression.

```diff
-from app.execution.sizing import approve_against_margin, requested_notional, stop_distance_pct
+from app.execution.sizing import approve_against_margin, below_min_order_notional, requested_notional, stop_distance_pct
...
-                if qty > 0 and not (settings.paper_min_order_notional and qty * next_open < settings.paper_min_order_notional):
+                if qty > 0 and not below_min_order_notional(qty * next_open, next_open):
```

### Before/after logic

- **Before:** the minimum-notional rule existed in two places - `app.execution.sizing.below_min_order_notional()`
  (used by `decision_loop.py`'s decision-time check) and this hand-written boolean expression in
  `backtesting/engine.py`.
- **After:** `below_min_order_notional()` is the single implementation. `backtesting/engine.py` calls
  it with exactly the same two values the inline expression used - the already-lot-rounded `qty *
  next_open` as the notional, and the same pre-slippage `next_open` as the price - so the shared
  function's internal `quantity = notional / price` recovers `qty` exactly, and its own internal
  re-rounding is idempotent on a value that is already an exact multiple of `paper_quantity_step`.
  The outer `qty > 0 and not (...)` short-circuit structure is unchanged, so a zero quantity (e.g.
  from `entry_reject_probability`) still skips the call entirely, exactly as before.
- **Preserved exactly, by construction of this substitution** (not just by test result): pre-slippage
  `next_open` semantics (the function is called with `next_open`, never a post-slippage price), the
  strict `<` threshold comparison (identical, now inside the shared function), the inclusive
  boundary (a notional exactly at the minimum is still not "below" it, per the function's own `<`,
  not `<=`), rejection/trade-generation behavior (same branch structure, same short-circuit), and
  every surrounding sizing/margin/risk line (`requested_notional`, `margin_state`,
  `backtest_risk_check`, `approve_against_margin`, lot-step rounding itself) - none of which were
  touched.
- **Not changed, per instruction:** slippage behavior, lot-rounding's own formula (still `int(qty /
  step + 1e-9) * step` immediately above, untouched - only the *comparison after it* now calls the
  shared function), fill-time margin validation (a live-only concept, not present in backtest before
  or after), `decision_loop.py`, `execution/margin.py`, `risk/risk_engine.py`, and
  `below_min_order_notional()` itself. No adapter or service class was introduced - this is a direct
  function call, matching the plan's explicit constraint (§9's "do not create a generic
  service/repository layer").

### Tests executed and results

| Check | Result |
|---|---|
| New characterization test alone (Phase 1.1's test) | **1 passed** |
| Full `test_min_notional_decision_time.py` | **5 passed** (unchanged from Phase 1.1) |
| Original 60-test baseline (`test_live_backtest_parity.py`, `test_backtest_parity.py`, `test_walk_forward_parity.py`, `test_sizing.py`, `test_margin_liquidation.py`, `test_min_notional_decision_time.py`, `test_risk_engine.py`) | **61 passed** (60 baseline + Phase 1.1's new test; identical to the Phase 1.1 post-change run) |
| Full backend suite (`.venv/bin/python -m pytest -q`, solo) | `2 failed, 937 passed, 17 skipped, 2 xfailed in 379.14s` - the 2 failures are the same pre-existing ones (`test_logging`, `test_secret_scan`, unrelated, already documented); 937 = the 936-passed prior state (end of Phase 4/Initiative-1-Phase-1.1) + this phase contributing zero net new tests beyond what 1.1 already added |
| Lint (`ruff check app/backtesting/engine.py`) | One pre-existing import-order finding (`I001`), confirmed via `git stash` to exist identically on the file *before* this change - not introduced by it |

**No golden/parity behavior changed. No new failures anywhere.**

### Confirmation: single ownership achieved for the duplication that was in scope

**Correction to an earlier draft of this section**, caught before finalizing: a fresh
`grep -rn "paper_min_order_notional" app/` after the change shows **three** call sites that
apply this rule, not one:

1. `app/execution/sizing.py::below_min_order_notional()` - the shared implementation.
2. `app/agents/decision_loop.py:607` - the decision-time check, calling (1). Unchanged.
3. `app/execution/paper_adapter.py:104` - `PaperExecutionAdapter.submit_order()`'s own **fill-time**
   inline check, independent of (1), untouched by this phase.

(3) is real and was **never in scope** for this investigation or this phase - `below_min_order_notional()`'s
own docstring states it exists specifically to *mirror the paper adapter's fill-time check*, so that
a decision made now agrees with what the adapter will do a bar later. The adapter's check is the
original, authoritative behavior; the shared function was written to replicate it at an earlier point
in time, not to replace it. Deduplicating (2)/(3) - i.e. having the adapter call the shared function
too, or vice versa - was not part of `ARCHITECTURE_REVIEW.md` §12's finding (which was specifically
about `decision_loop.py` vs. `backtesting/engine.py`) and is not proposed here.

**What this phase actually achieved**: `below_min_order_notional()` is now the single implementation
shared by the **two decision-time paths** - live's `decision_loop.py` and backtest's `engine.py` -
which is exactly the duplication `ARCHITECTURE_REVIEW.md` §12 and this document's §3-6 identified and
scoped. The separate, pre-existing, intentional fill-time/decision-time pair ((2) vs. (3)) is a
different, already-understood relationship, not a new or newly-discovered duplication, and remains
exactly as it was.

**STOPPING here as instructed. No further live/backtest refactoring has begun. Awaiting explicit
approval before any next step** (the lot-rounding duplication, margin-timing asymmetry, and
`enforce_risk_engine` optionality documented in §12 remain explicitly untouched, per that section's
own recommendation).

---

## Initiative 1 — CLOSED

### 1. Objective

Investigate the one genuine remaining architectural finding from `ARCHITECTURE_REVIEW.md` §12: real
duplication between the live decision path (`decision_loop.py`) and the backtest path
(`backtesting/engine.py`) in their shared sizing → margin → risk orchestration - and resolve it if,
and only to the extent, the evidence justified.

### 2. Investigation result

Of everything traced across both flows (stop-distance, requested-notional, margin state, risk
enforcement, margin approval, lot rounding, minimum-notional handling, fill mechanics, cost model,
accounting), **exactly one calculation was genuinely reimplemented rather than shared**:
minimum-notional handling at decision time. Everything else was either already fully shared
(`app.execution.fillmodel`, `app.execution.accounting`, the core sizing/margin/risk function calls
themselves), or an intentional, evidence-backed difference (see §5). The existing
`backtest_risk_check` adapter pattern was inspected and found not to extend usefully to this case,
because no `Agent`-shaped object needed adapting - the fix was a direct function call, not a new
abstraction.

### 3. Exact change

`app/backtesting/engine.py` - one import, one conditional expression:

```diff
-from app.execution.sizing import approve_against_margin, requested_notional, stop_distance_pct
+from app.execution.sizing import approve_against_margin, below_min_order_notional, requested_notional, stop_distance_pct
...
-if qty > 0 and not (settings.paper_min_order_notional and qty * next_open < settings.paper_min_order_notional):
+if qty > 0 and not below_min_order_notional(qty * next_open, next_open):
```

Plus one new characterization test (`tests/test_min_notional_decision_time.py::test_backtest_currently_agrees_with_below_min_order_notional_at_a_real_nonzero_threshold`),
written and confirmed passing against the unmodified implementation *before* the production change
was made (Phase 1.1), so the change could be verified as a proven no-op rather than an assumed one.

No other file was touched. `decision_loop.py`, `execution/sizing.py`, `execution/margin.py`,
`risk/risk_engine.py`, and `below_min_order_notional()` itself were never modified.

### 4. Verification

- New characterization test: 1 passed (both before and after the production change - it was written
  against the old code first, per Phase 1.1, and re-run unmodified after Phase 1.2).
- Full `test_min_notional_decision_time.py`: 5 passed.
- Original 60-test parity/sizing/margin/risk baseline + the new test: **61 passed.**
- Full backend suite: **937 passed, 2 failed, 17 skipped, 2 xfailed.** The 2 failures are the same
  pre-existing, unrelated failures present throughout this entire session
  (`test_logging.py::test_uvicorn_access_log_formats_and_is_redacted`,
  `test_secret_scan.py::test_repository_tracked_files_are_clean` - the already-documented committed
  `.env`). Zero new failures anywhere, at any point in this initiative.
- Lint: the one finding on the changed file was confirmed pre-existing via `git stash` comparison
  against the unmodified original, not introduced by this change.

### 5. Intentional differences left untouched

- **Live decision-time minimum-notional behavior** (`decision_loop.py`) - unchanged; it already
  called the shared function before this initiative began.
- **Fill-time `PaperExecutionAdapter` validation** - remains its own, separate, pre-existing inline
  check. This is intentional and predates this initiative: `below_min_order_notional()` exists
  specifically to *mirror* the adapter's fill-time behavior at decision time, not to replace it. Not
  a newly-discovered duplication; not in scope.
- **Lot-rounding** (`math.floor` in the adapter vs. `int()` in the backtester's own quantity
  rounding, one step earlier in the same function) - functionally identical for this domain's
  always-non-negative quantities; left as two representations of one fact, not unified, per §12's
  own recommendation against fixing duplication that isn't demonstrated to be a problem.
- **Margin-timing asymmetry** - live re-validates `available_margin` against the agent's balance at
  the fill bar (a bar after the decision, in next-open mode); backtest uses the decision-bar's
  already-approved notional directly with no re-check. Real, structural, never observed to cause a
  divergence in any tested scenario, and explicitly not proposed to change in either direction
  without new evidence that it matters.
- **`enforce_risk_engine`'s optionality** - mandatory in live, optional (default off) in backtest,
  but already `True` everywhere it is relevant (the research pipeline and the adversarial suite both
  pass it explicitly). Intentional, unchanged.

### 6. Remaining future candidates (not started, not scheduled)

- Extending `AIClientPort`-style dependency inversion to `app/evolution/ollama_researcher.py` (the
  one dormant, unwired instance of the pre-Phase-1 `OllamaClient` coupling shape) -
  `ARCHITECTURE_REVIEW.md`'s own roadmap item 2, Low priority, cheap whenever that module is next
  touched for functional reasons.
- The margin-timing asymmetry (§5) could warrant its own investigation if a future scenario is found
  where it produces an observable live/backtest divergence - no such scenario exists today, so no
  action is proposed.
- `_process_agent_inner`'s further decomposition (`ARCHITECTURE_REVIEW.md` roadmap item 3, Medium,
  optional) - a separate, `decision_loop.py`-internal question, unrelated to live/backtest
  orchestration.

None of these are started. None are scheduled without further explicit instruction.

### 7. Status

**Initiative 1 (Live/Backtest Orchestration Unification) is CLOSED.** Its scope - the one genuine
duplication identified by `ARCHITECTURE_REVIEW.md` §12 - was investigated, narrowly and precisely
resolved, and fully verified with zero new test failures across three full-suite runs. No further
live/backtest refactoring will begin without new, explicit instruction.