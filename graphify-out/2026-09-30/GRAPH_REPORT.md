# Graph Report - reserch_model  (2026-09-30)

## Corpus Check
- 334 files · ~249,360 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .service 4, (none) 3, .ini 2)

## Summary
- 4140 nodes · 15506 edges · 176 communities (143 shown, 33 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2178 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2e4c99b4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- breeding.py
- sqlalchemy
- Trade
- export.py
- MarketDataService
- get_settings
- config.py
- test_strategy_dna.py
- test_ws_client.py
- decision_loop.py
- indicators.py
- MarketCandle
- test_evolution_pipeline.py
- run_backtest
- test_stops_trailing.py
- RiskDecision
- PaperExecutionAdapter
- routes/status.py
- reset
- test_ollama_schema_normalization.py
- test_oos_lockbox.py
- Multi-Week Research Readiness Report
- test_worker_cycle.py
- lease.py
- run_council_cycle
- helpers_agents.py
- RuleSet
- Agent
- StrategyFamily
- BacktestResult
- test_ollama_failure_modes.py
- strategy_regime.py
- test_experiment_runner.py
- test_shadow_fitness_synthetic.py
- ExecutionRequest
- test_promotion_service.py
- pipeline.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- test_evolution_gate_and_champions.py
- compute_fitness
- routes/correlation.py
- trades.py
- test_shadow_mode.py
- families.py
- test_lifecycle_ports.py
- test_live_backtest_parity.py
- OllamaCallStats
- get_db
- HyperliquidClient
- test_regime_validation_engine.py
- Side
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- test_worker_fencing.py
- test_sqlite_locking.py
- test_council_failclosed.py
- Initiative 1 — CLOSED
- test_as_of_boundaries.py
- Bias
- Local Migration
- test_postgres_concurrency.py
- test_correlation.py
- AbuseGuard
- prune_decisions.py
- test_council_deadline.py
- pydantic
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- test_db_location.py
- compute_agent_performance_metric
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- agents.py
- test_analytics_migration.py
- test_migrations.py
- dashboard.py
- test_dna_runtime_coverage.py
- secret_scan.py
- _build_scenario
- routes/regime_validation.py
- make_agents
- evaluate_fitness_versions.py
- conftest.py
- shadow_rows_for_generation
- test_champion_challenger_service.py
- report_trade_quality.py
- test_fitness_edge_cases.py
- test_api_endpoints.py
- run.sh
- test_dashboard_js.py
- test_check_constraints_are_enforced_by_postgres_itself
- test_backtesting.py
- logging.py
- test_promotion_evidence.py
- Position
- WsCandle
- ImmutableAnalyticsRecordError
- test_gap_cycle.py
- paper_adapter.py
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- run_cycle.py
- test_api_security.py
- test_fitness_versions.py
- OrderStatus
- compute_generation_correlation_report
- routes/reality_gap.py
- helpers_shadow.py
- test_fitness_forward.py
- graphify reference: extra exports and benchmark
- normalization.py
- alembic_config
- fitness_forward.py
- StrategyVersion
- _mock_transport
- graphify reference: query, path, explain
- champion_challenger_service.py
- purge_secrets_from_history.sh
- Post-Refactoring Architecture Review
- typing
- test_next_open_execution.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- test_config_audit.py
- correlation_service.py
- list_challengers
- test_adversarial_service.py
- test_cooldown_limits.py
- graphify reference: GitHub clone and cross-repo merge
- code_only
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md
- routes/market.py
- migrate_sqlite_to_postgres.py
- refresh_fitness_forward
- report_strategy_regime.py
- set_flag
- StrategyDNA
- fitness_versions.py
- _alembic
- test_snapshots_and_lifecycle.py
- test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison
- graphify reference: transcribe video and audio
- _bar_ms

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 246 edges
2. `PaperExecutionAdapter` - 190 edges
3. `Agent` - 176 edges
4. `make_agents()` - 165 edges
5. `StrategyDNA` - 159 edges
6. `make_dna()` - 159 edges
7. `Side` - 150 edges
8. `StrategyVersion` - 140 edges
9. `make_context()` - 133 edges
10. `Trade` - 130 edges

## Surprising Connections (you probably didn't know these)
- `5. PositionCloseSettler boundary` --references--> `retire_generation()`  [INFERRED]
  ARCHITECTURE_REVIEW.md → backend/app/agents/lifecycle.py
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py
- `5. AI council as *context*, not oracle` --references--> `Decision`  [INFERRED]
  docs/architecture.md → backend/app/models/decision.py
- `Local` --references--> `Side`  [INFERRED]
  POSTGRESQL_MIGRATION_REPORT.md → backend/app/models/enums.py

## Import Cycles
- None detected.

## Communities (176 total, 33 thin omitted)

### Community 0 - "breeding.py"
Cohesion: 0.08
Nodes (32): BreedingResult, check_candidate_schema(), _most_correlated_pair(), Random, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the…, The least-diverse pair (O(n^2) over precomputed signatures; kept for…, Gate 1 of the candidate pipeline: the DNA must survive a strict round-trip… (+24 more)

### Community 1 - "sqlalchemy"
Cohesion: 0.06
Nodes (99): do_run_migrations(), run_migrations_online(), Which agents can be TESTED at their capital (Option D of the min-notional…, _components_of(), DB I/O for the analytics foundation. The ONLY module that writes, and it writes…, Wires compute_fitness to real persisted data, so Agent.fitness — read by…, Persists PerformanceMetric snapshots from real Trade/Agent state. Regime-…, Base (+91 more)

### Community 2 - "Trade"
Cohesion: 0.06
Nodes (77): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+69 more)

### Community 3 - "export.py"
Cohesion: 0.09
Nodes (26): _build(), _cell_value(), _convergence_rows(), export_report(), _fetch(), _flatten(), _plain(), Any (+18 more)

### Community 4 - "MarketDataService"
Cohesion: 0.09
Nodes (23): _as_float(), _chunks(), _dialect_insert(), MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion., Fetches the last `lookback_candles` candles and upserts them. Returns the… (+15 more)

### Community 5 - "get_settings"
Cohesion: 0.04
Nodes (48): get_settings(), create_app(), lifespan(), main(), migrate(), One-off: copy every row from the live Postgres database into a fresh SQLite…, test_settings_drive_the_config_including_the_formerly_dead_knobs(), _fast() (+40 more)

### Community 6 - "config.py"
Cohesion: 0.07
Nodes (39): 3. Current cross-community bridge nodes, What should NOT be refactored, Enum, field_validator, str, Centralized application configuration. Every environment-dependent value in the…, All gates required by spec section 40 before ANY live order. This does not…, Settings (+31 more)

### Community 7 - "test_strategy_dna.py"
Cohesion: 0.13
Nodes (26): _blend(), crossover(), Random, DNA crossover (spec section 25): combine two successful parents' DNA into one…, dna_distance(), A simple, interpretable [0, 1] distance: 0 = identical family and near-…, jitter(), mutate() (+18 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.07
Nodes (41): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, test_ws_reconnects_are_counted(), candle(), FakeServer, make() (+33 more)

### Community 9 - "decision_loop.py"
Cohesion: 0.04
Nodes (135): 12. Live/backtest duplication, 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _close_position() (+127 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (57): _atr(), compute_indicator(), compute_indicator_features(), compute_indicator_series(), _ema(), _feature_keys_cached(), _ind_adx(), _ind_atr() (+49 more)

### Community 11 - "MarketCandle"
Cohesion: 0.15
Nodes (36): active_flags(), Returns {flag_name: reason} for every currently-active flag., MarketCandle, clock_after_bar(), FakeHyperliquid, In-memory stand-in for HyperliquidClient (only the methods the service uses)., A clock value just after bar i has closed (past the 1.5s grace by default)., test_market_endpoint_reports_the_confirmed_candle_and_keeps_the_forming_one_separate() (+28 more)

### Community 12 - "test_evolution_pipeline.py"
Cohesion: 0.10
Nodes (43): events(), experiment_diff(), experiments(), generations(), AsyncSession, get, Baseline-vs-candidate diff for two experiment_ids (see…, summary() (+35 more)

### Community 13 - "run_backtest"
Cohesion: 0.09
Nodes (53): drop_random_candles(), Removes `fraction` of bars at random (missing-candle feed gaps): the indicator…, DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward() (+45 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.08
Nodes (51): advance_extremes(), Bar, evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of…, Peak/trough AFTER this bar, and whether trailing is now armed. (+43 more)

### Community 15 - "RiskDecision"
Cohesion: 0.14
Nodes (37): backtest_risk_check(), Routes backtest/adversarial position sizing through the real…, Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every… (+29 more)

### Community 16 - "PaperExecutionAdapter"
Cohesion: 0.09
Nodes (56): PaperExecutionAdapter, cycle(), make_context(), test_aligned_council_scales_size_up_and_records_audit_fields(), test_healthy_council_influences_size_but_agents_stay_independent(), test_high_confidence_opposed_council_vetoes_but_agent_signal_is_still_recorded(), test_incomplete_council_still_reaches_the_risk_engine_and_blocks_entry(), _round_trip() (+48 more)

### Community 17 - "routes/status.py"
Cohesion: 0.12
Nodes (24): _acquire_stream_slot(), _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37). (+16 more)

### Community 18 - "reset"
Cohesion: 0.40
Nodes (5): reset(), _fresh_metrics(), fixture, fixture, _reset_metrics()

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.11
Nodes (48): CouncilAnalysis, One analyst's structured response feeding into a CouncilDecision., ValueError, The response cannot be safely normalised. `reason` is a short machine-readable…, ResponseNormalizationError, analyst_server(), client_for(), gen() (+40 more)

### Community 20 - "test_oos_lockbox.py"
Cohesion: 0.07
Nodes (45): The ONLY data evolution/fitness/selection may see: everything up to and…, slice_train_validation(), evaluate_in_sample(), InSampleEvaluation, DataFrame, `frame`/`data` MUST be the train+validation frame (see…, compute_oos_score(), evaluate_oos_once() (+37 more)

### Community 21 - "Multi-Week Research Readiness Report"
Cohesion: 0.17
Nodes (11): 10. FINAL READINESS CHECK, 1. `as_of` BOUNDARY AUDIT, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 4. STANDARD EXPERIMENT COMPARISON FORMAT, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 9. RECOVERY TEST — real, on the actual dev environment, Known limitations (+3 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.13
Nodes (27): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), test_database_errors_are_counted_when_a_cycle_fails_on_the_database(), _cycles(), Worker cycle integrity (spec phases 1, 2, 21): confirmed candles only,… (+19 more)

### Community 23 - "lease.py"
Cohesion: 0.08
Nodes (33): datetime, utcnow(), db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id(), AsyncSession (+25 more)

### Community 24 - "run_council_cycle"
Cohesion: 0.12
Nodes (39): _decision(), history(), latest(), AsyncSession, get, AsyncSession, run_council_cycle(), CouncilDecision (+31 more)

### Community 25 - "helpers_agents.py"
Cohesion: 0.05
Nodes (90): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _atr(), _bollinger(), compute_features(), detect_regime(), _ema(), _macd() (+82 more)

### Community 26 - "RuleSet"
Cohesion: 0.14
Nodes (33): Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet, build_feature_view(), compute_population_features(), _entry_direction(), _eval_condition() (+25 more)

### Community 27 - "Agent"
Cohesion: 0.07
Nodes (60): AgentAlreadyDeadError, bankruptcy_threshold(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession, datetime, RuntimeError (+52 more)

### Community 28 - "StrategyFamily"
Cohesion: 0.25
Nodes (29): MarketRegime, StrategyFamily, ComparisonOperator, IndicatorConfig, Enum, field_validator, str, One named indicator instance the strategy depends on, e.g. {"name": "rsi",… (+21 more)

### Community 29 - "BacktestResult"
Cohesion: 0.10
Nodes (24): BacktestResult, BacktestTrade, persist_backtest_metrics(), persist_walk_forward_metrics(), Builds a StageMetrics row from a single backtest run (BACKTEST or OUT_OF_SAMPLE…, Builds a StageMetrics row (WALK_FORWARD stage) from a walk-forward report,…, Walk-forward testing (spec section 24). Rolls a train/test window forward…, Fraction of windows that were profitable — a simple, auditable stand-in for… (+16 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.06
Nodes (57): counter_value(), Ollama-driven strategy research (spec section 26). Ollama proposes candidate…, OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError (+49 more)

### Community 31 - "strategy_regime.py"
Cohesion: 0.09
Nodes (38): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+30 more)

### Community 32 - "test_experiment_runner.py"
Cohesion: 0.12
Nodes (29): _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments(), AsyncSession, Bar, DataFrame (+21 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.14
Nodes (27): current_fitness(), make_population(), (production compute_fitness, max drawdown) fed the way fitness_service feeds…, world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions(), _percentile_among_tested(), _precision() (+19 more)

### Community 34 - "ExecutionRequest"
Cohesion: 0.12
Nodes (19): Deterministic settlement at the modelled price when the engine keeps failing to…, _synthetic_exit_fill(), close(), slip(), ExecutionRequest, ExecutionResult, Submits an order and returns its fill result. Implementations MUST be…, fee_rate_for() (+11 more)

### Community 35 - "test_promotion_service.py"
Cohesion: 0.36
Nodes (11): _agent_with_fitness(), _passing_metrics(), asyncio, datetime, Champion/challenger promotion wiring: evaluate_promotion actually gets called…, Every rejection must be auditable, not just every promotion — until this was…, _seed_version(), test_no_promotion_under_minimum_track_record() (+3 more)

### Community 36 - "pipeline.py"
Cohesion: 0.06
Nodes (68): BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, Adds any indicator series not yet present (idempotent; a spec whose series all… (+60 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.07
Nodes (53): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, _build_epoch(), count_confirmed_candles() (+45 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.17
Nodes (21): compute_shadow(), rank_correlation(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, Spearman rank correlation between two scores over the agents that are ranked…, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, _agent(), _pop() (+13 more)

### Community 39 - "analyze_trade"
Cohesion: 0.10
Nodes (40): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+32 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.06
Nodes (62): AdversarialConfig, AdversarialReport, _clip01(), compute_robustness_score(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+54 more)

### Community 41 - "test_evolution_gate_and_champions.py"
Cohesion: 0.20
Nodes (19): NoValidCandidatesError, RuntimeError, Every candidate (and every replacement founder) failed the validation gate:…, Champion/challenger state that actually drives the population: current…, select_elite_versions(), ChampionStatus, _count(), _half_the_time() (+11 more)

### Community 42 - "compute_fitness"
Cohesion: 0.13
Nodes (31): _clip(), compute_fitness(), FitnessInputs, FitnessResult, FitnessWeights, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,… (+23 more)

### Community 43 - "routes/correlation.py"
Cohesion: 0.23
Nodes (14): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+6 more)

### Community 44 - "trades.py"
Cohesion: 0.14
Nodes (24): get_regime_performance(), get_side_performance(), get_strategy_performance(), list_trades(), AsyncSession, get, Breaks down closed-trade performance by strategy family. A trade's strategy is…, Breaks down closed-trade performance by the market regime that was active when… (+16 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.19
Nodes (19): Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, ShadowExecutionAdapter, walk_book(), book(), FakeBook, Shadow mode (spec phase 26): real book, hypothetical fills, no orders ever., Route the REAL HyperliquidClient through a recording transport: every request…, req() (+11 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "test_lifecycle_ports.py"
Cohesion: 0.14
Nodes (20): Ends a superseded generation cleanly: every open position is closed at…, retire_generation(), PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult, _AlwaysZeroBadDebtSettler (+12 more)

### Community 48 - "test_live_backtest_parity.py"
Cohesion: 0.21
Nodes (10): Deterministic fake exchange + candle factory shared by market/worker tests., _frame(), _funding(), DataFrame, parametrize, LIVE (paper, through the real worker cycle) vs BACKTEST parity (spec phases 5,…, Guard against a vacuous parity suite: across the scenarios stops, signal exits…, _run_live() (+2 more)

### Community 49 - "OllamaCallStats"
Cohesion: 0.09
Nodes (20): AICallStats, Protocol, T, The subset of OllamaCallStats the council actually reads., OllamaCallStats, BareMinimumClient, asyncio, OllamaClient itself is UNCHANGED and still works as the council's AI client -… (+12 more)

### Community 50 - "get_db"
Cohesion: 0.14
Nodes (18): exit_analytics(), _histogram(), AsyncSession, datetime, get, UUID, Exit-research dashboard data: MFE/MAE, realized R, post-exit movement, reversal…, list_open_positions() (+10 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.11
Nodes (14): 10. Market-data dependency direction, BookProvider, Protocol, HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context. (+6 more)

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.13
Nodes (35): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+27 more)

### Community 53 - "Side"
Cohesion: 0.15
Nodes (21): Side, asyncio, test_duplicate_client_order_id_is_rejected_not_double_filled(), test_live_adapter_refuses_to_place_orders_when_not_implemented(), test_paper_adapter_applies_fees_and_slippage(), test_paper_adapter_never_makes_network_calls(), Paper execution realism (spec phase 7): slippage, fees, latency, partial fills,…, _req() (+13 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (35): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+27 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.18
Nodes (24): _agent(), _candle(), _migration_module(), _order(), _position(), Impossible states cannot be written (spec phase 26): the DATABASE rejects them,…, Plain ids of an agent - usable after a rollback has expired the ORM object., _Ref (+16 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.18
Nodes (20): champion_evidence_ok(), estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, _samples() (+12 more)

### Community 57 - "test_worker_fencing.py"
Cohesion: 0.14
Nodes (23): LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _counts(), _keeper(), Worker fencing (spec phase 3): a worker that loses its lease/heartbeat stops…, Deterministic order ids + an in-process idempotency guard: a rollback must…, Paper engine that lets a rival worker take over the lease while the cycle is in… (+15 more)

### Community 58 - "test_sqlite_locking.py"
Cohesion: 0.24
Nodes (11): factory(), fixture, SQLite write-lock behaviour on a real WAL file shared by two connections…, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle() (+3 more)

### Community 59 - "test_council_failclosed.py"
Cohesion: 0.06
Nodes (30): 11. AI/Ollama dependency direction, OllamaClient, OllamaKeyHealth, Returns (key, key_index). key_index is the position in OLLAMA_API_KEYS (never…, Safe operational state: positions/statuses only, never secrets., True if at least one credential could serve a request right now (or no…, Re-read credentials from settings WITHOUT a restart. A key whose value is…, Cooldown for a 429: honour Retry-After (seconds), else an escalating default… (+22 more)

### Community 60 - "Initiative 1 — CLOSED"
Cohesion: 0.33
Nodes (6): 1. Objective, 3. Exact change, 5. Intentional differences left untouched, 6. Remaining future candidates (not started, not scheduled), 7. Status, Initiative 1 — CLOSED

### Community 61 - "test_as_of_boundaries.py"
Cohesion: 0.12
Nodes (35): _is_uuid(), _ms(), AsyncSession, datetime, Rebuild the matrix for `computation_version` (derived aggregate: DELETE the…, `as_of`, when given, bounds every piece of data this refresh may see (candles,…, refresh_strategy_regime_matrix(), refresh_trade_analytics() (+27 more)

### Community 62 - "Bias"
Cohesion: 0.08
Nodes (52): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), apply_judge(), compute_consensus() (+44 more)

### Community 63 - "Local Migration"
Cohesion: 0.18
Nodes (10): Future Production Migration, Local Migration, PostgreSQL Migration Guide, Prerequisites, Step 2 — Apply the schema, Step 3 — Migrate the data, Step 4 — Verify, Step 5 — Run the app on Postgres (+2 more)

### Community 64 - "test_postgres_concurrency.py"
Cohesion: 0.22
Nodes (8): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, make_raw_candle(), i-th 1m candle after T0, Hyperliquid wire format., _raws(), REAL PostgreSQL behaviour (spec phase 25): true multi-connection races, the…, test_a_lock_wait_times_out_instead_of_blocking_forever(), test_session_timeouts_are_applied_to_every_pooled_connection()

### Community 65 - "test_correlation.py"
Cohesion: 0.18
Nodes (21): entry_condition_similarity(), feature_similarity(), Jaccard similarity over each DNA's (indicator name, sorted params) set plus its…, Jaccard similarity over (feature, operator, value) entry conditions, averaged…, No `now` override -> real wall-clock time, exactly the pre-existing behavior., test_correlation_report_default_now_is_backward_compatible(), test_correlation_report_now_override_excludes_trades_closed_after_it(), _add_trade() (+13 more)

### Community 66 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 67 - "prune_decisions.py"
Cohesion: 0.29
Nodes (12): count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,…, Deletes no-op rows older than `cutoff` in batches. Returns rows deleted. (+4 more)

### Community 68 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (19): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+11 more)

### Community 69 - "pydantic"
Cohesion: 0.29
Nodes (9): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, AdversarialTestReportOut, BaseModel, ScenarioBreakdownOut (+1 more)

### Community 70 - "test_funding.py"
Cohesion: 0.38
Nodes (11): FundingPayment, One funding settlement charged to (or credited to) one position. The (position,…, _dna(), _hold_across(), Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.14
Nodes (13): 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Experiment Guide, From the CLI (+5 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "test_db_location.py"
Cohesion: 0.09
Nodes (20): model_validator, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real…, Three processes share the database. If their pools alone could exceed the…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch… (+12 more)

### Community 74 - "compute_agent_performance_metric"
Cohesion: 0.27
Nodes (10): compute_agent_performance_metric(), AsyncSession, Builds (does not persist) a PerformanceMetric snapshot for `agent` from its…, Backward-compatible default: as_of=None preserves the original unbounded…, UTCDateTime stores/reads timezone-aware UTC throughout (app/models/base.py) -…, _seed_agent_with_trades(), test_as_of_boundary_at_utc_midnight_is_inclusive_and_timezone_consistent(), test_compute_agent_performance_metric_as_of_with_empty_future_still_returns_a_finite_metric() (+2 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.12
Nodes (22): _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess, fixture (+14 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.21
Nodes (19): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids(), Agents that cannot reach the exchange minimum order at their capital are… (+11 more)

### Community 78 - "agents.py"
Cohesion: 0.22
Nodes (18): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), list_agents(), AsyncSession, get (+10 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.16
Nodes (12): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+4 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.23
Nodes (13): alembic_autogenerate, alembic_migration, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs() (+5 more)

### Community 81 - "dashboard.py"
Cohesion: 0.35
Nodes (10): agent_metrics(), champions_analysis(), equity(), fitness_components(), overview(), AsyncSession, get, ranking_stability() (+2 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.21
Nodes (11): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_dna_field_is_either_runtime_covered_or_documented_metadata() (+3 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.23
Nodes (12): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+4 more)

### Community 84 - "_build_scenario"
Cohesion: 0.19
Nodes (13): _build_scenario(), asyncio, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, _run_fixed_scenario(), test_fixed_scenario_is_internally_consistent(), test_fixed_scenario_matches_the_captured_baseline() (+5 more)

### Community 85 - "routes/regime_validation.py"
Cohesion: 0.33
Nodes (8): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID, BaseModel, RegimeStatsOut, RegimeValidationReportOut

### Community 86 - "make_agents"
Cohesion: 0.10
Nodes (42): make_agents(), make_dna(), Independent agents, per-agent failure isolation and DB-level idempotency (spec…, test_a_failing_agent_is_isolated_and_the_rest_of_the_population_trades(), submit_order(), test_client_order_id_is_unique_in_the_database(), test_closed_positions_do_not_block_a_new_open_one(), test_database_rejects_a_second_decision_for_the_same_agent_and_candle() (+34 more)

### Community 87 - "evaluate_fitness_versions.py"
Cohesion: 0.13
Nodes (25): _bucket_report(), _capture_rate(), _evaluate_version(), _future_for(), _future_profit_factor(), _grid_as_of_points(), _latest_upto(), _load_context() (+17 more)

### Community 88 - "conftest.py"
Cohesion: 0.23
Nodes (9): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+1 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.29
Nodes (9): ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat(), main(), READ-ONLY side-by-side report of the production fitness and the SHADOW (Phase… (+1 more)

### Community 90 - "test_champion_challenger_service.py"
Cohesion: 0.18
Nodes (32): advance_pipeline_stage(), Attempts to move `strategy_version_id` one step forward in the pipeline.…, add_promotion_evidence(), The full evidence set the promotion gate demands beyond PnL: adversarial…, asyncio, datetime, ChampionChallengerEngine: the Candidate -> Validation -> Challenger ->…, This is the one place advance_pipeline_stage calls evaluate_and_promote — no… (+24 more)

### Community 91 - "report_trade_quality.py"
Cohesion: 0.14
Nodes (20): cohort_stats(), _flat(), main(), _pearson(), _ranks(), READ-ONLY fitness -> future-performance report (Reports F and H). python -m…, Average ranks (ties share the mean rank) — deterministic., One cohort (as_of, horizon): the study's statistics, over flattened rows. (+12 more)

### Community 92 - "test_fitness_edge_cases.py"
Cohesion: 0.18
Nodes (16): capped_profit_factor(), compute_trade_stats(), _max_streaks(), Pure trade-statistics engine feeding PerformanceMetric snapshots.…, gross_win / gross_loss; the no-loss case is capped, and no evidence at all (no…, Longest consecutive-win and consecutive-loss streaks, in trade order. Flat…, TradeStatsResult, inp() (+8 more)

### Community 93 - "test_api_endpoints.py"
Cohesion: 0.14
Nodes (15): publish_status(), candle(), Dashboard/API surface (spec phases 35-37): confirmed-candle market view,…, test_evolution_endpoints(), test_export_report_is_one_xlsx_with_every_dashboard_section(), test_metrics_endpoint_is_operator_only_and_exposes_the_required_series(), test_ollama_health_endpoint_needs_operator_and_never_leaks_key_values(), test_population_and_agent_detail_endpoints() (+7 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (11): cmd_backup(), cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), env_value(), is_running() (+3 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "test_check_constraints_are_enforced_by_postgres_itself"
Cohesion: 0.67
Nodes (3): test_check_constraints_are_enforced_by_postgres_itself(), order(), pend()

### Community 97 - "test_backtesting.py"
Cohesion: 0.18
Nodes (18): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+10 more)

### Community 98 - "logging.py"
Cohesion: 0.09
Nodes (33): argparse, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory(), _is_secret_key() (+25 more)

### Community 99 - "test_promotion_evidence.py"
Cohesion: 0.16
Nodes (26): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, evaluate_and_promote(), Evaluates whether `strategy_version_id`'s metrics at `stage` justify promoting…, test_criteria_come_from_settings() (+18 more)

### Community 100 - "Position"
Cohesion: 0.09
Nodes (39): _cancel_stale_pending(), _council_context(), _load_funding(), protect_open_positions(), AsyncSession, DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, Protective-only pass for `context`'s bar: funding, stop, take-profit, trailing,… (+31 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "test_gap_cycle.py"
Cohesion: 0.29
Nodes (9): _seed_always_long_population(), _crash(), _delete_bar(), _open_positions_at_bar_398(), Gap recovery through the REAL cycle path (spec phase 14): gap -> backfill ->…, test_recovered_gap_resumes_trading(), test_unrecoverable_gap_halts_new_entries_but_open_positions_are_still_protected(), usefixtures (+1 more)

### Community 104 - "paper_adapter.py"
Cohesion: 0.09
Nodes (21): ABC, 6. ExecutionEngine boundary, ExecutionEngine, Execution engine abstraction (spec section 19). Every trading mode…, `immediate`: an order is filled when submitted (shadow/live: against the real…, The transaction holding these orders rolled back: release their ids (one agent,…, The cycle's transaction committed: the claimed ids are now durable (DB unique…, Release any network resources (no-op for pure-simulation engines). (+13 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "run_cycle.py"
Cohesion: 0.06
Nodes (34): asyncio, _escape(), _fmt(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint…, record_db_error() (+26 more)

### Community 108 - "test_api_security.py"
Cohesion: 0.05
Nodes (47): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+39 more)

### Community 109 - "test_fitness_versions.py"
Cohesion: 0.13
Nodes (24): AgentFacts, The immutable facts of an agent needed at any T (no mutable state)., Hardcoded to today's production values (fitness_engine.FitnessWeights defaults…, _v1_weights(), _facts(), datetime, parametrize, Regression coverage for app.analytics.fitness_versions and the… (+16 more)

### Community 110 - "OrderStatus"
Cohesion: 0.21
Nodes (17): ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter, OrderStatus (+9 more)

### Community 111 - "compute_generation_correlation_report"
Cohesion: 0.18
Nodes (18): apply_diversity_pressure(), _compute_behavioral_correlations(), compute_generation_correlation_report(), DiversityPressureAction, GenerationCorrelationReport, persist_generation_correlation(), AsyncSession, datetime (+10 more)

### Community 112 - "routes/reality_gap.py"
Cohesion: 0.29
Nodes (10): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…, BaseModel, RealityGapChainReportOut (+2 more)

### Community 113 - "helpers_shadow.py"
Cohesion: 0.15
Nodes (13): ShadowAgentInput, TradeEvidence, _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, Pure exposure scaling: k times the size, identical trading decisions. (+5 more)

### Community 114 - "test_fitness_forward.py"
Cohesion: 0.24
Nodes (17): forward_window(), The honest (T, T+h] window: truncated at the earliest real boundary., facts(), point(), Phase 3 tests: look-ahead protection, historical reconstruction, censoring,…, test_dead_agent_reconstruction_endstops_at_death(), test_forward_window_uses_only_trades_after_t(), test_full_coverage_when_no_boundary_hits() (+9 more)

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "normalization.py"
Cohesion: 0.19
Nodes (15): BoundedResponse, _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any (+7 more)

### Community 118 - "fitness_forward.py"
Cohesion: 0.18
Nodes (19): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), _overlaps_oos_window(), datetime (+11 more)

### Community 119 - "StrategyVersion"
Cohesion: 0.13
Nodes (32): create_generation(), UUID, Creates a new Generation row and one Agent per strategy_version_id, each…, _preserve_family_distribution(), AsyncSession, Ranks every agent in `generation_number` by `Agent.fitness` (falling back to…, Selects survivors from `generation_number`, breeds children via…, Biases fresh-DNA injection toward minority families apply_diversity_pressure… (+24 more)

### Community 121 - "_mock_transport"
Cohesion: 0.21
Nodes (11): _mock_transport(), asyncio, Root cause of the reported intermittent analyst 401s: with multiple…, test_401_on_every_key_exhausts_retries_and_raises_auth_error(), test_401_on_one_key_is_retried_and_recovers_on_the_next_key(), test_429_is_retried_then_raises_after_exhausting_retries(), test_invalid_json_raises_response_error(), test_schema_mismatch_raises_response_error() (+3 more)

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "champion_challenger_service.py"
Cohesion: 0.22
Nodes (14): 9. Database dependency direction, AsyncSession, Context manager for a transactional unit of work outside a request. Commits on…, session_scope(), _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report() (+6 more)

### Community 135 - "Post-Refactoring Architecture Review"
Cohesion: 0.14
Nodes (13): 13. Test architecture, 14. Any newly introduced coupling, 1. Current Graphify statistics, 2. Current high-degree nodes, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem) (+5 more)

### Community 137 - "test_next_open_execution.py"
Cohesion: 0.30
Nodes (13): _orders(), _pos(), Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close…, Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the…, test_a_pending_entry_that_was_not_filled_on_the_next_bar_is_never_filled_late(), test_min_notional_rejects_a_sub_ten_dollar_order(), test_pending_entry_fills_at_the_next_bars_open_not_the_signal_close(), test_pending_entry_is_cancelled_when_entries_are_halted_at_the_fill_bar() (+5 more)

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 140 - "test_config_audit.py"
Cohesion: 0.25
Nodes (10): _python_sources(), No fake configuration (spec phase 29) and no dead code (phase 30). Every…, Everything goes through Settings (one validated, documented surface)., risk_engine, market_data_service and the setting used to carry three copies of…, _readers(), test_every_setting_has_a_runtime_reader_or_a_documented_reason(), test_no_module_reads_the_environment_directly(), test_removed_dead_code_stays_removed() (+2 more)

### Community 141 - "correlation_service.py"
Cohesion: 0.15
Nodes (22): _condition_set(), exit_condition_similarity(), feature_set(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the…, ruleset_signature(), ruleset_signature_similarity() (+14 more)

### Community 142 - "list_challengers"
Cohesion: 0.31
Nodes (9): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+1 more)

### Community 143 - "test_adversarial_service.py"
Cohesion: 0.36
Nodes (8): asyncio, DataFrame, UUID, Wires run_adversarial_suite (previously uncalled anywhere outside its own test)…, _seed_strategy_version(), test_run_and_persist_adversarial_suite_persists_a_report(), test_run_and_persist_adversarial_suite_raises_for_unknown_strategy_version(), _trending_candles()

### Community 144 - "test_cooldown_limits.py"
Cohesion: 0.44
Nodes (8): _dna(), Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe(), test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day(), test_no_cooldown_configured_allows_immediate_reentry(), _trade_round_trip()

### Community 146 - "code_only"
Cohesion: 0.18
Nodes (10): code_only(), Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, _sources(), test_every_http_post_in_the_codebase_targets_an_allowlisted_endpoint_or_is_internal(), test_no_module_contains_order_sending_signing_or_wallet_code(), test_the_scanner_itself_catches_real_violations_but_ignores_documentation(), For --cluster-only (+2 more)

### Community 150 - "routes/market.py"
Cohesion: 0.39
Nodes (7): get_market_history(), get_market_snapshot(), AsyncSession, get, The last CONFIRMED (closed) candle is the source of truth; the still-forming…, CandlePoint, MarketSnapshot

### Community 151 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.36
Nodes (7): _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., One row of headline aggregates, computed identically against either engine, for…, upgrade_schema()

### Community 152 - "refresh_fitness_forward"
Cohesion: 0.43
Nodes (6): For every recorded FitnessScore snapshot (plus an hourly reconstruction grid…, refresh_fitness_forward(), _corr_upto(), _latest_upto(), _stage_evidence_upto(), 1.1 Confirmed already-safe (no change)

### Community 153 - "report_strategy_regime.py"
Cohesion: 0.48
Nodes (6): _flat(), _fmt(), _fmt_pct(), main(), READ-ONLY Strategy x Regime report (Reports A and G). python -m…, render()

### Community 154 - "set_flag"
Cohesion: 0.40
Nodes (5): AsyncSession, Read/write helpers for durable system flags (kill switch, data-gap halt)., Single string (or None) the risk engine uses to block NEW entries., set_flag(), trading_halt_reason()

### Community 155 - "StrategyDNA"
Cohesion: 0.10
Nodes (36): Strategy diversity tracking (spec section 27/29). Measures how similar two DNA…, _spec_set(), Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), CooldownConfig, PositionSizing, BaseModel, model_validator (+28 more)

### Community 156 - "fitness_versions.py"
Cohesion: 0.40
Nodes (4): FitnessVersionSpec, Research-only registry of named fitness formula/timing variants for offline…, A smooth alternative to the hard clip(-1, 1): tanh never fully flattens two…, _signed_sqrt_tanh()

### Community 157 - "_alembic"
Cohesion: 0.50
Nodes (5): _alembic(), _insert(), Path, test_migration_downgrade_removes_the_constraints(), test_migration_refuses_when_existing_rows_violate_a_constraint_and_changes_nothing()

### Community 159 - "test_snapshots_and_lifecycle.py"
Cohesion: 0.14
Nodes (18): _dna_is_immutable(), ImmutableRecordError, listens_for, RuntimeError, _snapshot_is_undeletable(), _snapshot_is_write_once(), _alembic(), Immutable snapshots (phase 32), death & generation rollover (phase 31). (+10 more)

### Community 160 - "test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison"
Cohesion: 0.50
Nodes (4): _crash_bar(), _positions_at(), test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison(), test_skipped_catchup_bars_still_protect_open_positions()

### Community 175 - "_bar_ms"
Cohesion: 0.67
Nodes (3): _bar_ms(), Bar, Interval of the candle grid (median diff), 60_000 fallback.

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1268 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `sqlalchemy`, `Trade`, `MarketDataService`, `config.py`, `Post-Refactoring Architecture Review`, `decision_loop.py`, `test_next_open_execution.py`, `MarketCandle`, `test_evolution_pipeline.py`, `run_backtest`, `test_stops_trailing.py`, `RiskDecision`, `test_config_audit.py`, `routes/status.py`, `test_cooldown_limits.py`, `PaperExecutionAdapter`, `test_oos_lockbox.py`, `routes/market.py`, `test_worker_cycle.py`, `run_council_cycle`, `helpers_agents.py`, `lease.py`, `Agent`, `BacktestResult`, `test_ollama_failure_modes.py`, `test_snapshots_and_lifecycle.py`, `ExecutionRequest`, `test_promotion_service.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `test_shadow_mode.py`, `test_lifecycle_ports.py`, `test_live_backtest_parity.py`, `HyperliquidClient`, `test_regime_validation_engine.py`, `Side`, `test_worker_fencing.py`, `test_council_failclosed.py`, `Bias`, `test_postgres_concurrency.py`, `prune_decisions.py`, `test_council_deadline.py`, `test_funding.py`, `test_untestable_agents.py`, `make_agents`, `conftest.py`, `test_champion_challenger_service.py`, `test_api_endpoints.py`, `logging.py`, `test_promotion_evidence.py`, `Position`, `test_gap_cycle.py`, `paper_adapter.py`, `run_cycle.py`, `test_api_security.py`, `OrderStatus`, `fitness_forward.py`, `StrategyVersion`?**
  _High betweenness centrality (0.126) - this node is a cross-community bridge._
- **Why does `OllamaClient` connect `test_council_failclosed.py` to `sqlalchemy`, `_mock_transport`, `test_council_deadline.py`, `config.py`, `Post-Refactoring Architecture Review`, `test_gap_cycle.py`, `decision_loop.py`, `paper_adapter.py`, `run_cycle.py`, `PaperExecutionAdapter`, `OllamaCallStats`, `test_ollama_schema_normalization.py`, `test_worker_cycle.py`, `helpers_agents.py`, `Initiative 1 — CLOSED`, `test_ollama_failure_modes.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `breeding.py`, `sqlalchemy`, `Trade`, `Post-Refactoring Architecture Review`, `decision_loop.py`, `test_evolution_pipeline.py`, `correlation_service.py`, `RiskDecision`, `PaperExecutionAdapter`, `routes/status.py`, `refresh_fitness_forward`, `helpers_agents.py`, `test_promotion_service.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_evolution_gate_and_champions.py`, `trades.py`, `test_lifecycle_ports.py`, `get_db`, `test_regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `test_worker_fencing.py`, `test_as_of_boundaries.py`, `test_postgres_concurrency.py`, `test_correlation.py`, `compute_agent_performance_metric`, `test_untestable_agents.py`, `agents.py`, `make_agents`, `evaluate_fitness_versions.py`, `shadow_rows_for_generation`, `test_champion_challenger_service.py`, `test_fitness_edge_cases.py`, `test_promotion_evidence.py`, `Position`, `paper_adapter.py`, `compute_generation_correlation_report`, `StrategyVersion`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 104 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 104 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._