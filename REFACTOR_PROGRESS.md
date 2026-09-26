# Refactor Progress

Tracks execution against `REFACTOR_PLAN.md`. Phases 3+ (config, `decision_loop.py`, test
reorganization) are not started and require separate approval.

---

## Phase 1 — AI client port (council)

**Status: done.**

**Problem.** `app/council/service.py` and `app/council/analysts.py` depended on the concrete
`OllamaClient` class directly. `OllamaClient` itself is correctly the single, well-tested
implementation of Ollama's failure handling (key rotation, retry, fail-closed, schema validation)
— nothing about it needed to change — but the council layer naming the concrete class meant its
real dependency (two methods: `is_available()`, `generate_structured()`) was implicit, and tests
could only prove behavior by happening to pass an object that looked enough like `OllamaClient`.

**Change.** Added `app/council/ports.py`: an `AIClientPort` `Protocol` (structural typing, `pydantic`
+ `typing` only, zero new runtime dependencies) describing exactly those two methods, plus a small
`AICallStats` Protocol for the subset of `OllamaCallStats` the council reads. `council/service.py`
and `council/analysts.py` now import `AIClientPort` instead of `OllamaClient` and type every
`client:` parameter against it. `OllamaClient` was not touched and satisfies the Protocol
automatically (verified directly: `isinstance(OllamaClient.__new__(OllamaClient), AIClientPort) ==
True`).

**Files changed:**
| File | Change |
|---|---|
| `backend/app/council/ports.py` | **new** — `AIClientPort`, `AICallStats` Protocols |
| `backend/app/council/service.py` | import + 3 type hints changed (`OllamaClient` → `AIClientPort`); no logic changed |
| `backend/app/council/analysts.py` | import + 1 type hint changed; no logic changed |
| `backend/tests/test_council_ports.py` | **new** — boundary + behavior regression tests |

**Not changed:** `app/services/ollama_client.py` (the implementation), `app/worker/cycle.py` (the
composition root — correctly still constructs and types the concrete `OllamaClient`, per DI
practice: concrete at the edges, abstract in the middle), `app/evolution/ollama_researcher.py`
(separate subsystem, out of scope, still types against `OllamaClient` directly).

**Tests added** (`test_council_ports.py`, 5 tests):
- `test_council_no_longer_imports_the_concrete_ollama_client` (parametrized ×2) — source-inspection
  proof neither council module imports `app.services.ollama_client` at all.
- `test_ollama_client_satisfies_the_protocol_structurally` — `OllamaClient` still works, unchanged.
- `test_bare_minimum_protocol_conformant_object_is_not_an_ollama_client` — a fake that is provably
  *not* an `OllamaClient` (no inheritance, no registration) still satisfies `AIClientPort`.
- `test_run_council_cycle_works_through_a_non_ollama_client_implementation` — end-to-end: a full
  council cycle (quorum, consensus, persistence) run against that fake, proving the dependency is
  real, not just a renamed type hint.

**Tests run:**
- `test_council_ports.py` + all 5 existing council files (`test_council_service.py`,
  `test_council_consensus.py`, `test_council_deadline.py`, `test_council_failclosed.py`,
  `test_council_integration.py`): **58 passed**.
- `test_ollama_client.py` + `test_ollama_failure_modes.py` (40 tests, unrelated to this change but
  the nearest neighbor — confirms `OllamaClient`'s own behavior is untouched): **40 passed**.
- `test_worker_cycle.py` + `test_gap_cycle.py` (the composition root that constructs the concrete
  `OllamaClient` and threads it through the port): **13 passed**.

**Dependency-boundary improvement:** council code no longer names `OllamaClient` anywhere (enforced
by a test, not just a claim); the AI dependency is now an explicit, minimal, swappable contract.

**Remaining concerns:** none for this phase. `app/evolution/ollama_researcher.py` has the identical
shape of coupling and would benefit from the same treatment, but it's a separate subsystem and out
of this phase's approved scope.

---

## Phase 2 — Lifecycle / execution boundary

**Status: done.**

**Problem.** `app/agents/lifecycle.py::retire_generation()` had a function-local
`from app.execution import accounting` import, used once to call `accounting.settle_close(...)`
when force-closing positions at generation rollover. This is domain code reaching directly into
execution internals — the exact `domain → infrastructure` direction the plan flags as wrong.
`app.execution.accounting` is itself a good module (the one shared, pure accounting
implementation used by paper/shadow/backtest/rollover — not itself broken), so the fix is about
*direction*, not about that module's content.

**Change.** Added `app/agents/ports.py`: a `PositionCloseSettler` Protocol (callable:
`(balance, gross_pnl, exit_fee) -> SettlementResult`) and a `SettlementResult` Protocol
(`new_balance`, `bad_debt`) describing `accounting.settle_close`'s exact existing contract.
`retire_generation()` now takes `settle_close: PositionCloseSettler` as a required keyword
parameter instead of importing `accounting` itself; `lifecycle.py` contains no reference to
`app.execution` anywhere, module-level or deferred (verified by source inspection in the new
test). The one production call site (`app/research/pipeline.py`, the orchestration layer that is
legitimately allowed to know about both domain and execution) now imports `app.execution.accounting`
and passes `accounting.settle_close` explicitly. `accounting.settle_close` itself is unchanged and
satisfies `PositionCloseSettler` structurally (verified directly).

**Files changed:**
| File | Change |
|---|---|
| `backend/app/agents/ports.py` | **new** — `PositionCloseSettler`, `SettlementResult` Protocols |
| `backend/app/agents/lifecycle.py` | removed the deferred `from app.execution import accounting` import; `retire_generation()` gained a required `settle_close` parameter; the one call site inside the function now calls `settle_close(...)` instead of `accounting.settle_close(...)` |
| `backend/app/research/pipeline.py` | added `from app.execution import accounting`; its one call to `retire_generation(...)` now passes `settle_close=accounting.settle_close` |
| `backend/tests/test_snapshots_and_lifecycle.py` | its one call to `retire_generation(...)` updated the same way |
| `backend/tests/test_lifecycle_ports.py` | **new** — boundary + behavior regression tests |

**Call sites verified complete:** grepped the whole repo for `retire_generation(` — exactly three
call sites exist (`app/research/pipeline.py`, `app/agents/lifecycle.py`'s own definition,
`tests/test_snapshots_and_lifecycle.py`), all three accounted for above.

**Tests added** (`test_lifecycle_ports.py`, 4 tests):
- `test_lifecycle_module_does_not_import_execution_at_all` — source-inspection proof.
- `test_accounting_settle_close_satisfies_the_protocol_structurally` — `accounting.settle_close`
  still works, unchanged.
- `test_retire_generation_uses_the_injected_settler_not_a_hardcoded_one` — a fake settler that
  deliberately behaves *differently* from the real one (never records bad debt) is injected, and
  `retire_generation`'s observable output changes accordingly — proves the dependency is real, not
  a renamed import.
- `test_retire_generation_behavior_is_unchanged_with_the_real_settler` — the exact existing
  coverage scenario, run through the new explicit `settle_close=accounting.settle_close` call site.

**Tests run:**
- `test_lifecycle_ports.py` + `test_snapshots_and_lifecycle.py` + `test_agent_lifecycle.py`:
  **19 passed**.
- `test_breeding.py`, `test_evolution_gate_and_champions.py`, `test_evolution_pipeline.py` (exercise
  `app.research.pipeline`, the updated call site, end to end): **32 passed**.
- `test_research_event_loop.py` (adjacent to pipeline changes): **4 passed** in isolation.

**Transactions/persistence/idempotency:** unaffected by design — `settle_close` is a pure,
stateless computation (no I/O, no session access); nothing about commit/flush timing, savepoints,
or the rollover transaction changed. Confirmed by the unchanged-behavior test reproducing the
original scenario's exact assertions (retired count, positions closed, trade rows, `bad_debt`
accounting) through the new call shape.

