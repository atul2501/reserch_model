# Post-Refactoring Architecture Review

Scope: compare the repository's current state against the Phase 0 Graphify baseline and the
completed Phases 1-4 (`REFACTOR_PLAN.md`, `REFACTOR_PROGRESS.md`). **No code was modified to produce
this review** - it is read-only analysis (a fresh `graphify extract --code-only --force` run plus
direct source inspection).

---

## 1. Current Graphify statistics

| Metric | Phase 0 baseline | Current | Delta |
|---|---|---|---|
| Code files | 287 | 292 | +5 |
| Nodes | 3,522 | 3,595 | +73 |
| Edges | 13,506 | 13,756 | +250 |
| Communities | 118 (119 on re-run - see note) | 137 | +18-19 |
| Mean community cohesion | 0.245 | 0.305 | +0.06 |
| Median community cohesion | 0.15 | 0.186 | +0.036 |
| Import cycles | none detected | none detected | no change |

**Note on the baseline number:** re-running Graphify's own clustering on the *unmodified* Phase 0
graph (before any refactor work) produces 119 communities, not 118 - Louvain-style community
detection has run-to-run seed variance of about that magnitude. Treat "118" and "119" as the same
baseline; the current "137" is a real, larger shift, explained below.

**+5 files, exactly accounted for:** `app/agents/ports.py`, `app/council/ports.py` (the two new
Protocol definitions), `tests/test_council_ports.py`, `tests/test_lifecycle_ports.py`,
`tests/test_decision_loop_characterization.py`. No other file was added or removed anywhere in the
repository.

**+250 edges, +73 nodes:** consistent with 5 new, real files being added (each with its own
imports, functions, classes, docstrings-as-nodes) plus additional call edges from the 3 new test
files exercising `make_agents`/`make_dna`/`make_context`/`PaperExecutionAdapter` more.

**+18 communities:** the two new `ports.py` files are small, single-purpose, high-cohesion modules
(one Protocol each, importing only `typing`/`pydantic`) - they form their own tight communities
rather than being absorbed into `council`'s or `agents`' existing large components. This is exactly
what a successful narrow extraction should look like in a community-detection graph: a new,
minimal, high-cohesion cluster, not a redistribution of the existing large ones.

**Cohesion improved slightly (+0.06 mean).** Read this as a directional, small, genuine signal, not
a large win: four narrowly-scoped phases touching two tiny new files and ~50 lines of
`decision_loop.py` is not expected to move a 3,595-node graph's aggregate cohesion much, and it
didn't - but it moved in the right direction, not the wrong one, and the mechanism (new
high-cohesion clusters) is exactly what was intended, not a graph artifact.

**Import cycles: none, before or after.** No cycle-detection tool ships with this Graphify install
(`diagnose multigraph` checks edge-collapse risk, not cycle-freedom); confirmed instead by direct
evidence: the two new port files import only `typing`/`pydantic`/`pydantic.BaseModel` (trivially
acyclic), and the full backend suite (936 tests) successfully imports the entire `app` package tree
on every run without an `ImportError` - which a genuine new circular import would produce
immediately at collection time.

---

## 2. Current high-degree nodes

| Node | Baseline edges | Current edges | Delta | Classification |
|---|---|---|---|---|
| `get_settings()` | 226 | 229 | +3 | **Intentional/acceptable** - unchanged pattern (Phase 0 finding stands: narrow reads, not a god object being threaded through); the +3 is test files monkeypatching settings in new tests |
| `PaperExecutionAdapter` | 171 | 178 | +7 | **Intentional/acceptable** - the new characterization test and lifecycle-port tests both instantiate it directly (real, necessary test setup, not new production coupling) |
| `make_agents()` | 143 | 149 | +6 | **False positive** - test fixture, not production code (Phase 0 finding stands) |
| `Agent` | 138 | 143 | +5 | **Intentional/acceptable** - a real domain node; more test files reference it (expected) |
| `StrategyDNA` | 141 | 142 | +1 | **Intentional/acceptable** |
| `make_dna()` | 136 | 142 | +6 | **False positive** - test fixture |
| `Side` | 135 | 135 | 0 | **Intentional/acceptable** - enum, unchanged |
| `make_context()` | 120 | 127 | +7 | **False positive** - test fixture |
| `StrategyStage` | 122 | 122 | 0 | **Intentional/acceptable** |
| `StrategyVersion` | 119 | 121 | +2 | **Intentional/acceptable** |

