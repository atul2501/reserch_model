# Refactor Plan — Phase 0 Analysis

Status: **analysis only, no code changed.** Produced per the Phase 0 brief: inspect first, plan
second. Every claim below is grounded in the actual codebase (agents read real files; a local,
code-only Graphify graph was rebuilt and cross-checked against the god-node list supplied) —
not generic advice.

Baseline test suite (unchanged by this document): **922 passed, 17 skipped, 2 xfailed, 3 failed**
(`.venv/bin/python -m pytest -q`, full backend suite). The 3 failures are pre-existing and
unrelated to architecture: a flaky event-loop-stall timing assertion, a logging-redaction format
test, and `test_secret_scan.py` correctly flagging that `backend/.env` was committed in the past
(already documented and partially remediated in `docs/security.md`). None of the phases below may
introduce *new* failures beyond this baseline.

---

## 1. Current architecture (as it actually is, not as the graph implies)

`docs/architecture.md` is an unusually good, current architecture doc — read it before this plan;
this document does not repeat it, only extends it with coupling/testability analysis it doesn't
cover. Headline facts that shape every phase below:

- **Three processes, one database, never call each other**: `scripts.run_cycle` (trading),
  `scripts.run_research` (evolution), `uvicorn app.main:app` (API/dashboard). `app/main.py` builds
  the FastAPI app at import time and does **not** run the trading loop — that's a separate process.
- `backend/app/` is already domain-partitioned into 16 packages (`agents`, `analytics`, `api`,
  `backtesting`, `core`, `council`, `evolution`, `execution`, `market`, `models`, `research`,
  `risk`, `schemas`, `services`, `strategies`, `worker`) — this is not a flat or accidental
  structure.
- An `ExecutionEngine` **port already exists** (`app/execution/base.py`) with three real
  implementations (`PaperExecutionAdapter`, `ShadowExecutionAdapter`,
  `HyperliquidLiveExecutionAdapter`, selected by `app/execution/router.py`). Live execution
  deliberately raises `NotImplementedError` behind five safety gates — see `docs/security.md`
  and `tests/test_no_live_orders.py`, which **must never be weakened**.
- Market data already has a real adapter boundary: `HyperliquidClient`/`hyperliquid_ws.py` are the
  only Hyperliquid-shape-aware code; `MarketDataService` normalizes into domain rows
  (`MarketCandle`, `FundingRate`); nothing else touches raw Hyperliquid payloads.
- AI has the same shape: `OllamaClient` is "the ONLY place allowed to call the Ollama API," with
  all failure handling (401/403 key rotation, 429 backoff, timeout, malformed-JSON, fail-closed)
  centralized inside it.
- `Agent`, `StrategyVersion`, `Strategy` are pure SQLAlchemy data models — no execution/AI/exchange
  imports, no behavior beyond immutability guards (DB triggers + ORM `before_update` events).
  Lifecycle transitions (birth/death/retirement) live in `app/agents/lifecycle.py`.
- No repository layer exists anywhere; ~26 modules take `db: AsyncSession` as a plain parameter,
  supplied by `get_db()` (FastAPI DI) or `session_scope()` (background processes). This is a
  deliberate, appropriate choice at this scale, not an oversight.
- Tests: flat `backend/tests/` directory, ~99 files, no subfolders.

## 2. Correcting the premise: what the god-node list actually means

The supplied Graphify numbers were reproduced exactly (287 files, 3522 nodes, 13506 edges, 119
communities; same top-10 hotspot list). But **high edge count is not evenly meaningful across
these ten nodes** — inspection splits them into three very different categories:

| Node | Edges | What the edges actually are |
|---|---|---|
| `make_agents()`, `make_dna()`, `Side`, `StrategyStage` (partly), `make_context()`'s test variant | 120–143 | **Test-fixture fan-out.** `make_context`/`make_dna`/`make_agents` are defined in `tests/helpers_agents.py` — they are not production code at all. Their edge count reflects ~99 test files reusing shared fixtures (healthy test coverage), not architectural coupling. Refactoring these for "coupling" would break widely-shared test infrastructure for zero behavioral gain. |
| `get_settings()` | 226 | **Shallow fan-out, not a god object being threaded through.** 62 call sites across ~30 files each read 1–9 narrow, subsystem-relevant fields locally (e.g. `paper_adapter.py` reads 3 paper-execution fields; `hyperliquid_client.py` reads 1). Nobody holds and passes around the whole `Settings` object. The graph counts every field read as an edge to the same singleton node, inflating the number without reflecting a single bad call site. |
| `PaperExecutionAdapter`, `Agent`, `StrategyDNA`, `StrategyVersion`, `Trade`, `Position`, `Decision`, `Order` | 82–171 | **Real domain nodes with legitimately many relationships** (an `Agent` really does relate to trades, positions, decisions, orders — that's the domain, not a defect). The one genuine finding here is *how* they're reached, covered in §3. |

This matters for scope: **do not treat all ten as equally broken.** The real, worthwhile targets
are narrower than the raw numbers suggest.

## 3. Actual coupling problems found (the real targets)

Ranked by value/risk, not by edge count:

1. **`app/agents/decision_loop.py` (955 lines) is a genuine hotspot.** `run_decision_cycle()` and
   `_process_agent_inner()` orchestrate 8–9 distinct concerns in one place: cycle
   query-batching, the mandatory position-protection sweep, next-open fill execution mechanics,
   position management (funding/stop/TP/trailing/liquidation), the signal→council→risk→sizing
   pipeline, order/trade/PnL persistence, agent lifecycle updates, decision audit rows, and
   savepoint/idempotency/fencing. It correctly calls the *abstract* `ExecutionEngine.submit_order()`
   (the port boundary is respected) but also reaches **past** that port directly into execution's
   internals — `execution.fillmodel.{fee_rate_for,slipped_price,slippage_bps}`,
   `execution.margin.margin_state`, `execution.sizing.*`, `execution.paper_adapter.new_client_order_id`
   — meaning the decision loop depends on execution's implementation details, not just its contract.
   High value to untangle, but also the highest-risk file in the codebase (idempotency, savepoint
   isolation, fenced commits are all load-bearing and tested) — scheduled **last**, in small steps.

2. **`app/agents/lifecycle.py::retire_generation()` has one deferred inline import**
   (`from app.execution import accounting`, function-local) to force-close positions at generation
   rollover. This is domain code reaching into execution internals, exactly the
   `domain → infrastructure` direction the brief wants avoided. Small, single call site, low risk.

3. **`app/council/service.py` depends on the concrete `OllamaClient` class**, not an abstract
   interface — there is no `AIClientPort` today. `OllamaClient`'s internals (key rotation, retry,
   fail-closed logic) are exactly right and must not change; this is purely about the *type* the
   council layer names in its dependency, not the implementation.

4. **`Settings` is one flat `BaseSettings` with ~150 fields.** Not a crisis (per §2), but it does
   mean every long-lived service class (`OllamaClient`, `HyperliquidClient`, `MarketDataService`,
   the execution adapters) currently calls the global `get_settings()` singleton *inside* its own
   constructor/methods rather than receiving config explicitly — which is the actual testability
   cost (tests must monkeypatch a global rather than construct a fake config). The codebase already
   has the right pattern in two places (`FitnessWeights.from_settings()`,
   `PromotionCriteria.from_settings()` — narrow, named dataclasses built from `Settings`) — this is
   extension of an existing pattern, not invention of a new one.

5. **Test suite is flat** (~99 files, no subfolders). Cosmetic; pytest doesn't care functionally.
   Only worth doing as a pure `git mv` pass late, if at all — real risk (broken relative imports,
   CI path assumptions) for no behavioral benefit. Deprioritized per the brief's own caution
   ("do not move hundreds of tests blindly").

## 4. Proposed target architecture

Not a rewrite toward a textbook layered architecture — the existing package boundaries
(`agents`/`execution`/`market`/`council`/`evolution`/`risk`) already express the right domains. The
target is narrower: close the specific `domain → infrastructure` leaks found in §3, and make the
existing config/port patterns (already used correctly in 2–3 places) consistent for the handful of
long-lived service classes where it actually helps testing. Concretely:

```
domain (agents/, models/, schemas/, strategies/)
   -> depends on -> ports (execution.base.ExecutionEngine, a new council AI port)
   -> never depends on -> execution internals, OllamaClient concretely, Hyperliquid payloads

application/orchestration (worker/, council/, evolution/, research/)
   -> depends on -> domain + ports
   -> receives config as narrow objects, not global get_settings() lookups, where it's a
      long-lived class (not a one-shot function reading 1-2 fields)

infrastructure (market/hyperliquid_client.py, services/ollama_client.py, execution/*_adapter.py)
   -> implements -> the ports
   -> owns exchange/LLM-specific shapes, never leaks them upward (already true today)
```

## 5. Migration phases (revised order — risk-ascending, not the original numbering)

Each phase: smallest safe change, run the affected tests, run the full suite before moving on, no
new failures beyond the documented baseline.