**Dependency-boundary improvement:** `app/agents/lifecycle.py` (domain layer) no longer imports
`app.execution` at all, at any point — enforced by a test, not just a claim. The one real caller
(`app.research.pipeline`, application/orchestration layer) explicitly supplies the execution
capability it needs.

**Remaining concerns:** none for this phase.

---

## Full test suite (both phases combined)

Baseline (before Phase 1/2, from the prior fitness-engine work): 922 passed, 17 skipped, 2 xfailed,
3 failed (all pre-existing: a flaky event-loop-stall timing assertion, a logging-redaction format
test, and `test_secret_scan.py` correctly flagging the already-documented committed `.env`).

One full-suite run during this work showed two additional failures in
`test_live_backtest_parity.py` (`trailing_stop`, `short_only`) — traced to my own testing process:
a second pytest invocation was running concurrently against the same file-based SQLite test
database while that run was still in progress (confirmed by a `DROP TABLE` teardown collision in
the concurrent run). Re-run standalone, combined with the two new test files, and as a clean solo
full-suite run with nothing else executing concurrently, `test_live_backtest_parity.py` passed
every time — this was test-harness contention, not a code regression.

**Final clean run** (`.venv/bin/python -m pytest -q`, nothing else running concurrently):

```
3 failed, 931 passed, 17 skipped, 2 xfailed in 401.37s
FAILED tests/test_logging.py::test_uvicorn_access_log_formats_and_is_redacted            (pre-existing)
FAILED tests/test_research_event_loop.py::test_evaluate_oos_once_runs_off_the_event_loop (pre-existing flaky timing-threshold class; a *different* specific test tripped it than in the original baseline run - confirms it's a timing flake, not a regression)
FAILED tests/test_secret_scan.py::test_repository_tracked_files_are_clean                (pre-existing, already documented in docs/security.md)
```

931 passed vs. the 922-passed baseline = **+9**, exactly the 5 new `test_council_ports.py` tests
(one parametrized ×2) + 4 new `test_lifecycle_ports.py` tests. Zero new failures beyond the
documented, pre-existing baseline categories.

---

## Phase 3 — Boundary verification and hardening (no `decision_loop.py`)

**Status: done. Verification only — no production code changed.**

Scope was explicitly limited to validating Phases 1 and 2 hold up, producing a dependency map, and
proposing (not implementing) a Phase 4 plan for `decision_loop.py`.

### 1. AIClientPort review

- `grep -n "OllamaClient" app/council/service.py app/council/analysts.py` → zero import/type-hint
  matches. The only three hits (in `analysts.py`) are docstring prose explaining historical
  context (`OllamaClient.last_stats`, "OllamaClient's internal retries"), not code.
- `AIClientPort`/`AICallStats` are imported only by `app/council/{ports,analysts,service}.py` —
  no other module depends on them (nothing over-adopted the port speculatively).