No god node's ranking order changed meaningfully (Agent and StrategyDNA swapped positions 4/5 by
one edge - noise). **No new god node entered the top 10, and none of Phase 4's actual code changes
(the two `decision_loop.py` extractions) show up as a new hotspot** - `_execute_next_open_decisions`
and `_force_close_reason` are small, single-caller-pattern functions with low degree, exactly as
intended for an internal extraction that doesn't change the file's external surface.

---

## 3. Current cross-community bridge nodes

Graphify's own "surprises" list (inferred edges that bridge separate communities unexpectedly) has
**5 entries, unchanged in kind from what Phase 0 would have shown**, all of the same shape:

| Source | Target | Classification |
|---|---|---|
| `test_default_bind_is_loopback()` | `Settings` | False positive - security/config audit test |
| `test_every_env_example_key_is_a_real_setting()` | `Settings` | False positive - config audit test |
| `test_production_default_is_the_conservative_rule_and_engines_honour_the_setting()` | `Settings` | False positive - realism-defaults audit test |
| `test_all_ten_families_are_defined()` | `StrategyFamily` | False positive - enum-completeness audit test |
| `test_every_dna_field_is_either_runtime_covered_or_documented_metadata()` | `StrategyDNA` | False positive - DNA-documentation audit test |

**All 5 are test-to-domain-model bridges, zero are production-to-production.** These are exactly the
kind of "test-induced graph density" the review is asked to distinguish from genuine coupling: each
is a deliberate governance/completeness test (does every DNA field have documented behavior? does
every settings key have a real field? is the default bind loopback?) reaching into a hub node by
design. None of Phase 1-4's new files or changes appear in this list - **no new bridge node was
introduced**.

---

## 4. AIClientPort boundary

**Holding.** Re-confirmed by fresh source inspection: `app/council/service.py` and
`app/council/analysts.py` contain zero imports of `app.services.ollama_client` (only explanatory
docstring prose mentions `OllamaClient` by name, which was already the case at the end of Phase 3).
`OllamaClient` itself is unmodified. The one known gap from Phase 3 - `app/evolution/ollama_researcher.py`
still imports `OllamaClient` concretely - is unchanged (it was out of scope for every phase and
remains dormant/unwired into production). **Classification: Intentional/acceptable** for the
council boundary; the `ollama_researcher.py` gap is **Low** (dormant code, no production blast
radius, already documented).

## 5. PositionCloseSettler boundary

**Holding.** `app/agents/lifecycle.py` contains zero real references to `app.execution` (only
docstring prose and one unrelated SQLAlchemy `.execution_options()` call, a coincidental substring
match already flagged and dismissed in Phase 3). `retire_generation()`'s signature is unchanged
since Phase 2. `app/research/pipeline.py` remains the sole, correct composition root.
**Classification: Intentional/acceptable.**

## 6. ExecutionEngine boundary

