# Graph Report - reserch_model  (2026-09-29)

## Corpus Check
- 329 files · ~237,148 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .service 4, (none) 3, .ini 2)

## Summary
- 4066 nodes · 15278 edges · 155 communities (123 shown, 32 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2161 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3cf1d268`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_agents
- sqlalchemy
- helpers_agents.py
- sqlalchemy_ext_asyncio
- MarketDataService
- get_settings
- pytest
- _db_gauges
- test_ws_client.py
- decision_loop.py
- indicators.py
- test_position_protection.py
- test_stage_metrics.py
- run_backtest
- test_stops_trailing.py
- RiskDecision
- make_context
- MarketRegime
- cycle.py
- test_ollama_schema_normalization.py
- test_frozen_oos_epoch.py
- test_reality_gap_engine.py
- test_worker_cycle.py
- test_worker_fencing.py
- run_council_cycle
- test_decision_loop.py
- RuleSet
- enums.py
- StrategyDNA
- data.py
- test_ollama_failure_modes.py
- strategy_regime.py
- experiment_runner.py
- test_shadow_fitness_synthetic.py
- backtesting/engine.py
- StrategyVersion
- pipeline.py
- dataset.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- select_and_breed_next_generation
- compute_fitness
- pydantic
- evolution/correlation.py
- test_shadow_mode.py
- families.py
- test_lifecycle_ports.py
- Refactor Progress
- test_council_integration.py
- typing
- ._post_info
- test_regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- _Sheet
- ollama_client.py
- test_council_failclosed.py
- requested_notional
- refresh_trade_analytics
- Bias
- Local Migration
- test_ollama_client.py
- test_correlation.py
- normalization.py
- Decision
- test_council_deadline.py
- registry.py
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- pathlib
- test_as_of_boundaries.py
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- test_api_endpoints.py
- test_analytics_migration.py
- test_migrations.py
- Agent
- test_dna_runtime_coverage.py
- secret_scan.py
- _build_scenario
- routes/champion_challenger.py
- compute_generation_correlation_report
- HyperliquidWebSocket
- conftest.py
- shadow_rows_for_generation
- dashboard.py
- report_fitness_forward.py
- Architecture
- test_oos_lockbox.py
- run.sh
- test_dashboard_js.py
- Side
- test_backtesting.py
- FakeServer
- propose_candidate
- test_cooldown_limits.py
- WsCandle
- ImmutableAnalyticsRecordError
- below_min_order_notional
- json
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- KeyRefresher
- test_sqlite_locking.py
- report_trade_quality.py
- Multi-Week Research Readiness Report
- exit_analytics.py
- apply_diversity_pressure
- helpers_shadow.py
- test_identical_frame_is_redelivered_after_a_failed_delivery
- graphify reference: extra exports and benchmark
- shadow_summary
- alembic_config
- _StreamSlot
- _reset_metrics
- _bar_ms
- migrate_sqlite_to_postgres.py
- graphify reference: query, path, explain
- capture_state
- purge_secrets_from_history.sh
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: GitHub clone and cross-repo merge
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 243 edges
2. `PaperExecutionAdapter` - 189 edges
3. `Agent` - 172 edges
4. `make_agents()` - 163 edges
5. `StrategyDNA` - 159 edges
6. `make_dna()` - 156 edges
7. `Side` - 148 edges
8. `StrategyVersion` - 140 edges
9. `make_context()` - 132 edges
10. `Trade` - 127 edges

## Surprising Connections (you probably didn't know these)
- `Files changed` --references--> `_execute_next_open_decisions()`  [INFERRED]
  REFACTOR_PROGRESS.md → backend/app/agents/decision_loop.py
- `Research` --references--> `experiments()`  [INFERRED]
  docs/runbook.md → backend/app/api/routes/evolution.py
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py
- `5. AI council as *context*, not oracle` --references--> `Decision`  [INFERRED]
  docs/architecture.md → backend/app/models/decision.py

## Import Cycles
- None detected.

## Communities (155 total, 32 thin omitted)

### Community 0 - "make_agents"
Cohesion: 0.07
Nodes (54): 1. Current Graphify statistics, make_agents(), make_dna(), _fast(), fixture, Independent agents, per-agent failure isolation and DB-level idempotency (spec…, test_a_failing_agent_is_isolated_and_the_rest_of_the_population_trades(), submit_order() (+46 more)

### Community 1 - "sqlalchemy"
Cohesion: 0.07
Nodes (81): argparse, do_run_migrations(), run_migrations_online(), _components_of(), DB I/O for the analytics foundation. The ONLY module that writes, and it writes…, For every recorded FitnessScore snapshot (plus an hourly reconstruction grid…, refresh_fitness_forward(), _corr_upto() (+73 more)

### Community 2 - "helpers_agents.py"
Cohesion: 0.12
Nodes (34): check_candidate_schema(), Gate 1 of the candidate pipeline: the DNA must survive a strict round-trip…, ComparisonOperator, CooldownConfig, IndicatorConfig, PositionSizing, BaseModel, Enum (+26 more)

### Community 3 - "sqlalchemy_ext_asyncio"
Cohesion: 0.04
Nodes (100): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix() (+92 more)

### Community 4 - "MarketDataService"
Cohesion: 0.04
Nodes (63): asyncio, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory(), _is_secret_key() (+55 more)

### Community 5 - "get_settings"
Cohesion: 0.04
Nodes (57): _acquire_stream_slot(), Request, Server-Sent Events: a `status` event every `interval` seconds (worker…, stream(), gen(), get_settings(), authenticate(), _client_id() (+49 more)

### Community 6 - "pytest"
Cohesion: 0.05
Nodes (59): 3. Current cross-community bridge nodes, Enum, field_validator, str, Centralized application configuration. Every environment-dependent value in the…, All gates required by spec section 40 before ANY live order. This does not…, Settings, TradingMode (+51 more)

### Community 7 - "_db_gauges"
Cohesion: 0.31
Nodes (9): _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, API-process counters + worker-published counters + DB-derived gauges…, Credential health by INDEX only (never the key itself) + last council outcome., system_status() (+1 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.15
Nodes (26): candle(), make(), Hyperliquid WebSocket transport (spec phase 17) against an in-process fake…, _run_until(), test_callback_failure_does_not_kill_the_stream(), script(), test_exact_duplicates_dropped_but_updates_to_the_open_bar_pass(), script() (+18 more)

### Community 9 - "decision_loop.py"
Cohesion: 0.07
Nodes (76): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+68 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (58): _atr(), compute_indicator(), compute_indicator_features(), compute_indicator_series(), _ema(), _feature_keys_cached(), feature_keys_for(), _ind_adx() (+50 more)

### Community 11 - "test_position_protection.py"
Cohesion: 0.06
Nodes (73): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, active_flags(), AsyncSession, Read/write helpers for durable system flags (kill switch, data-gap halt)., Returns {flag_name: reason} for every currently-active flag., Single string (or None) the risk engine uses to block NEW entries., set_flag() (+65 more)

### Community 12 - "test_stage_metrics.py"
Cohesion: 0.23
Nodes (11): WalkForwardReport, WalkForwardWindow, _backtest_result(), asyncio, UUID, Persisted per-stage performance snapshots and reality-gap comparison (spec…, _seed_strategy_version(), test_compute_reality_gap_between_stages() (+3 more)

### Community 13 - "run_backtest"
Cohesion: 0.10
Nodes (51): DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward(), _simulate(), dna_indicator_specs() (+43 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.18
Nodes (28): advance_extremes(), Bar, bar_time(), evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of… (+20 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (41): Routes backtest/adversarial position sizing through the real…, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every…, RiskCheckInput, RiskCheckResult, _python_sources() (+33 more)

### Community 16 - "make_context"
Cohesion: 0.11
Nodes (37): 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), cycle(), make_context(), test_export_report_is_one_xlsx_with_every_dashboard_section(), test_population_and_agent_detail_endpoints(), test_population_reports_trade_counts_open_positions_and_win_rate() (+29 more)

### Community 17 - "MarketRegime"
Cohesion: 0.08
Nodes (58): _atr(), _bollinger(), compute_features(), detect_regime(), _ema(), _macd(), DataFrame, Series (+50 more)

### Community 18 - "cycle.py"
Cohesion: 0.08
Nodes (41): counter_value(), _escape(), _fmt(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint…, record_db_error() (+33 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.13
Nodes (43): CouncilAnalysis, One analyst's structured response feeding into a CouncilDecision., analyst_server(), client_for(), gen(), items(), long_vote(), norm() (+35 more)

### Community 20 - "test_frozen_oos_epoch.py"
Cohesion: 0.10
Nodes (34): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, evaluate_oos_once(), OosAlreadyConsumedError (+26 more)

### Community 21 - "test_reality_gap_engine.py"
Cohesion: 0.05
Nodes (73): compute_full_reality_gap_chain(), persist_reality_gap_report(), AsyncSession, UUID, Full-lifecycle reality-gap report: Backtest -> Walk-Forward -> Out-of-Sample ->…, Compares every consecutive pair of stages this strategy version has actually…, Insert-only — caller commits., RealityGapChainReport (+65 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.15
Nodes (24): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), _cycles(), no_council(), fixture (+16 more)

### Community 23 - "test_worker_fencing.py"
Cohesion: 0.05
Nodes (58): db_now(), _insert_fn(), LeaseKeeper, LeaseLost, LeaseState, new_owner_id(), AsyncSession, RuntimeError (+50 more)

### Community 24 - "run_council_cycle"
Cohesion: 0.12
Nodes (39): _decision(), history(), latest(), AsyncSession, get, AsyncSession, run_council_cycle(), CouncilDecision (+31 more)

### Community 25 - "test_decision_loop.py"
Cohesion: 0.17
Nodes (33): minimal_context(), A NEUTRAL-feature context for one CONFIRMED stored candle…, MarketContext, MomentumFeatures, PriceActionFeatures, BaseModel, The shared market context computed once per candle and fanned out to the AI…, Flattened {feature_name: value} view used by the deterministic rule engine… (+25 more)

### Community 26 - "RuleSet"
Cohesion: 0.09
Nodes (52): Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet, _all_rulesets(), available_feature_keys() (+44 more)

### Community 27 - "enums.py"
Cohesion: 0.06
Nodes (72): 9. Database dependency direction, AgentAlreadyDeadError, bankruptcy_threshold(), create_generation(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession (+64 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.29
Nodes (25): StrategyFamily, model_validator, Combinations the schema ACCEPTS but that silently do nothing (or something…, StrategyDNA, _base_risk(), _build_breakout(), _build_hybrid(), _build_market_structure() (+17 more)

### Community 29 - "data.py"
Cohesion: 0.09
Nodes (32): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame (+24 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.09
Nodes (31): Cooldown for a 429: honour Retry-After (seconds), else an escalating default…, call(), make_client(), parametrize, Ollama client failure handling (spec phases 14-15): 401, 403, 429, timeout,…, test_200_with_malformed_envelope_is_a_typed_response_error(), test_200_with_non_json_body_is_a_typed_response_error_not_a_crash(), test_400_is_not_retried_and_is_a_typed_error() (+23 more)

### Community 31 - "strategy_regime.py"
Cohesion: 0.08
Nodes (40): bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci(), episode_ids() (+32 more)

### Community 32 - "experiment_runner.py"
Cohesion: 0.13
Nodes (30): _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments(), AsyncSession, Bar, DataFrame (+22 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.13
Nodes (33): champion_evidence_ok(), compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, current_fitness(), make_population(), (production compute_fitness, max drawdown) fed the way fitness_service feeds…, world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights… (+25 more)

### Community 34 - "backtesting/engine.py"
Cohesion: 0.11
Nodes (28): compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL, _Pos, Event-driven backtesting engine (spec section 22; phase 22 "backtest parity").… (+20 more)

### Community 35 - "StrategyVersion"
Cohesion: 0.06
Nodes (109): NoValidCandidatesError, RuntimeError, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the…, Every candidate (and every replacement founder) failed the validation gate:…, Champion/challenger state that actually drives the population: current…, select_elite_versions(), CandidateMetrics (+101 more)

### Community 36 - "pipeline.py"
Cohesion: 0.12
Nodes (34): derive_seed(), A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id,…, ChallengerEvaluation, Experiment, Generation, _adversarial(), evaluate_gates(), AsyncSession (+26 more)

### Community 37 - "dataset.py"
Cohesion: 0.12
Nodes (35): ResearchEpoch, _build_epoch(), count_confirmed_candles(), EpochIntegrityError, fingerprint_frame(), get_active_epoch(), get_or_create_epoch(), load_confirmed_candles() (+27 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.16
Nodes (20): TradeEvidence, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), with_extra_cost(), _agent() (+12 more)

### Community 39 - "analyze_trade"
Cohesion: 0.16
Nodes (29): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+21 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.08
Nodes (52): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+44 more)

### Community 41 - "select_and_breed_next_generation"
Cohesion: 0.05
Nodes (72): BreedingResult, _most_correlated_pair(), _preserve_family_distribution(), Random, Selects survivors from `generation_number`, breeds children via…, Biases fresh-DNA injection toward minority families apply_diversity_pressure…, The least-diverse pair (O(n^2) over precomputed signatures; kept for…, select_and_breed_next_generation() (+64 more)

### Community 42 - "compute_fitness"
Cohesion: 0.05
Nodes (82): _clip(), compute_fitness(), FitnessInputs, FitnessResult, FitnessWeights, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,… (+74 more)

### Community 43 - "pydantic"
Cohesion: 0.10
Nodes (22): AICallStats, AIClientPort, Protocol, T, The council's dependency contract on an AI client (Phase 1 dependency-boundary…, The subset of OllamaCallStats the council actually reads., Everything the council needs from an AI client. Signature matches…, OllamaCallStats (+14 more)

### Community 44 - "evolution/correlation.py"
Cohesion: 0.23
Nodes (13): _condition_set(), exit_condition_similarity(), feature_set(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the…, ruleset_signature(), ruleset_signature_similarity() (+5 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.05
Nodes (56): ABC, ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+48 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "test_lifecycle_ports.py"
Cohesion: 0.11
Nodes (26): 5. PositionCloseSettler boundary, Improvements achieved, datetime, Ends a superseded generation cleanly: every open position is closed at…, retire_generation(), PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into… (+18 more)

### Community 48 - "Refactor Progress"
Cohesion: 0.17
Nodes (11): 2. PositionCloseSettler review, 3. Dependency-direction map, 4-5. Test results, Files changed, Full test suite (both phases combined), Phase 3 — Boundary verification and hardening (no `decision_loop.py`), Phase 4.1 — Extraction performed, Phase 4 — proposed plan for `decision_loop.py` (NOT implemented; plan only, pending approval) (+3 more)

### Community 49 - "test_council_integration.py"
Cohesion: 0.14
Nodes (21): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, test_not_run_means_approved_only_when_the_council_was_not_required() (+13 more)

### Community 51 - "._post_info"
Cohesion: 0.24
Nodes (8): HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context., Returns raw Hyperliquid candle dicts: {"t": open_ms, "T": close_ms,…, Returns Hyperliquid's published funding settlements: [{"coin", "fundingRate",…, Public read-only order book snapshot: {"coin","time","levels":[bids, asks]}…, retry

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.08
Nodes (47): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID, BacktestResult, _all_regimes(), classify_robustness() (+39 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.11
Nodes (36): PaperExecutionAdapter, Random, OrderStatus, _orders(), _pos(), Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close…, Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the…, test_a_pending_entry_that_was_not_filled_on_the_next_bar_is_never_filled_late() (+28 more)

### Community 54 - "Runbook"
Cohesion: 0.07
Nodes (25): Behaviour change to know about: next-open fills, Database size / `decisions` growth, Emergency stop, Health, Ollama credentials (no restart needed), PostgreSQL, PostgreSQL sizing and timeouts, Research (+17 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.23
Nodes (15): estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, _samples(), ShadowConfig, unit_result() (+7 more)

### Community 57 - "_Sheet"
Cohesion: 0.17
Nodes (11): _build(), _cell_value(), _fetch(), _flatten(), _plain(), Any, datetime, Nested dicts become dotted columns; lists become JSON text. (+3 more)

### Community 58 - "ollama_client.py"
Cohesion: 0.14
Nodes (22): OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError, OllamaServerError (+14 more)

### Community 59 - "test_council_failclosed.py"
Cohesion: 0.04
Nodes (52): 10. Market-data dependency direction, 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 6. ExecutionEngine boundary, Intentional coupling (do not "fix"), Post-Refactoring Architecture Review (+44 more)

### Community 60 - "requested_notional"
Cohesion: 0.12
Nodes (33): 12. Live/backtest duplication, _SyntheticAgentState, approve_against_margin(), build_sizing_result(), normalize_method(), Position sizing (spec phase 6): pure, deterministic, unit-tested. Supported DNA…, Fractional distance from entry to the protective stop (matches the stop…, What the DNA wants, before risk clamps. Never negative. (+25 more)

### Community 61 - "refresh_trade_analytics"
Cohesion: 0.11
Nodes (29): _as_trade_rows(), _is_uuid(), _ms(), AsyncSession, datetime, Rebuild the matrix for `computation_version` (derived aggregate: DELETE the…, `as_of`, when given, bounds every piece of data this refresh may see (candles,…, refresh_strategy_regime_matrix() (+21 more)

### Community 62 - "Bias"
Cohesion: 0.11
Nodes (36): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), apply_judge(), compute_consensus() (+28 more)

### Community 63 - "Local Migration"
Cohesion: 0.07
Nodes (25): model_validator, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real…, Three processes share the database. If their pools alone could exceed the…, Future Production Migration, Known limitations found during the local migration (apply to production too), Local Migration (+17 more)

### Community 64 - "test_ollama_client.py"
Cohesion: 0.19
Nodes (14): _Echo, _mock_transport(), asyncio, BaseModel, Ollama client failure handling: timeout, 429, malformed response (spec 45)., Root cause of the reported intermittent analyst 401s: with multiple…, test_401_on_every_key_exhausts_retries_and_raises_auth_error(), test_401_on_one_key_is_retried_and_recovers_on_the_next_key() (+6 more)

### Community 65 - "test_correlation.py"
Cohesion: 0.17
Nodes (22): entry_condition_similarity(), feature_similarity(), Jaccard similarity over each DNA's (indicator name, sorted params) set plus its…, Jaccard similarity over (feature, operator, value) entry conditions, averaged…, No `now` override -> real wall-clock time, exactly the pre-existing behavior., test_correlation_report_default_now_is_backward_compatible(), test_correlation_report_now_override_excludes_trades_closed_after_it(), _add_trade() (+14 more)

### Community 66 - "normalization.py"
Cohesion: 0.16
Nodes (19): BoundedResponse, _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any (+11 more)

### Community 67 - "Decision"
Cohesion: 0.12
Nodes (32): Decision, count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,… (+24 more)

### Community 68 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (18): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+10 more)

### Community 69 - "registry.py"
Cohesion: 0.18
Nodes (18): code_version(), finish_experiment(), new_experiment_id(), AsyncSession, UUID, Experiment registry (spec phase 23): every research run is a reproducible,…, Git commit (short) of the running code; `CODE_VERSION` env overrides…, Alembic head revision shipped with this code. (+10 more)

### Community 70 - "test_funding.py"
Cohesion: 0.33
Nodes (11): _dna(), _hold_across(), _no_sleep(), fixture, Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.11
Nodes (18): 1. Running a baseline vs. candidate experiment, 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Custom configs (+10 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "pathlib"
Cohesion: 0.27
Nodes (9): Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch…, test_absolute_memory_and_other_urls_are_untouched(), test_defaults_point_at_the_single_data_folder(), test_parent_folder_is_created(), test_relative_path_is_resolved_against_backend_not_the_cwd(), test_settings_from_env_use_the_resolved_path() (+1 more)

### Community 74 - "test_as_of_boundaries.py"
Cohesion: 0.23
Nodes (15): compute_agent_performance_metric(), AsyncSession, Builds (does not persist) a PerformanceMetric snapshot for `agent` from its…, datetime, Regression coverage for the `as_of` hardening pass: for any evaluation with…, Backward-compatible default: as_of=None preserves the original unbounded…, UTCDateTime stores/reads timezone-aware UTC throughout (app/models/base.py) -…, _seed_agent_with_trades() (+7 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.26
Nodes (12): confirmation_time_ms(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., seconds_until_next_confirmation(), test_council_cadence_is_derived_from_candle_time() (+4 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.11
Nodes (24): alembic_autogenerate, alembic_migration, _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database() (+16 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.18
Nodes (22): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids(), AsyncSession (+14 more)

### Community 78 - "test_api_endpoints.py"
Cohesion: 0.08
Nodes (37): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+29 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.15
Nodes (13): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+5 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.33
Nodes (10): _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs(), test_downgrade_then_upgrade_round_trips(), test_drift_detector_actually_detects_drift() (+2 more)

### Community 81 - "Agent"
Cohesion: 0.07
Nodes (63): Which agents can be TESTED at their capital (Option D of the min-notional…, _agent_age_days(), _agent_group_stats(), get_agent_metrics(), get_champions_analysis(), get_equity_curve(), get_fitness_components(), get_overview() (+55 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.23
Nodes (10): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_nested_dna_field_is_covered_by_a_named_behaviour_test() (+2 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.17
Nodes (16): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), uvicorn's AccessFormatter unpacks record.args into 5 fields; the redaction…, test_uvicorn_access_log_formats_and_is_redacted() (+8 more)

### Community 84 - "_build_scenario"
Cohesion: 0.31
Nodes (9): _build_scenario(), asyncio, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, _run_fixed_scenario(), test_fixed_scenario_is_internally_consistent(), test_fixed_scenario_matches_the_captured_baseline() (+1 more)

### Community 85 - "routes/champion_challenger.py"
Cohesion: 0.25
Nodes (13): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+5 more)

### Community 86 - "compute_generation_correlation_report"
Cohesion: 0.19
Nodes (13): _compute_behavioral_correlations(), compute_generation_correlation_report(), _lookup(), _Matrix, _position_overlap_jaccard(), AsyncSession, DataFrame, datetime (+5 more)

### Community 87 - "HyperliquidWebSocket"
Cohesion: 0.21
Nodes (5): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, OnCandles

### Community 88 - "conftest.py"
Cohesion: 0.21
Nodes (10): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+2 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.22
Nodes (12): rank_correlation(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat() (+4 more)

### Community 90 - "dashboard.py"
Cohesion: 0.35
Nodes (10): agent_metrics(), champions_analysis(), equity(), fitness_components(), overview(), AsyncSession, get, ranking_stability() (+2 more)

### Community 91 - "report_fitness_forward.py"
Cohesion: 0.26
Nodes (11): cohort_stats(), _flat(), main(), _pearson(), _ranks(), READ-ONLY fitness -> future-performance report (Reports F and H). python -m…, Average ranks (ties share the mean rank) — deterministic., One cohort (as_of, horizon): the study's statistics, over flattened rows. (+3 more)

### Community 92 - "Architecture"
Cohesion: 0.17
Nodes (12): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+4 more)

### Community 93 - "test_oos_lockbox.py"
Cohesion: 0.08
Nodes (35): Fraction of windows that were profitable — a simple, auditable stand-in for…, compute_oos_score(), [0, 1]. Zero without enough trades to say anything. Otherwise: (0.4 *…, Final-OOS protection (spec phase 23): evolution cannot see or re-tune against…, A handful of trades cannot earn a near-full score regardless of how clean they…, The bug this fix closes: a 3-trade, ~flat-return, small-drawdown run used to…, _setup(), test_database_constraint_is_the_final_arbiter_for_oos_reuse() (+27 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (11): cmd_backup(), cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), env_value(), is_running() (+3 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "Side"
Cohesion: 0.11
Nodes (30): stop_price(), take_profit_price(), BacktestTrade, entry_levels(), EntryLevels, funding_payment(), The ONE implementation of position accounting (paper, shadow, backtest, walk-…, One funding settlement. Positive = the trader PAYS. A positive rate makes longs… (+22 more)

### Community 97 - "test_backtesting.py"
Cohesion: 0.20
Nodes (16): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+8 more)

### Community 98 - "FakeServer"
Cohesion: 0.18
Nodes (4): test_ws_reconnects_are_counted(), FakeServer, Scriptable exchange: every accepted connection runs `script(ws, conn_index)`., test_heartbeat_pings_are_sent()

### Community 99 - "propose_candidate"
Cohesion: 0.22
Nodes (8): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _AlwaysFailsClient, asyncio, Duck-typed stand-in for OllamaClient — raises immediately rather than going…, test_propose_candidate_returns_none_on_ollama_rate_limit(), test_propose_candidate_returns_none_on_ollama_timeout(), Exception

### Community 100 - "test_cooldown_limits.py"
Cohesion: 0.23
Nodes (13): _dna(), _fast(), fixture, Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe(), test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day() (+5 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "below_min_order_notional"
Cohesion: 0.08
Nodes (32): backtest_risk_check(), Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, below_min_order_notional(), True when an ENTRY of `notional` at `price` would be refused by the exchange…, deterministic(), fixture, test_check_mirrors_the_adapter_lot_rounding(), 10. Required characterization/parity tests before implementation (+24 more)

### Community 104 - "json"
Cohesion: 0.29
Nodes (8): Ollama-driven strategy research (spec section 26). Ollama proposes candidate…, _flat(), _fmt(), _fmt_pct(), main(), READ-ONLY Strategy x Regime report (Reports A and G). python -m…, render(), json

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "KeyRefresher"
Cohesion: 0.20
Nodes (4): KeyRefresher, Safe to call from a signal handler., test_key_refresher_never_raises_into_the_trading_loop(), test_key_refresher_periodic_and_forced()

### Community 108 - "test_sqlite_locking.py"
Cohesion: 0.24
Nodes (11): factory(), fixture, SQLite write-lock behaviour on a real WAL file shared by two connections…, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle() (+3 more)

### Community 109 - "report_trade_quality.py"
Cohesion: 0.33
Nodes (9): _flat(), getattr_r(), main(), _mean(), _median(), _pct(), READ-ONLY trade-quality report (Reports B, C, D): entry quality, exit quality,…, Group value as a plain string ('SIDE.SHORT' enum repr -> 'SHORT', None -> '-'). (+1 more)

### Community 110 - "Multi-Week Research Readiness Report"
Cohesion: 0.18
Nodes (10): 10. FINAL READINESS CHECK, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 7. RESEARCH DASHBOARD, 9. RECOVERY TEST — real, on the actual dev environment, Known limitations, Multi-Week Research Readiness Report (+2 more)

### Community 111 - "exit_analytics.py"
Cohesion: 0.36
Nodes (7): exit_analytics(), _histogram(), AsyncSession, datetime, get, UUID, Exit-research dashboard data: MFE/MAE, realized R, post-exit movement, reversal…

### Community 112 - "apply_diversity_pressure"
Cohesion: 0.43
Nodes (7): apply_diversity_pressure(), DiversityPressureAction, GenerationCorrelationReport, Pure signal generator for app/evolution/breeding.py to consume: a mutation-rate…, asyncio, test_apply_diversity_pressure_flags_high_correlation_and_never_touches_agent_status(), test_apply_diversity_pressure_no_pressure_when_healthy()

### Community 113 - "helpers_shadow.py"
Cohesion: 0.31
Nodes (7): ShadowAgentInput, _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, Agents plus the ground truth. `truth_edge[i]` is the true net edge (R/trade) of…, types

### Community 114 - "test_identical_frame_is_redelivered_after_a_failed_delivery"
Cohesion: 0.29
Nodes (6): A DB hiccup must not turn the exchange's retry of the SAME frame into a…, test_client_survives_connection_refused_then_connects(), flaky(), script(), test_identical_frame_is_redelivered_after_a_failed_delivery(), script()

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "shadow_summary"
Cohesion: 0.40
Nodes (4): AsyncSession, get, Expected-vs-actual market execution measured by shadow mode., shadow_summary()

### Community 119 - "_reset_metrics"
Cohesion: 0.33
Nodes (4): Echo, BaseModel, fixture, _reset_metrics()

### Community 121 - "_bar_ms"
Cohesion: 0.67
Nodes (3): _bar_ms(), Bar, Interval of the candle grid (median diff), 60_000 fallback.

### Community 123 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.36
Nodes (7): _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., One row of headline aggregates, computed identically against either engine, for…, upgrade_schema()

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "capture_state"
Cohesion: 0.67
Nodes (3): capture_state(), See module docstring for exactly what is/isn't included and why., _round()

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1239 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **32 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `make_agents`, `sqlalchemy`, `helpers_agents.py`, `sqlalchemy_ext_asyncio`, `MarketDataService`, `pytest`, `decision_loop.py`, `test_position_protection.py`, `run_backtest`, `test_stops_trailing.py`, `RiskDecision`, `make_context`, `cycle.py`, `test_frozen_oos_epoch.py`, `test_reality_gap_engine.py`, `test_worker_cycle.py`, `test_worker_fencing.py`, `run_council_cycle`, `enums.py`, `data.py`, `backtesting/engine.py`, `StrategyVersion`, `pipeline.py`, `dataset.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `compute_fitness`, `test_shadow_mode.py`, `test_lifecycle_ports.py`, `test_council_integration.py`, `test_regime_validation_engine.py`, `PaperExecutionAdapter`, `ollama_client.py`, `test_council_failclosed.py`, `requested_notional`, `Bias`, `Decision`, `test_council_deadline.py`, `registry.py`, `test_funding.py`, `test_untestable_agents.py`, `test_api_endpoints.py`, `Agent`, `conftest.py`, `test_cooldown_limits.py`, `below_min_order_notional`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `StrategyDNA` connect `StrategyDNA` to `make_agents`, `sqlalchemy`, `helpers_agents.py`, `pytest`, `decision_loop.py`, `test_position_protection.py`, `test_stage_metrics.py`, `run_backtest`, `RiskDecision`, `make_context`, `MarketRegime`, `test_frozen_oos_epoch.py`, `test_reality_gap_engine.py`, `test_worker_cycle.py`, `test_decision_loop.py`, `RuleSet`, `enums.py`, `data.py`, `experiment_runner.py`, `backtesting/engine.py`, `StrategyVersion`, `pipeline.py`, `dataset.py`, `test_adversarial.py`, `select_and_breed_next_generation`, `evolution/correlation.py`, `test_regime_validation_engine.py`, `test_council_failclosed.py`, `requested_notional`, `test_correlation.py`, `Decision`, `Experiment Guide`, `test_as_of_boundaries.py`, `test_untestable_agents.py`, `Agent`, `test_dna_runtime_coverage.py`, `compute_generation_correlation_report`, `Side`, `test_backtesting.py`, `below_min_order_notional`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `make_agents`, `sqlalchemy`, `helpers_agents.py`, `sqlalchemy_ext_asyncio`, `_db_gauges`, `decision_loop.py`, `test_position_protection.py`, `RiskDecision`, `make_context`, `test_frozen_oos_epoch.py`, `test_reality_gap_engine.py`, `test_worker_fencing.py`, `test_decision_loop.py`, `enums.py`, `backtesting/engine.py`, `StrategyVersion`, `pipeline.py`, `dataset.py`, `test_shadow_fitness.py`, `select_and_breed_next_generation`, `compute_fitness`, `test_lifecycle_ports.py`, `test_regime_validation_engine.py`, `PaperExecutionAdapter`, `test_db_constraints.py`, `shadow_fitness.py`, `test_council_failclosed.py`, `requested_notional`, `refresh_trade_analytics`, `test_correlation.py`, `Decision`, `test_as_of_boundaries.py`, `test_untestable_agents.py`, `compute_generation_correlation_report`, `shadow_rows_for_generation`, `below_min_order_notional`, `apply_diversity_pressure`, `capture_state`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 102 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 102 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._