- `AIClientPort`'s method signature (`is_available`, `generate_structured(system_prompt,
  user_prompt, response_model, temperature, max_retries_override, deadline_seconds)`) is generic
  LLM vocabulary — no Ollama-specific field (base URL, API key, model name literal, HTTP status
  handling) appears anywhere in the Protocol.
- `OllamaClient` (`app/services/ollama_client.py`) is unmodified since Phase 1; `app/worker/cycle.py`
  (the composition root) still imports and types it concretely, as it should.
- **New finding, not fixed (out of this phase's scope):** `app/evolution/ollama_researcher.py` has
  the identical pre-Phase-1 coupling shape — `from app.services.ollama_client import OllamaClient,
  OllamaError` and `propose_candidate(client: OllamaClient, ...)`. Checked its callers
  (`grep -rln "ollama_researcher\|propose_candidate"`): only its own file and
  `tests/test_infra_resilience.py` reference it — it is not wired into `app.research.pipeline` or
  any worker today. Recorded under "remaining architectural risks" below; not touched, since fixing
  it wasn't part of the approved Phase 1-3 scope.

### 2. PositionCloseSettler review

- `grep -n "execution" app/agents/lifecycle.py` → the only matches are docstring prose (explaining
  that callers pass `app.execution.accounting.settle_close`) and one unrelated SQLAlchemy API call,
  `.execution_options(synchronize_session=False)` (a coincidental substring match, nothing to do
  with the `app.execution` package). Zero real coupling.
- `retire_generation()`'s signature is confirmed unchanged since Phase 2:
  `(db, generation_number, *, mark_price, at, fee_rate, settle_close: PositionCloseSettler)`.
- All callers of `retire_generation(` in the whole repo (re-grepped fresh): `app/research/pipeline.py`
  (the only production call site) and the two Phase-2-updated test files. No caller was missed.
- `app/research/pipeline.py:46` imports `app.execution.accounting` at module level (not deferred);
  its one call passes `settle_close=accounting.settle_close` explicitly (`pipeline.py:341`). Confirmed
  the correct, sole composition root — it is an application/orchestration module already permitted
  to know about both domain and execution, per REFACTOR_PLAN.md's target architecture.
- Checked `app/agents/`, `app/models/`, `app/schemas/` for any other `app.execution` import: only
  `app/agents/decision_loop.py` has one — expected, already documented in Phase 0/REFACTOR_PLAN.md
  as the Phase 4 target, not a new or hidden dependency introduced by this work.
- `app/agents/ports.py` and `app/council/ports.py` both import only `typing`/`pydantic` — zero
  infrastructure dependency in either port definition.

### 3. Dependency-direction map

```
council/service.py, council/analysts.py
        |  depends on (type hint only; structural/Protocol, no inheritance)
        v
   AIClientPort                              app/council/ports.py
   (is_available, generate_structured)
        ^  satisfies structurally, unmodified
        |
   OllamaClient                              app/services/ollama_client.py
   (key rotation, retry/backoff,
    fail-closed, schema validation)
        ^  constructed and typed CONCRETELY by (composition root - correct)
        |
   app/worker/cycle.py
```

```
app/agents/lifecycle.py :: retire_generation()
        |  depends on (required parameter; structural/Protocol, no inheritance)
        v
   PositionCloseSettler                      app/agents/ports.py
   (balance, gross_pnl, exit_fee) -> SettlementResult
        ^  satisfies structurally, unmodified
        |
   accounting.settle_close                   app/execution/accounting.py
   (shared by paper/shadow/backtest/
    walk-forward/rollover)
        ^  supplied explicitly by (composition root - correct)
        |
   app/research/pipeline.py
```

Both maps have the same shape: the domain/application module names a small Protocol it owns
(`ports.py` beside the dependent code); the concrete infrastructure implementation is unmodified
and satisfies it structurally with no inheritance or registration; a single, identifiable
composition root supplies the concrete implementation explicitly. No other module was found
short-circuiting either arrow.

### 4-5. Test results

**Targeted:**
- Council: `test_council_ports.py` + all 5 pre-existing council test files + `test_ollama_client.py`
  + `test_ollama_failure_modes.py` → **98 passed**.
- Lifecycle: `test_lifecycle_ports.py` + `test_snapshots_and_lifecycle.py` + `test_agent_lifecycle.py`
  + `test_breeding.py` + `test_evolution_gate_and_champions.py` + `test_evolution_pipeline.py` →
  **51 passed**.

**Full suite** (`.venv/bin/python -m pytest -q`, solo, nothing concurrent):
```
2 failed, 932 passed, 17 skipped, 2 xfailed in 394.77s
FAILED tests/test_logging.py::test_uvicorn_access_log_formats_and_is_redacted   (pre-existing)
FAILED tests/test_secret_scan.py::test_repository_tracked_files_are_clean      (pre-existing, documented)
```
This run, the previously-observed flaky `test_research_event_loop.py` timing test did not trip at
all (932 vs 931 passed last run - one more test collected/passed than the prior clean run;
consistent with normal suite growth/timing variance, not a change from this phase, since zero
files were modified). No new failures anywhere.

### Remaining architectural risks (as of end of Phase 3)

1. **`app/evolution/ollama_researcher.py`** still depends on the concrete `OllamaClient` directly
   (same shape Phase 1 fixed in council). Currently unwired into any production pipeline, so the
   blast radius of leaving it is low, but it would need the same `AIClientPort`-style treatment
   before being wired in, or when someone next touches it.
2. **`app/agents/decision_loop.py`** still imports `app.execution` and calls into
   `fillmodel`/`margin`/`sizing`/`paper_adapter` functions directly, alongside the abstract
   `ExecutionEngine.submit_order()` port. This is the known, documented Phase 4 target — see the
   plan below. Not touched in Phase 3, per instruction.
3. No new risks were introduced by Phases 1-3: both new ports are verified structurally sound, both
   composition roots are the sole, correct suppliers of their concrete implementation, and the full
   suite is clean against the same pre-existing baseline as before this work started.

---

## Phase 4 — proposed plan for `decision_loop.py` (NOT implemented; plan only, pending approval)

`decision_loop.py` (955 lines) is the highest-value and highest-risk target identified in
REFACTOR_PLAN.md. It correctly calls the abstract `ExecutionEngine.submit_order()` port, but also
imports and calls `execution.fillmodel.{fee_rate_for, slipped_price, slippage_bps}`,
`execution.margin.margin_state`, `execution.sizing.*`, and
`execution.paper_adapter.new_client_order_id` directly — plus `execution.accounting` for the
same position-close settlement Phase 2 already ported out of `lifecycle.py`. It also has 8-9
distinct responsibilities in one call chain (cycle orchestration, the mandatory protection sweep,
next-open fill mechanics, position management, the signal-risk-sizing pipeline, persistence,
lifecycle updates, audit rows, idempotency/fencing) per Phase 0's findings.

**Why this needs a different methodology than Phases 1-2:** Phases 1-2 were pure dependency-
inversion (change what a function *names* as its dependency, not what it *does*) — a Protocol swap
is behavior-preserving by construction if the concrete implementation is unmodified. `decision_loop.py`
work is different: the plan calls for *extracting* code, which risks subtly changing control flow,
ordering, or transaction boundaries even when the intent is "no behavior change." The invariants at
stake are the most load-bearing in the codebase: `worker_cycles.cycle_id` idempotency, the unique
`(agent_id, candle_open_time)` decision constraint, SAVEPOINT-per-agent isolation, fenced commits
(lease epoch re-verified inside the transaction), and the mandatory post-loop protection sweep.

**Proposed sub-phases (each independently approvable and testable; stop between each):**

| # | Sub-phase | What | Risk |
|---|---|---|---|
| 4.0 | Characterization harness (no code change) | Before touching anything: confirm the existing test suite's coverage of `decision_loop.py` is sufficient as a regression net (`test_worker_cycle.py`, `test_gap_cycle.py`, `test_live_backtest_parity.py`, `test_next_open_execution.py`, savepoint/fencing tests). Identify any gap where a specific extraction could silently change behavior without an existing test catching it, and propose the minimum tests to close that gap - added *before* any extraction, run against the current unmodified file to confirm they pass. | None (no production code touched) |
| 4.1 | Extract next-open fill execution mechanics | The block that processes the *previous* bar's pending order/exit into a named, private function within the same file (`decision_loop.py`) - a pure extract-function refactor: identical statements, identical order, identical variable scope, no logic change. Verify via full-suite run, byte-for-byte identical DB state on a fixed multi-bar/multi-agent scenario before/after. | Medium (isolated, single region, mechanical) |
| 4.2 | Extract position-protection/management | The stop/TP/trailing/liquidation/funding management block into a named, private function, same treatment as 4.1. This is the block the mandatory post-loop sweep also calls - extra care to confirm both call paths (per-agent inline, and the sweep) still execute identically. | Medium-high (two call paths must stay identical) |
| 4.3 | Investigate (not yet decide) the sizing/margin boundary | Phase 0 explicitly left open whether `sizing`/`margin` pre-computation belongs in `decision_loop.py` (pre-execution, arguably decision-side) or should move behind the execution port. This sub-phase is read-only: trace every call site of `app.execution.sizing.*` and `app.execution.margin.margin_state`, document what each needs from `decision_loop.py`'s local state, and bring back a recommendation - no code change until that recommendation is reviewed and approved separately. | None (investigation only) |
| 4.4 | Act on 4.3's recommendation, if approved | Only after 4.3 is reviewed: the smallest change that follows from it (likely: nothing moves, since sizing/margin are legitimately pre-submission decision-side concerns - or a narrow accessor if a genuine leak is found). | Depends on 4.3's finding |

**What Phase 4 will explicitly NOT do:** merge the "cycle orchestration" and "position management"
responsibilities into a single class hierarchy, change the SAVEPOINT/commit/fencing structure,
change idempotency keys, or touch the mandatory protection sweep's invocation points. Per
REFACTOR_PLAN.md, `decision_loop.py`'s job is to orchestrate correctly, not to look
architecturally minimal - extractions are only worth doing where they don't risk that orchestration.

**Explicit stop condition:** if 4.1's before/after DB-state diff shows *any* difference beyond
legitimately non-deterministic fields (timestamps, generated UUIDs), Phase 4 stops there and reports
back rather than proceeding to 4.2.

No part of Phase 4 has been implemented. Awaiting approval to begin at 4.0.

---

## Phase 4.0 — Characterization coverage audit and baseline (no extraction)

**Status: done. Test-only. `decision_loop.py` and execution architecture untouched.**

### Coverage audit

Read `decision_loop.py` in full (955 lines) and inventoried its responsibilities against
the existing suite (`tests/test_decision_loop.py`, `test_decision_volume.py`, `test_funding.py`,
`test_gap_cycle.py`, `test_margin_liquidation.py`, `test_min_notional_decision_time.py`,
`test_next_open_execution.py`, `test_position_protection.py`, `test_sizing.py`,
`test_worker_cycle.py`, `test_worker_fencing.py`, `test_cooldown_limits.py`, `test_shadow_mode.py`
- 12+ files, ~90 tests already targeting this file directly or its immediate collaborators).

| Responsibility | Coverage found | Verdict |
|---|---|---|
| Next-open fill mechanics | `test_next_open_execution.py` (9 tests): pending order creation, fill at next open not signal close, managed on its own fill bar, pending exit, halted/cancelled/expired variants, min-notional at fill time | Well covered |
| Position protection/management | `test_position_protection.py` (13 tests incl. new), `test_funding.py` (6), `test_margin_liquidation.py` (9): failing agent, invalid DNA, dead orphan, force-settle, idempotent per bar, restart survival, bad-debt reconciliation | Well covered |
| Mandatory protection sweep | Same as above, plus `test_gap_cycle.py` (halted-but-protected) | Well covered, **one gap found and closed** (see below) |
| Idempotency keys | `test_worker_fencing.py` (deterministic ids across retries, rollback retry, savepoint releases order id), `test_worker_cycle.py` (candle never reprocessed), `test_decision_loop.py` (distinct client_order_id) | Well covered |
| SAVEPOINT-per-agent isolation | `test_worker_fencing.py::test_an_agent_savepoint_rollback_releases_its_order_id` - traced through in detail: proves a failing agent's rollback does NOT prevent a second agent in the SAME cycle from being processed and committed, and that the failed agent is correctly retried (not treated as a duplicate) on a later cycle | Well covered |
| Fenced commits | `test_worker_fencing.py` (10 tests: lease lost mid-cycle, stops at next agent, local TTL self-fence, DB fence detects takeover, two workers produce one decision set) | Very well covered - the most heavily tested area of the file |
| Sizing/margin pre-computation | `test_sizing.py` (8 unit tests), `test_margin_liquidation.py`, `test_min_notional_decision_time.py` (4) | Well covered at the unit level (ownership question is explicitly Phase 4.3's, not touched here) |
| Order/fill/accounting interactions | `test_decision_loop.py`, `test_funding.py` (trade PnL includes fee+funding, matches equity), `test_margin_liquidation.py` (liquidation penalty, can kill agent) | Well covered |
| Transaction boundaries | `test_worker_cycle.py::test_candle_that_stops_being_final_before_the_decision_phase_aborts_without_any_writes` + the fencing suite | Well covered |

### Coverage gaps found (2) - closed with new characterization tests, current-behavior only

1. **Daily-loss breaker's day-rollover reset was unproven for the field that matters.**
   `test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day` already proved
   `daily_trade_count` resets at UTC day rollover (same code block,
   `decision_loop.py` lines 466-469), but nothing proved `day_start_equity` - the field the
   daily-loss breaker itself reads - also resets. Added
   `test_daily_loss_breaker_lifts_at_the_next_utc_day_even_without_recovering_equity` to
   `tests/test_decision_loop.py`: reproduces the existing breaker-triggers test, then advances to
   the next UTC day and proves the breaker lifts because the anchor re-points to current equity,
   *not* because equity recovered (it explicitly does not).
2. **The mandatory sweep's "other generation" case was undocumented by any test.**
   `protect_open_positions`'s own docstring names four target cases (failed agent, invalid DNA,
   DEAD/orphan owner, other generation); the first three each had dedicated tests, the fourth had
   none. Added
   `test_a_position_from_a_different_generation_than_the_one_being_cycled_is_still_protected` to
   `tests/test_position_protection.py`: an agent in generation 99 with an open position, while
   every cycle in the test only ever runs `generation=100` (so the per-agent loop never touches it)
   - proves only the sweep can and does reach it, including closing it via a stop.

Both were run against the **current, unmodified** `decision_loop.py` and describe what it
*already* does - neither changes or proposes changing behavior.

### Scenarios still uncovered (noted, not closed - judged low-value or explicitly out of scope)

- Venue-mismatch halt has exactly one test (`test_shadow_mode.py`), not in a decision-loop-focused
  file. Works, just thin; not extended here to keep this phase's diff minimal.
- The council `combine()` size-modifier's exact interaction with the
  `"council_incomplete_no_new_trades"` reason string is exercised indirectly
  (`test_council_incomplete_blocks_new_entries_but_still_processes_exits`) but not unit-isolated.
  Low risk (council integration is well covered elsewhere; Phase 4.1/4.2 don't touch this code path).
- Sizing/margin *ownership* (whether it belongs in `decision_loop.py` or behind the execution port)
  is explicitly Phase 4.3's question, not investigated here per your instruction.

### Deterministic fixed scenario and comparison strategy

New file: `tests/test_decision_loop_characterization.py`. One fixed, deterministic scenario run
across 4 candles with next-open (production default) fill timing:
- **Agent A** (generation 100): entry → fills → signal exit → pending exit fills.
- **Agent B** (generation 100, tighter stop): entry → fills → stopped out.
- **Agent D** (generation 100, invalid/schema-drifted DNA): paused, never trades.
- **Agent E** (generation 99 - a *different*, never-cycled generation): a pre-existing open
  position that only the mandatory sweep can reach.

`capture_state(db)` returns a plain dict keyed by each agent's **deterministic** `identifier**
(e.g. `"GEN100-AG0001"`, not the random `Agent.id` UUID), containing every price, quantity, fee,
PnL, balance, status, exit reason, risk decision and risk-reasoning payload - sorted by candle
time within each agent so row order can never cause a spurious diff.

**Explicitly excluded** (documented in the file's module docstring, with the reason for each):
`id` primary keys (random `uuid4` default), `created_at`/`updated_at` (real wall-clock `utcnow()`),
`Agent.death_timestamp` (real wall-clock), `Order.client_order_id`/`Decision.id` (deterministic,
but derived *from* the random `Agent.id`, so they'd differ across runs even with zero behavior
change), and `Order.latency_ms`/`raw_venue_response` (simulated latency, pinned to 0 by
`conftest.py` for all unit tests, excluded anyway so this file never silently depends on that pin).
Everything else is included and is expected to be 100% stable, because it derives only from the
fixed inputs and the **candle clock**, never the wall clock.

Two tests use this scenario:
- `test_fixed_scenario_is_internally_consistent` - readable, independent-of-the-snapshot assertions
  (who traded, who got paused, who reconciled) that describe *why* the scenario is shaped this way;
  a failure here means the scenario broke, not necessarily that `decision_loop.py` changed.
- `test_fixed_scenario_matches_the_captured_baseline` - the actual regression test: asserts the
  captured state equals a golden dict captured from this exact scenario against the current,
  unextracted code. **Phase 4.1+ re-runs this file unmodified after each extraction step; any
  difference beyond the documented exclusions fails it immediately.**

The golden state itself (captured once, embedded literally in the test file) is available for
review in `tests/test_decision_loop_characterization.py`'s `_GOLDEN_STATE` - e.g. agent A's single
trade closes at `exit_price: 99.58007504` via `exit_reason: "exit_rules"`, net PnL
`-0.052975`; agent B's tighter stop fires at `99.56015008` via `"stop_loss"`; agent D never
produces a decision or trade row; agent E's position stays open with
`unrealized_pnl: -0.4` and its `last_processed_open_time` advances every candle despite never
being in the cycled generation.

### Test results

- New tests standalone: `test_decision_loop_characterization.py` (2 tests) - **2 passed**.
- New tests' sibling files: `test_decision_loop.py` + `test_decision_loop_characterization.py` +
  `test_position_protection.py` - **24 passed**.
- Full decision-loop-adjacent set (all 12 files from the audit table above) - **97 passed**.
- Full suite (`.venv/bin/python -m pytest -q`, solo, nothing concurrent):
  ```
  2 failed, 936 passed, 17 skipped, 2 xfailed in 402.08s
  FAILED tests/test_logging.py::test_uvicorn_access_log_formats_and_is_redacted   (pre-existing)
  FAILED tests/test_secret_scan.py::test_repository_tracked_files_are_clean      (pre-existing, documented)
  ```
  936 vs. the 932-passed Phase 3 baseline = **+4**, exactly the 2 gap-filling tests + 2
  characterization tests. Zero new failures.

### Invariants discovered during this audit that Phase 4.1+ must preserve

1. **`LeaseLost` during per-agent processing aborts the entire cycle immediately, uncaught** -
   `fence.check_local()` (line 301-302) is called *outside* the per-agent `try/except`, so it
   propagates past the whole loop, not just that agent's savepoint. This is asymmetric with an
   ordinary `Exception`, which is caught and isolated to that one agent's savepoint. Confirmed by
   tracing `test_lost_lease_flag_stops_the_cycle_at_the_next_agent` in detail.
2. **The per-agent loop's `decided_ids` exclusion (cross-invocation idempotency) and the
   per-position `last_processed_open_time` check (per-bar idempotency) are two distinct
   mechanisms** covering different replay scenarios (agent has no position vs. agent/orphan has an
   open position) - any extraction touching either must keep both, not conflate them into one.
3. **The invalid-DNA-pausing pre-filter only ever runs for the generation actually passed to
   `run_decision_cycle`** - unlike the mandatory sweep (which is generation-agnostic by design).
   This is why the characterization scenario had to place its invalid-DNA agent in the *same*
   generation being cycled (a real design constraint discovered while building the scenario, not
   an assumption).
4. **An agent holding a position is never paused for invalid DNA while the position is open** -
   only once flat (`a.id not in positions` in the pre-filter condition) - confirmed by both the
   pre-existing `test_an_agent_with_invalid_dna_still_gets_protection_and_is_parked` and this
   phase's new scenario.

---

## Proposed Phase 4.1 scope (NOT implemented - proposal only, pending your approval)

Per REFACTOR_PLAN.md's Phase 4 table: extract the **next-open fill execution mechanics**
(`_execute_pending_entry`, `_execute_pending_exit`, `_fill_entry` - `decision_loop.py` lines
657-756) into named, private functions **in the same file** - a pure extract-function refactor.
No new module, no new class, no change to `CycleContext`, no change to what gets imported from
`app.execution`.

**What would change:** purely mechanical - the same statements, in the same order, given the same
arguments, just named and called instead of inlined at their current call sites. This is already
mostly true today (these are already separate functions!) - so 4.1's actual scope, if you approve
it, would be narrower than originally sketched in REFACTOR_PLAN.md: likely limited to tightening
the boundary between "step 0" in `_process_agent_inner` (lines 483-488) and these three functions,
and/or extracting the small inline fill-application helpers (`_apply_fill_to_order`, `_cancel_order`,
lines 636-651) if they turn out to be reused in a way that benefits from relocation. I would confirm
the precise diff is that narrow (or report back if it turns out to be bigger) before writing any code.

**Verification gate before/after:** `tests/test_decision_loop_characterization.py` run unmodified;
`test_fixed_scenario_matches_the_captured_baseline` must still pass byte-for-byte. If it doesn't,
per REFACTOR_PLAN.md's explicit stop condition, Phase 4.1 halts and reports back rather than
proceeding to 4.2.

Awaiting your approval before writing any Phase 4.1 code.

---

## Phase 4.1 — Extraction performed

**Status: done. `decision_loop.py` changed; nothing else.**

### Exact extraction

The scope narrowed exactly as flagged when Phase 4.1 was proposed:
`_execute_pending_entry`, `_execute_pending_exit`, `_fill_entry` were already separate functions
and were **not** touched, reorganized, or duplicated. The only thing extracted was the 5-line
dispatch inside `_process_agent_inner` that decides *which* of them to call.

**Before** (`_process_agent_inner`, "step 0"):
```python
pending_entry = cc.pending.get(agent.id)
if position is not None and position.pending_exit_signal_time is not None:
    position = await _execute_pending_exit(cc, agent, dna, stage, position, decision)
elif position is None and pending_entry is not None:
    position = await _execute_pending_entry(cc, agent, dna, stage, pending_entry, decision)
```

**After**:
```python
position = await _execute_next_open_decisions(cc, agent, dna, stage, position, decision)
```
with the same 5 lines moved verbatim into a new function `_execute_next_open_decisions`
(placed beside `_execute_pending_entry`/`_execute_pending_exit`, in the file's existing
"Next-open execution" section), with an explicit `return position` for the fall-through case that
previously happened implicitly (neither `if` nor `elif` matched, so `position` was simply left
unchanged) - behaviorally identical, just made explicit since the value now has to be returned
rather than mutated in the enclosing scope.

### Files changed

| File | Change |
|---|---|
| `backend/app/agents/decision_loop.py` | 19 insertions, 5 deletions. One new function (`_execute_next_open_decisions`); one call site simplified from a 5-line inline dispatch to one call. No other line touched. |

Diff is 24 lines total - reviewed in full before running anything.

### Before/after responsibility

- **Before:** `_process_agent_inner` (the per-candle, per-agent orchestrator) directly encoded the
  priority rule "a pending exit always takes precedence over a pending entry" as part of its own
  body, interleaved with the other 8 responsibilities Phase 0 identified in that function.
- **After:** that priority rule is owned by `_execute_next_open_decisions`, a single-purpose
  function whose only job is "resolve what the previous bar's close decided." `_process_agent_inner`
  now reads as a flat sequence of numbered steps (0 through 5) that each delegate to one call,
  without needing to know *how* step 0 makes its choice.

### Verification

| Check | Result |
|---|---|
| Characterization test, immediately before the change (baseline) | 2 passed |
| Characterization test, immediately after the change | **2 passed** - `test_fixed_scenario_matches_the_captured_baseline` matched the Phase 4.0 golden snapshot exactly; no exclusion list changes, no snapshot edits |
| Full decision-loop-adjacent set (12 files, same set as Phase 4.0) | 97 passed (identical count to Phase 4.0's 97) |
| Full backend suite | `2 failed, 936 passed, 17 skipped, 2 xfailed in 393.95s` - **identical to the Phase 4.0 baseline in every number**; the 2 failures are the same pre-existing ones (`test_logging`, `test_secret_scan`) |
| Lint (`ruff check app/agents/decision_loop.py`) | Same pre-existing import-order findings as before this change (verified none are new, none are near the changed lines) |

None of the STOP conditions were triggered: the golden snapshot did not differ, no
trading/accounting state changed, idempotency/transaction/fencing/`LeaseLost` behavior is
untouched (this extraction never crosses a `db.begin_nested()`, `fence.check_local()`, or
`db.commit()` boundary - it sits entirely inside one agent's already-isolated processing), and no
new test failure appeared anywhere in the suite.

### Unexpected observations

None. This was the cleanest possible outcome: a byte-for-byte-identical golden snapshot and an
identical full-suite pass/fail count, which is exactly what a pure, behavior-preserving
extract-function refactor should produce.

**STOPPING here as instructed. Phase 4.2 has not been started and awaits your explicit approval.**

---

## Phase 4.2 — Extraction performed

**Status: done. `decision_loop.py` changed; nothing else.**

### Exact position-protection/management logic and its callers

Read the full logic before touching anything:
- `_manage_open_position` (funding accrual via `_accrue_funding`, liquidation-price recompute,
  level-trigger evaluation, extreme advancement, margin/equity update) and `_accrue_funding` were
  **already** single, shared functions with no duplication - confirmed by Phase 4.0's audit and
  re-confirmed here (both callers listed below call the exact same `_manage_open_position`).
- **Two callers**, both already funneling through that shared function:
  1. The normal per-agent path: `_process_agent_inner`, "step 1" (`if position is not None: if
     await _manage_open_position(...): return ...`).
  2. The mandatory protection sweep: `_protect_one` (called from `protect_open_positions`'s loop).

**The actual duplication found** was not in `_manage_open_position` itself, but in what each caller
does *after* it returns `False` (position survived the bar) - both then check "is the owner still
viable, and if not, force-close with which `(order_kind, exit_reason)`":
- `_process_agent_inner`: `if agent.status == AgentStatus.DEAD: _close_position(..., order_kind="liquidation", exit_reason="agent_death")`
- `_protect_one`: `if not closed and agent.status != AgentStatus.ACTIVE and position.is_open: _close_position(..., order_kind="liquidation" if DEAD else "market", exit_reason="agent_death" if DEAD else "orphan_resolution")`

The `(order_kind, exit_reason)` pairing for "DEAD" was spelled out as a literal in one place and as
half of a ternary in the other - a real, if narrow, duplication that would need to be kept in sync
by hand if it ever changed.

### Shared state / transaction / savepoint / fencing / idempotency review

- Both callers already run inside their own `db.begin_nested()` savepoint (per-agent in the normal
  loop, per-position in the sweep) - established **before** either reaches this code; unaffected.
- Neither caller's fencing (`fence.check_local()`) or `LeaseLost` handling is anywhere near this
  code - both are checked once per loop iteration, before the per-agent/per-position work begins.
- `Position.last_processed_open_time` idempotency is set inside `_manage_open_position` itself
  (untouched); `decided_ids` idempotency is upstream of both callers (untouched).
- `_close_position`'s own accounting (settlement, bad-debt recording, trade booking, cooldown) is
  untouched - only the two *arguments* passed to it (`order_kind`, `exit_reason`) are now computed
  via a shared function instead of inline.

### Smallest meaningful extraction boundary chosen

Given the constraint to preserve the two callers' behavioral differences exactly, **the extraction
touches only the WHAT (the order_kind/exit_reason mapping), never the WHETHER (each caller's own
condition for deciding to force-close)**. A closures-based unification of the conditions themselves
was considered and rejected as disproportionate risk for this phase - the two conditions differ for
a real reason (`_process_agent_inner` can only ever observe DEAD at this checkpoint, since an agent
entering that loop starts ACTIVE and can only transition to DEAD, never PAUSED, during it; `_protect_one`
must also handle PAUSED/RETIRED orphans from any generation) and unifying them would have required
passing behavior (not just data) across the boundary, adding risk without a corresponding reduction
in real duplication (the *conditions* were never duplicated - only the *reason mapping* was).

**New function**, placed immediately before `_protect_one` (same file):
```python
def _force_close_reason(agent: Agent) -> tuple[str, str]:
    if agent.status == AgentStatus.DEAD:
        return "liquidation", "agent_death"
    return "market", "orphan_resolution"
```
Both call sites now do `order_kind, exit_reason = _force_close_reason(agent)` and pass those
through to the unchanged `_close_position(...)` call. `_process_agent_inner`'s condition
(`agent.status == AgentStatus.DEAD`) and `_protect_one`'s condition (`not closed and agent.status
!= AgentStatus.ACTIVE and position.is_open`) are **byte-for-byte unchanged**.

### Files changed

| File | Change |
|---|---|
| `backend/app/agents/decision_loop.py` | This phase's increment: 1 new function (`_force_close_reason`, 15 lines incl. docstring); both call sites' inline literal/ternary replaced with a call to it (net: conditions unchanged, `_close_position` call sites unchanged except sourcing their two arguments from the shared function). |

### Callers affected

`_process_agent_inner` (normal per-agent path) and `_protect_one` (mandatory sweep) - both listed
above; no other caller of `_manage_open_position` or `_close_position` exists.

### Before/after responsibility

- **Before:** the mapping "what does force-closing a DEAD-owned vs. otherwise-non-viable-owned
  position look like" was implicit, spelled out independently at each of the two call sites.
- **After:** `_force_close_reason` is the single owner of that mapping. Each caller still owns -
  unchanged - the separate question of *whether* its specific situation warrants a force-close at
  all.

### Verification

| Check | Result |
|---|---|
| Characterization test, immediately before the change | 2 passed (Phase 4.1's confirmed baseline) |
| Characterization test, immediately after the change | **2 passed** - byte-for-byte match against the Phase 4.0 golden snapshot; not modified |
| All position-protection tests (`test_position_protection.py` + `test_margin_liquidation.py`, 23 tests - includes the specific DEAD-agent-orphan-resolution and liquidation-kills-agent tests this extraction most directly touches) | **23 passed** |
| Full decision-loop-adjacent set (same 12 files as Phase 4.0/4.1) | 97 passed (identical to Phase 4.1) |
| Full backend suite | `2 failed, 936 passed, 17 skipped, 2 xfailed in 395.39s` - **identical to the Phase 4.1 baseline in every number**; same 2 pre-existing failures |
| Lint (`ruff check app/agents/decision_loop.py`) | No new findings near the changed lines |

None of the STOP conditions were triggered: golden snapshot unchanged (and not edited to force a
pass), no DB/accounting/position state change, no idempotency/transaction/fencing/`LeaseLost`
change (this extraction never touches those mechanisms), no new test failure anywhere.

### Unexpected observations

One worth recording precisely, since it was the basis for the design decision above: the
"duplication" named in the phase brief turned out to be narrower on inspection than the phase name
suggested. `_manage_open_position`/`_accrue_funding` (the actual position-management mechanics)
were already fully shared with zero duplication - Phase 4.0's audit was correct about that. The
real, if small, duplication was specifically the post-management "what does an unviable owner's
force-close look like" mapping, which is what this phase extracted. No other position-protection
logic needed touching.

**STOPPING here as instructed. Phase 4.3 has not been started and awaits your explicit approval.**

---

## Phase 4.3 — Sizing/margin ownership investigation (no code changed)

**Status: done. Investigation and recommendation only. Nothing in the repository was modified.**

### 1. Current sizing/margin flow (complete lifecycle)

Traced every call site of `app.execution.sizing.*`, `app.execution.margin.margin_state`, and
`app.risk.risk_engine.check_trade` across the whole backend.

**Origination → transformation → consumption, inside `decision_loop.py::_process_agent_inner`
("step 4", priced at the signal bar's close - the only price known at decision time):**

1. `stop_distance_pct(dna, price, atr, swing_low, swing_high, side)` → fractional stop distance
   (pure function of DNA + market features).
2. `requested_notional(dna, equity, price, atr, stop_dist_pct)` → what the DNA *wants*, before any
   risk clamp; scaled by the council's `size_modifier` immediately after.
3. `margin_state(balance=agent.balance, maintenance_margin_rate=...)` → `available_margin` (flat-
   account form: no open position yet, so `equity == balance`).
4. `check_trade(RiskCheckInput(..., proposed_notional, available_margin, stop_distance_pct, ...))` →
   `RiskCheckResult(decision, approved_notional, approved_leverage, reasons)`. This is the **single
   enforcement point** for every hard and soft risk rule (drawdown, daily loss, leverage caps,
   exposure caps, risk-per-trade caps, council-incomplete fail-closed, halt reasons).
5. `approve_against_margin(risk_result.approved_notional, leverage, available_margin)` → caps the
   risk-approved notional a **second time** against the same `available_margin`, because
   `check_trade` itself doesn't know about margin sufficiency beyond what was passed in as a cap
   candidate - equity being positive is not sufficient justification for unlimited exposure.
6. `below_min_order_notional(approved, price)` → **decision-time replica of what the paper adapter
   will do at fill time** (lot-step rounding, then compare to the exchange minimum). If it would
   fail, the order is rejected *now*, with a reason, instead of being persisted and failing a bar
   later.
7. `build_sizing_result(method, requested, approved, leverage, price, stop_dist_pct)` → the final
   `SizingResult` (quantity, margin, risk_amount) that becomes the `Order` row's fields.

**Persistence:** every one of these values is written to `Order` (`requested_notional`,
`approved_notional`, `initial_margin`, `risk_amount`, `leverage`, `quantity`) and to
`Decision.risk_reasoning` (the full audit trail: reasons list, approved/requested notional, margin,
leverage, risk amount, sizing method, min-notional-if-relevant, the council audit). Nothing is
silently discarded - this is by design, per the architecture doc's audit requirements.

**Re-consumption later, same file:**
- `_fill_entry` (next-open fill, potentially a full bar after the decision): calls `margin_state`
  and `approve_against_margin` **again**, with the agent's **current** balance - because in
  next-open mode, funding or another event could have changed the balance between the decision and
  the fill. This is a deliberate re-validation, not leftover duplication.
- `_manage_open_position` (every bar an open position exists): calls `margin_state` **with position
  arguments** (side/quantity/entry_price/mark_price) for live mark-to-market, unrealized PnL,
  maintenance-margin, and liquidation checks. Structurally different call (position-bearing vs.
  flat-account) but the same pure function.

### 2. Current ownership

- `app/execution/sizing.py` (`stop_distance_pct`, `requested_notional`, `approve_against_margin`,
  `below_min_order_notional`, `build_sizing_result`): pure, stateless, imports only
  `app.core.config.get_settings` and `app.schemas.strategy_dna.StrategyDNA`. No DB, no Agent model,
  no execution-adapter dependency.
- `app/execution/margin.py` (`margin_state`): pure, stateless, imports only
  `app.analytics.pnl_engine` and `app.models.enums.Side`.
- `app/risk/risk_engine.py` (`check_trade`): pure, stateless, imports `app.models.agent.Agent` (for
  `peak_equity`/`starting_balance` - duck-typeable, see below) and `app.schemas.strategy_dna`. This
  is explicitly documented as "the final safety authority before execution" and "Ollama cannot
  override this."
- **The ORCHESTRATION** (the specific sequence above, steps 1-7, and writing results into
  `Decision`/`Order`) lives in `decision_loop.py` and **nowhere else in the live/paper/shadow path**.

### 3. Dependencies

- Sizing/margin/risk are each individually pure functions - no dependency on execution adapters,
  no dependency on the DB, no dependency on `ExecutionEngine`.
- `decision_loop.py` is the only module that threads `agent` (a real ORM row), `cc` (`CycleContext`:
  market data, council context, global risk limits), and `decision` (the audit row) through this
  sequence simultaneously - none of the three pure modules could do this orchestration themselves
  without importing `Agent`/`Decision`/`CycleContext`, which would be the actual `domain →
  infrastructure`-reversed coupling the refactor is trying to avoid, not fix.
- **A second, independent caller of the same pure functions exists**: `app/backtesting/engine.py`
  calls `margin_state`, `stop_distance_pct`, `requested_notional`, `approve_against_margin`, and
  `check_trade` directly, in its **own**, separately-written sequence (lines ~306-367) - notably
  *without* `build_sizing_result` or `below_min_order_notional` (the backtester has no paper-adapter
  fill mechanics to pre-empt). This is real duplication - of the *orchestration recipe*, not the
  underlying math - see §5.
- **An existing adapter pattern already solves an adjacent version of this problem**:
  `app/backtesting/risk_adapter.py::backtest_risk_check` wraps `check_trade` behind a duck-typed
  `_SyntheticAgentState` (only `peak_equity`/`starting_balance`/`equity` are read) so the backtester
  - which has no real `Agent` DB row - can call the **exact same** risk rules without reimplementing
  them. This is the codebase's own precedent for "share a pure rule engine across live and backtest
  without merging their orchestration": one thin, context-specific adapter per shared function, not
  a unified pipeline. Notably, no equivalent adapter exists for the *sizing* functions - the
  backtester calls them directly, because they need no Agent-shaped input to begin with.

### 4. Existing invariants (why the code is where it is)

- **The `below_min_order_notional` decision-time check is the direct fix for a real, documented
  production incident**: `tests/test_min_notional_decision_time.py`'s own module docstring records
  that "3,469 of ~4,900 entry orders (~70%) were approved by the Risk Engine, persisted as PENDING,
  then FAILED at the next bar's open" before this check existed - each leaving a dangling `FAILED`
  order and a `Decision` mislabelled REJECTED with no reason. `test_check_mirrors_the_adapter_lot_rounding`
  proves the decision-time check's lot-rounding arithmetic is kept byte-identical to
  `PaperExecutionAdapter`'s own rounding, by design, specifically so "the decision and the later
  fill can never disagree" (the function's own docstring, verbatim). This is objective 4(e) exactly:
  **deliberately located in decision_loop.py because moving it away from the order-creation decision
  would reopen the exact bug this code was written to close.**
- **Fill-time margin re-validation** (`_fill_entry`'s own `margin_state`/`approve_against_margin`
  call) exists because next-open timing means a bar's worth of real events (funding, another
  agent's trade - no, per-agent this is single-position, but funding certainly) can pass between
  the decision and the fill; re-checking against the *current* balance right before committing to a
  fill is a correctness requirement, not an accident.
- **Live/backtest parity** (`docs/architecture.md`: "applied by the live loop and the backtester
  with the same code") is proven by `tests/test_live_backtest_parity.py` (an expensive, ~80-second
  multi-scenario test suite). Any change to the sizing/margin/risk *sequence* in `decision_loop.py`
  risks silently diverging from `backtesting/engine.py`'s independent copy of that sequence unless
  both are changed together and the parity suite is re-run.
- **SAVEPOINT/idempotency/fencing**: none of steps 1-7 touch the database, open a savepoint, or
  interact with fencing - they run entirely inside the already-open per-agent savepoint, before any
  `Order`/`Decision` row is even added to the session. Moving this logic to a different module would
  not change any transaction boundary, since none of it currently crosses one.

### 5. Architectural problem, if any

**(a) appropriate** for the pure math (sizing.py, margin.py, risk_engine.py already live in the
right, correctly-decoupled places) and **(e) deliberately located there** for the orchestration
itself (decision_loop.py needs `Agent`+`CycleContext`+`Decision` together, and the decision-time
min-notional check is a proven bug fix that depends on running *before* order persistence).

**There is real duplication - but it is not inside `decision_loop.py`, and not between
`decision_loop.py` and any execution adapter.** It is between `decision_loop.py` and
`app/backtesting/engine.py`: both independently hand-write the same "stop-distance → requested
notional → margin state → risk check → margin-approve" sequence, calling the same pure functions in
almost - but not exactly - the same order and with different final steps (paper's
`build_sizing_result`/`below_min_order_notional` have no backtest equivalent). This is a **live vs.
backtest parity-architecture question**, not a `decision_loop.py` internal-coupling question - it is
outside what "extract sizing/margin out of decision_loop.py" would even address, since extracting it
to somewhere in `app/execution/` would not automatically make `backtesting/engine.py` use the
extraction unless that file were *also* changed, which is a materially larger, separately-scoped
change touching the system's most heavily parity-tested surface.

**No mixing of orchestration with domain logic (d) was found** beyond what is inherent to
`decision_loop.py`'s job description (it *is* the orchestrator; reading `agent.equity`,
`dna.position_sizing`, and `cc.council.size_modifier` in one place to build one `RiskCheckInput` is
what orchestration means here, not a violation of it).

### 6. Would moving this logic change trading behavior?

**Yes, almost certainly, if it were moved carelessly** - not because the math would change, but
because of the two proven timing-sensitive invariants above: (1) the min-notional check must run
*before* the `Order` row is persisted, in the same synchronous decision path, or the original
70%-failure-rate bug reopens; (2) the fill-time margin re-check in `_fill_entry` must read the
agent's balance *as of the fill*, not the decision - any extraction that cached or hoisted these
values earlier than their current call sites would silently reintroduce stale-margin behavior.
Extracting the pure math functions themselves would change nothing (they're already extracted);
extracting the *sequencing* is where the risk lives.

### 7. Candidate extraction boundary, if justified

**None identified inside `decision_loop.py` that meets the bar this refactor has held itself to in
Phases 4.1/4.2** (a real, provable duplication with a safe, narrow boundary). The one real
duplication found (§5) is cross-file with `backtesting/engine.py`, and the smallest safe boundary
for *that* - if it were ever pursued - would follow the codebase's own established pattern
(`backtest_risk_check`-style thin adapters, one per shared function/step) rather than a merged
pipeline, and would need `tests/test_live_backtest_parity.py` as its primary gate. That is a
different, larger initiative than "Phase 4: decision_loop.py," not a sub-step of it.

### 8. Alternative approaches considered

- **A `SizingService`/`RiskPreparationService` class wrapping steps 1-7**: rejected. It would need
  to accept `agent`, `cc`, and `decision` anyway (nothing about the sequence is context-free), so it
  would either (i) live in `app/agents/` next to `decision_loop.py` - a rename, not an extraction,
  since `decision_loop.py` would still own and call it with the same data - or (ii) live under
  `app/execution/` and import `Agent`/`Decision`/`CycleContext` to do so, which is the exact
  `domain → infrastructure` direction reversal REFACTOR_PLAN.md's target architecture forbids.
- **Moving `below_min_order_notional`'s check into `PaperExecutionAdapter` only, removing it from
  decision-time**: rejected outright - this is precisely the bug `test_min_notional_decision_time.py`
  exists to prevent from recurring; it would reopen the ~70%-of-orders failure mode by design.
- **A shared `plan_entry(...)` used by both `decision_loop.py` and `backtesting/engine.py`**:
  the only alternative that would address the *actual* duplication found. Not pursued in this
  investigation because it is out of Phase 4's declared scope (`decision_loop.py` only) and because
  its blast radius (§9) is materially larger than anything Phase 4.1/4.2 touched.

### 9. Risk assessment

| Option | Risk |
|---|---|
| Extract sizing/margin orchestration out of `decision_loop.py` into `app/execution/` | High - reverses the target dependency direction (execution would need to import Agent/Decision/CycleContext), and risks the two proven timing invariants in §6 |
| Extract into a new `app/agents/` sibling module, called from `decision_loop.py` | Low technical risk, but **zero architectural benefit** - it would be the same coupling under a new file name, not a boundary; fails "do not introduce a new abstraction merely for architectural aesthetics" |
| Unify `decision_loop.py` and `backtesting/engine.py`'s orchestration (the one real duplication) | Medium-high - touches the system's most heavily parity-tested surface (`test_live_backtest_parity.py`, ~80s, multiple DNA scenarios); genuinely valuable but not a Phase 4 sub-step |
| Do nothing | None - current behavior, current tests, current architecture all remain exactly as they are and already pass |

### 10. Expected blast radius

Zero, because no extraction is recommended for Phase 4.4. If the cross-file duplication (§5) were
ever addressed as its own initiative, its blast radius would touch `decision_loop.py`,
`backtesting/engine.py`, `backtesting/risk_adapter.py`, and the full `test_live_backtest_parity.py`
suite at minimum - explicitly out of scope for "Phase 4: decision_loop.py."

### 11. Explicit recommendation: Phase 4.4 should NOT proceed as originally scoped

**No extraction of sizing/margin out of `decision_loop.py` is justified.** The current location is
correct under objective 4's own categories - **(a) appropriate** for the pure functions (already
properly factored into `app/execution/sizing.py`, `app/execution/margin.py`,
`app/risk/risk_engine.py`) and **(e) deliberately located** for the orchestration sequence itself,
which is backed by a documented production-incident fix and a real fill-time re-validation
requirement, neither of which would survive being relocated without re-engineering the very
invariants they exist to protect.

The one genuine architectural finding from this investigation - duplicated orchestration between
`decision_loop.py` and `backtesting/engine.py` - is real but belongs to a different, larger,
separately-scoped initiative (live/backtest parity architecture), not to "Phase 4: decision_loop.py
extraction." I'd recommend closing Phase 4 at this point rather than manufacturing a Phase 4.4
extraction where none is warranted - matching Phase 4.1's own precedent of reporting "the available
diff is narrower than expected" rather than extracting for its own sake.

**No code was changed, no tests were changed, no configuration was changed. Awaiting your decision
on whether to close Phase 4 here or open the cross-file live/backtest duplication as its own,
separately-scoped initiative.**

---

## Phase 4 — CLOSED

**Decision:** Phase 4.3's investigation is accepted as conclusive. No safe or meaningful extraction
of sizing/margin orchestration from `decision_loop.py` is justified. **Phase 4.4 will not be
opened.**

- Phase 4.3 is complete: investigation and recommendation only.
- No production code was changed by Phase 4.3 - confirmed by `git status` showing no diff beyond
  what Phases 4.1 and 4.2 already produced.
- No Phase 4.4. The sizing/margin extraction originally sketched in REFACTOR_PLAN.md's Phase 4 item
  4.3/4.4 does not proceed.
- **Sizing/margin orchestration intentionally remains in `decision_loop.py`.** The pure functions it
  calls (`app/execution/sizing.py`, `app/execution/margin.py`, `app/risk/risk_engine.py`) are
  already correctly factored and are not touched; the orchestration sequencing them is
  `decision_loop.py`'s own responsibility, not a coupling defect.
- **Decision-time minimum-notional validation (`below_min_order_notional`) must remain at
  order-creation time**, before the `Order` row is persisted - this is the proven fix for the
  documented ~70%-of-entry-orders production incident (`tests/test_min_notional_decision_time.py`)
  and must never be moved to fill time or any later point.
- **Fill-time margin validation (inside `_fill_entry`) must remain at fill time**, re-checked
  against the agent's balance as of the actual fill (not the decision, which in next-open mode can
  be a full bar earlier) - this is a correctness requirement, not redundant duplication.
- **The cross-file duplication between `decision_loop.py` and `app/backtesting/engine.py`'s
  independently-written sizing/margin/risk orchestration is real, but is a separate future
  initiative** (live/backtest parity architecture), explicitly out of scope for Phase 4 and not
  started.

**Files left unmodified, per instruction, and confirmed unmodified by this closure:**
`app/agents/decision_loop.py`'s sizing orchestration (the extraction performed in 4.1/4.2 stands;
the sizing/margin block itself was never touched in any phase), `app/execution/sizing.py`,
`app/execution/margin.py`, `app/risk/risk_engine.py`, `app/backtesting/engine.py`,
`app/backtesting/risk_adapter.py`.

**No new refactoring will begin until explicitly instructed.**

### Summary of everything Phase 4 actually changed

For reference, the complete, final diff surface from Phases 4.1-4.2 (4.0 and 4.3 added tests/docs
only, no production code):

| File | Phase | Change |
|---|---|---|
| `app/agents/decision_loop.py` | 4.1 | `_execute_next_open_decisions` extracted from `_process_agent_inner`'s step 0 |
| `app/agents/decision_loop.py` | 4.2 | `_force_close_reason` extracted, shared by `_process_agent_inner` and `_protect_one` |

Both extractions are pure, behavior-preserving, verified byte-for-byte against the Phase 4.0
characterization baseline, with zero change to the full backend suite's pass/fail counts across
every verification run.