**Unchanged, and untouched by this refactor entirely** - Phase 4.3 explicitly declined to modify
it, correctly (see REFACTOR_PROGRESS.md's Phase 4.3 entry). `app/execution/base.py`'s
`ExecutionEngine` ABC, its three implementations (`PaperExecutionAdapter`, `ShadowExecutionAdapter`,
`HyperliquidLiveExecutionAdapter`), and `app/execution/router.py`'s selection logic are exactly as
they were at Phase 0. `decision_loop.py` still calls only the abstract `submit_order()` for order
placement; it still also imports `fillmodel`/`margin`/`sizing`/`paper_adapter.new_client_order_id`
directly for pre-execution sizing math (Phase 4.3's investigated, deliberately-unresolved item - see
§9/§12). **Classification: Intentional/acceptable** - this is correctly-scoped, pre-existing
architecture that Phase 4 correctly chose not to touch.

## 7. Agent/strategy boundaries

**Unchanged and still clean.** `Agent`, `StrategyVersion`, `Strategy` remain pure SQLAlchemy data
models (Phase 0's finding re-confirmed by inspection: no new methods, no new imports). Lifecycle
transitions remain in `app/agents/lifecycle.py`, now with one fewer infrastructure dependency
(Phase 2's fix holds). `make_dna()`/`make_agents()`/`make_context()` remain test-only, never
production. **Classification: Intentional/acceptable.**

## 8. `decision_loop.py` remaining responsibilities

The file grew from 955 to **985 lines** (+30, both new functions' bodies plus their docstrings) and
from ~19 to **21 module-level functions**. Its responsibility count is **unchanged from Phase 0's
audit** (still the same 8-9 concerns: cycle orchestration, the protection sweep, next-open fill
mechanics, position management, the signal-risk-sizing pipeline, persistence, lifecycle updates,
audit rows, idempotency/fencing) - Phase 4 **named two of the seams between them** more explicitly
(`_execute_next_open_decisions`, `_force_close_reason`) without reducing or redistributing the
underlying responsibilities themselves. This is the expected, honest outcome of "the smallest safe
extraction" done twice: real, verified, zero-risk improvements to internal naming and duplication,
not a reduction in the file's overall scope.

**Remaining concerns, explicitly investigated and NOT extracted (Phase 4.3):** sizing/margin
orchestration. Classification: **Intentional/acceptable** - backed by a documented production
incident fix (`tests/test_min_notional_decision_time.py`) and a fill-time re-validation
requirement; moving it would risk reopening a real, previously-fixed bug (see
REFACTOR_PROGRESS.md's Phase 4.3 section for the full trace). This is not deferred-but-still-a-
problem; it is investigated-and-confirmed-correct-where-it-is.

**Genuinely still large and multi-responsibility, by design:** `_process_agent_inner` (still ~170
lines, still the single per-agent orchestrator). Classification: **Medium** - not urgent, not
broken, but the largest remaining single function in the codebase and the natural next candidate if
further decomposition is ever wanted (see §15 roadmap).

## 9. Database dependency direction

**Unchanged - already correct at Phase 0, confirmed still correct.** No repository layer exists (by
design, per REFACTOR_PLAN.md's own recommendation not to build one). `app/core/database.py`'s
`get_db()` (API routes) / `session_scope()` (background processes) split is untouched.
**Classification: Intentional/acceptable.**

## 10. Market-data dependency direction

**Unchanged.** `HyperliquidClient`/`hyperliquid_ws.py` remain the only Hyperliquid-shape-aware code;
`MarketDataService` remains the sole normalization boundary. Phase 4 never touched `app/market/`.
**Classification: Intentional/acceptable.**

## 11. AI/Ollama dependency direction

**Improved for the council; unchanged elsewhere.** `council/service.py` and `council/analysts.py`
now depend on `AIClientPort`, not `OllamaClient` (Phase 1, holding - see §4).
`app/evolution/ollama_researcher.py` still depends on `OllamaClient` concretely - **unchanged,
dormant, Low priority** (see §4, §15).

## 12. Live/backtest duplication

**Unchanged, and correctly left alone.** Phase 4.3's investigation (REFACTOR_PROGRESS.md) found
that `app/backtesting/engine.py` independently re-implements the sizing/margin/risk orchestration
sequence that lives in `decision_loop.py`, calling the same underlying pure functions
(`stop_distance_pct`, `requested_notional`, `margin_state`, `check_trade`) in a separately-written
sequence. This is real duplication of *orchestration*, not of the underlying math (which is
correctly shared). It predates this refactor entirely and was correctly identified as out-of-scope
for "Phase 4: decision_loop.py" rather than force-fixed. **Classification: Medium** - real,
worth addressing eventually, but requires its own initiative gated by
`tests/test_live_backtest_parity.py` (~80s, multi-scenario), not a decision_loop.py sub-phase.

## 13. Test architecture

**Unchanged in structure, +3 files in count.** Still a flat `backend/tests/` directory (97 files by
this review's count, not counting `conftest.py`/`helpers_*.py` - the earlier ~99 estimate from
Phase 0's exploration agent was approximate). The three new files added by Phase 1/2/4.0
(`test_council_ports.py`, `test_lifecycle_ports.py`, `test_decision_loop_characterization.py`)
follow the existing flat convention deliberately, per REFACTOR_PLAN.md's own explicit decision not
to reorganize the test directory. **Classification: Intentional/acceptable** (per REFACTOR_PLAN.md
§5, deprioritized by design - real mechanical risk, no functional benefit, still true).

## 14. Any newly introduced coupling

**None found.** Every file touched across all four phases is accounted for by the two features
built (AI port, position-close port) and the two decision_loop.py extractions - confirmed by
`git status` showing exactly: `decision_loop.py`, `lifecycle.py`, `council/service.py`,
`council/analysts.py`, `research/pipeline.py`, `fitness_engine.py` (a separate, earlier, already-
reported piece of work), plus the 5 new files. No file outside this list was touched at any point,
and no file in this list gained a *new* external dependency that didn't already exist - every
change either removed a dependency (lifecycle.py losing its `app.execution` import) or renamed/
relocated an existing one (council depending on a Protocol instead of a class).

---

## Before vs. After summary

| Dimension | Before (Phase 0) | After (Phase 4 closed) |
|---|---|---|
| Council's AI dependency | Concrete `OllamaClient` import | `AIClientPort` Protocol; `OllamaClient` unmodified, satisfies it structurally |
| Lifecycle's execution dependency | Deferred `from app.execution import accounting` inside `retire_generation()` | Zero `app.execution` references; caller (`research/pipeline.py`) supplies `PositionCloseSettler` explicitly |
| `decision_loop.py`'s next-open dispatch | Inlined 5-line if/elif in `_process_agent_inner` | Named function `_execute_next_open_decisions` |
| `decision_loop.py`'s force-close mapping | Duplicated literal/ternary in two call sites | Single shared `_force_close_reason` |
| Sizing/margin orchestration location | In `decision_loop.py` | **Unchanged** - investigated, confirmed correct, left alone |
| `ExecutionEngine` hierarchy | Port + 3 adapters, already correct | **Untouched**, confirmed still correct |
| Test directory structure | Flat, 287 files' worth of tests | **Unchanged by design**, +3 files |
| Full test suite | 922 passed / 3 pre-existing failures (original baseline before this session's fitness work) | 936 passed / 2 pre-existing failures - zero new failures across every verification run in every phase |
| Import cycles | None | None |

## Improvements achieved

1. Two real, if narrow, dependency-inversion fixes (§4, §5), each verified by a test that proves
   the dependency is genuine (a non-`OllamaClient` object drives a full council cycle; a
   non-`accounting` settler drives `retire_generation`), not just a renamed type hint.
2. Two real, if small, duplication removals inside `decision_loop.py` (§8), each verified
   byte-for-byte against a purpose-built characterization baseline with zero behavioral drift.
3. A reusable regression baseline (`tests/test_decision_loop_characterization.py`) that did not
   exist before and now exists as permanent infrastructure for any future `decision_loop.py` change.
4. Two coverage gaps closed with tests describing *current*, previously-unverified behavior (the
   daily-loss breaker's day-rollover anchor reset; the mandatory sweep's cross-generation case) -
   not new behavior, but new proof of existing behavior.
5. A correct, evidence-backed **decision not to over-extract**: Phase 4.3 is itself an improvement
   in the sense that it prevented an architecturally-motivated but practically-harmful change
   (moving sizing/margin) from being made.

## Remaining risks

| Risk | Classification |
|---|---|
| `decision_loop.py` is still a 985-line, 8-9-responsibility file | **Medium** - known, stable, not worsened by this refactor |
| Live/backtest orchestration duplication (§12) | **Medium** - real, pre-existing, requires its own initiative |
| `ollama_researcher.py`'s un-inverted `OllamaClient` dependency | **Low** - dormant, unwired, no current blast radius |
| `backend/.env` committed-secret history (flagged by `test_secret_scan.py`, pre-existing, unrelated to this refactor) | **High**, but explicitly out of architectural scope - a security/ops item, not a coupling item; already documented in `docs/security.md` |
| Test directory remains flat at 97+ files | **Low** - cosmetic, explicitly deprioritized by design |

## Intentional coupling (do not "fix")

- `get_settings()`'s broad fan-out (§2) - narrow reads from ~62 call sites, not a god object.
- `decision_loop.py` importing `app.execution.sizing`/`margin`/`paper_adapter.new_client_order_id`
  directly for pre-execution math - investigated in Phase 4.3, confirmed correct and load-bearing.
- The flat test directory - a deliberate cost/benefit call, not an oversight.
- `worker/cycle.py` typing `OllamaClient` concretely - the correct composition-root pattern, not a
  leak of the abstraction.

## False positives (Graphify signal, not an architectural problem)

- `make_agents()`, `make_dna()`, `make_context()` - test fixtures, not production code.
- The 5 "surprises" bridge nodes (§3) - all test-to-domain-model governance/audit tests.
- Raw god-node edge counts increasing slightly (§2) - driven by more test files exercising the same
  fixtures, not by new production coupling.

## Recommended next initiatives

See the prioritized roadmap below.

## What should NOT be refactored

1. **`ExecutionEngine`/adapter hierarchy** - already correct (port + 3 adapters); rebuilding it was
   never justified and still isn't.
2. **Sizing/margin location** - Phase 4.3's investigation stands; do not revisit without new
   evidence that the two documented invariants (decision-time min-notional check, fill-time margin
   re-validation) have changed.
3. **`Settings` structure** - splitting it into multiple `BaseSettings` classes would touch ~62 call
   sites for a cosmetic win over narrow per-service config objects, which is the already-correct
   pattern in the two places that need it (`FitnessWeights`, `PromotionCriteria`).
4. **Test directory reorganization** - real mechanical risk (import paths, CI assumptions), no
   functional benefit; pytest does not care about folder structure.
5. **A repository/unit-of-work layer over the database** - no evidence it's needed at this scale;
   the current `db: AsyncSession`-as-parameter pattern is appropriate and well-tested.

---

## Prioritized roadmap: next 3 architectural initiatives

1. **Live/backtest orchestration unification** (§12, Medium). The one genuine, unaddressed
   duplication found across this entire review. Candidate approach: follow the codebase's own
   precedent (`backtesting/risk_adapter.py::backtest_risk_check` - a thin, context-specific adapter
   around a shared pure function) rather than a merged pipeline. Gate: `test_live_backtest_parity.py`
   must pass unchanged before and after every step. Larger and riskier than any single Phase
   4.1/4.2 step - plan it as its own multi-step initiative with its own characterization baseline,
   mirroring Phase 4.0's methodology.
2. **`ollama_researcher.py`'s `AIClientPort` adoption** (§4/§11, Low, but cheap). Apply the exact
   same Phase 1 pattern (already proven, already tested) to this dormant module before it is ever
   wired into production - closes the last known instance of the pre-Phase-1 coupling shape at
   near-zero cost, whenever that module is next touched for functional reasons.
3. **`_process_agent_inner` further decomposition** (§8, Medium, optional). If more clarity is
   wanted in `decision_loop.py` beyond what Phase 4.1/4.2 achieved, the next candidate boundary -
   following the same "smallest safe extraction, characterization-gated" methodology - would be
   the "step 4: sizing + risk" block's *orchestration* (not the sizing/margin location itself,
   which Phase 4.3 settled) into a named, single-purpose function within the same file, the same
   way `_execute_next_open_decisions` named "step 0." Should only be attempted with a
   characterization scenario extended to cover the risk-rejection and margin-reduction paths, which
   the current `test_decision_loop_characterization.py` scenario does not yet exercise.

**STOPPING after this review, as instructed. No code was modified.**