| # | Phase | Files touched (approx.) | Risk |
|---|---|---|---|
| 1 | Add `AIClientPort` Protocol; `council/service.py` depends on the Protocol, `OllamaClient` satisfies it structurally (no change to `OllamaClient` itself) | `app/council/service.py` + 1 new file | Very low |
| 2 | Fix `lifecycle.py::retire_generation()`'s deferred import — route position-closing through the `ExecutionEngine` port instead of `execution.accounting` directly | `app/agents/lifecycle.py` | Low |
| 3 | Introduce 2–3 narrow config dataclasses (`OllamaConfig`, `HyperliquidConfig`) built `.from_settings()`-style, for the handful of long-lived service classes' constructors; leave the ~50 inline single-field `get_settings()` reads untouched | `app/services/ollama_client.py`, `app/market/hyperliquid_client.py`, `app/core/config.py` (add factory methods only) | Low-medium |
| 4 | Extract 1–2 clearly-bounded regions of `decision_loop.py` into named functions/modules *without changing control flow, savepoint boundaries, or commit points* — candidates: next-open fill execution mechanics, position-protection sweep | `app/agents/decision_loop.py` | Medium-high (do in isolation, one region at a time, full suite between each) |
| 5 (optional) | Mechanical test-directory reorganization (`git mv` only, verify collection count unchanged) | `backend/tests/` | Low effort, low value — do last, only if time permits |

Phases explicitly **not recommended**: rewriting `PaperExecutionAdapter`/`ShadowExecutionAdapter`/
`HyperliquidLiveExecutionAdapter` into an `ExecutionPort` hierarchy — it already exists. Splitting
`Settings` into fully separate `BaseSettings` classes — would touch all 62 call sites for a cosmetic
win over the narrow-factory approach in Phase 3. Building a repository layer — no evidence it's
needed at this scale (per the brief's own instruction not to build one without a meaningful
boundary).

## 6. Risks

- `decision_loop.py` is the highest-risk file in the repo: idempotency (`worker_cycles.cycle_id`,
  unique `(agent_id, candle_open_time)`), SAVEPOINT-per-agent isolation, fenced commits (lease
  epoch re-verified inside the transaction), and the mandatory post-loop protection sweep are all
  tested invariants (`docs/architecture.md` §2, §8). Any change here risks silently breaking one of
  these without a visible test failure if not scoped narrowly.
- `tests/test_no_live_orders.py` and the five-gate live-trading lockout must not be touched or
  weakened by Phase 1/3's port work — verify it still passes after every phase, not just at the end.
- `tests/test_shadow_fitness.py` enforces that shadow fitness cannot influence production selection
  by inspecting imports of breeding/mutation/champion modules — any import restructuring in those
  modules must keep this test meaningful (not accidentally pass because the import moved out of
  what it scans).
- Config Phase 3 touches files imported almost everywhere (`app/core/config.py`) — even additive
  changes (new factory methods) risk import-order/circular-import issues; run the full suite, not
  just the affected module's tests.

## 7. Behavior that must remain unchanged (explicit checklist for every phase)

- Fill timing (next-open fill), slippage/fee/latency/partial-fill/reject models, the $10 minimum
  notional, deterministic-per-order-id randomness.
- OHLC conservative-ambiguity rule (adverse before favourable), trailing-stop same-bar-extreme rule.
- Margin/liquidation formulas, funding accrual, bad-debt floor-at-zero accounting.
- Idempotency: `worker_cycles.cycle_id`, unique `(agent_id, candle_open_time)` decisions,
  deterministic `client_order_id`, one-open-position-per-agent partial index, atomic worker lease.
- Agent lifecycle: ACTIVE→DEAD (permanent)→RETIRED transitions, death reason/timestamp/equity
  freezing, milestone ratcheting.
- OOS lockbox sealing/immutability (ORM guard + DB triggers), evaluate-once-per-version constraint.
- Champion/challenger staging, promotion evidence gates, fitness formula (components/weights).
- Council quorum/fail-closed semantics, Ollama key-health/retry/cooldown behavior.
- Live trading remaining fully blocked (`tests/test_no_live_orders.py` green, all five gates intact).
- Every existing API contract, DB schema, and environment-variable name.

## 8. What Phase 0 deliberately does not conclude

- Whether `sizing`/`margin` pre-computation belongs in `decision_loop.py` (pre-execution, arguably
  decision-side) or should move fully behind the execution port is left open — needs a closer read
  of `app/execution/sizing.py` and `margin.py` call patterns before proposing a move, to avoid
  guessing at a boundary that risk-checking legitimately needs pre-submission.
- No community-cohesion or bridge-node analysis was run yet (`graphify cluster-only` /
  `diagnose multigraph`) — worth running once Phase 1–2 land, to get a real before/after comparison
  rather than re-quoting the same baseline numbers.

---

**Next step**: your go-ahead on Phase 1 (the AI port) and Phase 2 (the lifecycle import fix) —
both are small, reviewable, low-risk, and independently testable. I'd hold Phase 3 (config) and
Phase 4 (decision_loop) for separate approval given their wider blast radius.
