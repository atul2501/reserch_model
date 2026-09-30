# Graph Report - reserch_model  (2026-09-30)

## Corpus Check
- 333 files · ~249,038 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .service 4, (none) 3, .ini 2)

## Summary
- 4137 nodes · 15504 edges · 158 communities (134 shown, 24 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2178 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2e4c99b4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- compute_features
- enums.py
- compute_and_persist_agent_fitness
- _Sheet
- MarketDataService
- get_settings
- test_live_safety.py
- compare_fitness_correction.py
- test_ws_client.py
- Agent
- indicators.py
- MarketCandle
- test_evolution_pipeline.py
- run_backtest
- test_stops_trailing.py
- RiskDecision
- make_agents
- test_swing_points.py
- test_metrics_emission.py
- test_ollama_schema_normalization.py
- test_frozen_oos_epoch.py
- Multi-Week Research Readiness Report
- test_worker_cycle.py
- lease.py
- test_council_failclosed.py
- MarketContext
- strategy_dna.py
- AgentStatus
- StrategyDNA
- backtesting/engine.py
- test_ollama_failure_modes.py
- test_strategy_regime_matrix.py
- lockbox.py
- test_shadow_fitness_synthetic.py
- ExecutionRequest
- test_promotion_service.py
- pipeline.py
- dataset.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- test_evolution_gate_and_champions.py
- compute_fitness
- routes/correlation.py
- trades.py
- test_shadow_mode.py
- families.py
- Trade
- test_ws_ingest_and_smoke.py
- test_council_integration.py
- sqlalchemy
- HyperliquidClient
- regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- test_worker_fencing.py
- test_sqlite_locking.py
- OllamaClient
- below_min_order_notional
- test_analytics_store.py
- Bias
- Local Migration
- test_postgres_concurrency.py
- test_as_of_boundaries.py
- AbuseGuard
- prune_decisions.py
- test_council_deadline.py
- get_adversarial_report_history
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- Settings
- performance_metrics_service.py
- cycle.py
- test_postgres.py
- PositionSizing
- set_kill_switch
- test_analytics_migration.py
- test_migrations.py
- dashboard_service.py
- test_dna_runtime_coverage.py
- secret_scan.py
- test_decision_loop_characterization.py
- get_latest_regime_validation
- test_dashboard_api.py
- evaluate_fitness_versions.py
- migrate_sqlite_to_postgres.py
- shadow_rows_for_generation
- StrategyStage
- report_agent_evidence.py
- test_fitness_edge_cases.py
- 24-Hour Data Validation & Next-Phase Execution — Research Report
- run.sh
- test_dashboard_js.py
- Side
- test_backtesting.py
- config.py
- test_promotion_evidence.py
- Decision
- WsCandle
- ImmutableAnalyticsRecordError
- test_gap_cycle.py
- 1. Current architecture (as it actually is, not as the graph implies)
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- run_cycle.py
- routes/status.py
- test_fitness_versions.py
- ExecutionVenue
- shadow_summary
- schemas/reality_gap.py
- helpers_shadow.py
- test_fitness_forward.py
- graphify reference: extra exports and benchmark
- schemas/adversarial.py
- alembic_config
- fitness_forward.py
- StrategyVersion
- MarketRegime
- graphify reference: query, path, explain
- test_reality_gap_engine.py
- purge_secrets_from_history.sh
- test_margin_liquidation.py
- get_regime_performance
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- correlation_service.py
- tradability.py
- test_regime_validation_engine.py
- graphify reference: GitHub clone and cross-repo merge
- test_no_live_orders.py
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md
- helpers_agents.py
- ImmutableRecordError
- test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison
- constraints.py
- test_paper_cycles_with_a_council_only_ever_touch_read_endpoints
- graphify reference: transcribe video and audio

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

## Communities (158 total, 24 thin omitted)

### Community 0 - "compute_features"
Cohesion: 0.19
Nodes (20): _atr(), _bollinger(), compute_features(), _ema(), _macd(), DataFrame, Series, Deterministic feature engine (spec section 7). Takes a rolling window of closed… (+12 more)

### Community 1 - "enums.py"
Cohesion: 0.08
Nodes (76): DB I/O for the analytics foundation. The ONLY module that writes, and it writes…, Wires compute_fitness to real persisted data, so Agent.fitness — read by…, Base, ChampionChallengerEngine: walks a StrategyVersion through the Candidate ->…, Wires evolution/champion.py's promotion-decision logic (previously uncalled) to…, AdversarialTestReport, Persisted adversarial-suite results — insert-only, one row per run, so…, Trading agent — one independent paper/shadow/live account. Spec sections 12-16:… (+68 more)

### Community 2 - "compute_and_persist_agent_fitness"
Cohesion: 0.21
Nodes (12): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+4 more)

### Community 3 - "_Sheet"
Cohesion: 0.16
Nodes (12): _build(), _cell_value(), _fetch(), _flatten(), _plain(), Any, AsyncSession, datetime (+4 more)

### Community 4 - "MarketDataService"
Cohesion: 0.10
Nodes (18): _as_float(), _chunks(), _dialect_insert(), GapReport, MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion. (+10 more)

### Community 5 - "get_settings"
Cohesion: 0.04
Nodes (42): get_settings(), create_app(), lifespan(), _fast(), fixture, api(), _db(), fixture (+34 more)

### Community 6 - "test_live_safety.py"
Cohesion: 0.15
Nodes (23): 6. ExecutionEngine boundary, Enum, str, TradingMode, HyperliquidLiveExecutionAdapter, get_execution_engine(), LiveSafetyGateError, RuntimeError (+15 more)

### Community 7 - "compare_fitness_correction.py"
Cohesion: 0.13
Nodes (19): Fraction of windows that were profitable — a simple, auditable stand-in for…, _clip(), compute_oos_score(), [0, 1]. Zero without enough trades to say anything. Otherwise: (0.4 *…, main(), _old_compute_oos_score(), READ-ONLY before/after comparison for the lockbox.py compute_oos_score fix…, The formula exactly as it stood before the confidence-scaling fix. (+11 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.10
Nodes (36): test_ws_reconnects_are_counted(), candle(), FakeServer, make(), Hyperliquid WebSocket transport (spec phase 17) against an in-process fake…, Scriptable exchange: every accepted connection runs `script(ws, conn_index)`., A DB hiccup must not turn the exchange's retry of the SAME frame into a…, _run_until() (+28 more)

### Community 9 - "Agent"
Cohesion: 0.07
Nodes (70): 2. Current high-degree nodes, 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _close_position() (+62 more)

### Community 10 - "indicators.py"
Cohesion: 0.06
Nodes (68): jitter(), _mutate_indicator_period(), _mutate_ruleset_thresholds(), Random, DNA mutation (spec section 25). Produces a new, independently-valid StrategyDNA…, Changes one declared indicator's period AND rewrites every rule that referenced…, compute_population_features(), DataFrame (+60 more)

### Community 11 - "MarketCandle"
Cohesion: 0.17
Nodes (31): MarketCandle, clock_after_bar(), FakeHyperliquid, In-memory stand-in for HyperliquidClient (only the methods the service uses)., A clock value just after bar i has closed (past the 1.5s grace by default)., test_market_endpoint_reports_the_confirmed_candle_and_keeps_the_forming_one_separate(), Closed-candle data integrity (spec phases 1, 18): only confirmed candles reach…, Records the bind-parameter count of every INSERT sent through the session,… (+23 more)

### Community 12 - "test_evolution_pipeline.py"
Cohesion: 0.18
Nodes (17): Scheduled evolution pipeline (spec phases 22-24, 29-32): gates, the full…, The sealed epoch is frozen (possibly days old); closing the retiring…, Same seed + same survivors -> identical child DNA (breeding is no longer…, A StrategyVersion stuck mid-pipeline (e.g. waiting out its observation window)…, _seed_candles(), _seed_population(), test_a_failed_cycle_is_recorded_and_leaves_the_population_intact(), test_extinct_population_restarts_from_fresh_founders_never_reviving_the_dead() (+9 more)

### Community 13 - "run_backtest"
Cohesion: 0.10
Nodes (51): DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward(), _simulate(), validate() (+43 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.20
Nodes (26): advance_extremes(), Bar, bar_time(), evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of… (+18 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (40): Routes backtest/adversarial position sizing through the real…, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every…, RiskCheckInput, RiskCheckResult, _python_sources() (+32 more)

### Community 16 - "make_agents"
Cohesion: 0.08
Nodes (77): 1. Current Graphify statistics, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), publish_status(), set_flag(), Residual of the cash identity (0.0 when the books balance). balance == starting…, reconcile(), cycle() (+69 more)

### Community 17 - "test_swing_points.py"
Cohesion: 0.18
Nodes (19): Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), _candles(), _path(), DataFrame, parametrize, Series, Swing-structure features: higher-high / higher-low / lower-high / lower-low,… (+11 more)

### Community 18 - "test_metrics_emission.py"
Cohesion: 0.10
Nodes (26): counter_value(), _key(), observe(), One place to count database failures (connection loss, deadlock, constraint…, record_db_error(), render_prometheus(), reset(), CycleOutcome (+18 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.08
Nodes (63): CouncilAnalysis, One analyst's structured response feeding into a CouncilDecision., _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json() (+55 more)

### Community 20 - "test_frozen_oos_epoch.py"
Cohesion: 0.08
Nodes (47): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), OosEvaluation, listens_for, RuntimeError, load_epoch_candles() (+39 more)

### Community 21 - "Multi-Week Research Readiness Report"
Cohesion: 0.10
Nodes (18): uvicorn's AccessFormatter unpacks record.args into 5 fields; the redaction…, test_uvicorn_access_log_formats_and_is_redacted(), 10. FINAL READINESS CHECK, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 4. STANDARD EXPERIMENT COMPARISON FORMAT, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 7. RESEARCH DASHBOARD (+10 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.16
Nodes (23): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), _cycles(), Worker cycle integrity (spec phases 1, 2, 21): confirmed candles only,…, The council can take ~45s; the bar is re-verified right before decisions and a… (+15 more)

### Community 23 - "lease.py"
Cohesion: 0.09
Nodes (30): db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id(), AsyncSession, Durable single-worker lease (spec: only one active decision worker). The…, Holds the lease for the worker's lifetime with a renewing heartbeat. (+22 more)

### Community 24 - "test_council_failclosed.py"
Cohesion: 0.09
Nodes (44): AsyncSession, run_council_cycle(), CouncilDecision, One consensus outcome for one candle — shared by all agents., council_on(), fixture, Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, test_a_verdict_for_another_candle_is_never_applied() (+36 more)

### Community 25 - "MarketContext"
Cohesion: 0.09
Nodes (41): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, minimal_context(), A NEUTRAL-feature context for one CONFIRMED stored candle…, MarketContext, MomentumFeatures, PriceActionFeatures, BaseModel (+33 more)

### Community 26 - "strategy_dna.py"
Cohesion: 0.09
Nodes (47): ComparisonOperator, Condition, BaseModel, Enum, str, Strategy DNA schema (spec section 10). This is the contract between the…, What Ollama (or the mutation/crossover engine) must produce for a new candidate…, A single testable condition against a named feature/indicator output, e.g.… (+39 more)

### Community 27 - "AgentStatus"
Cohesion: 0.11
Nodes (37): AgentAlreadyDeadError, bankruptcy_threshold(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession, RuntimeError, UUID (+29 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.18
Nodes (31): IndicatorConfig, field_validator, model_validator, Combinations the schema ACCEPTS but that silently do nothing (or something…, One named indicator instance the strategy depends on, e.g. {"name": "rsi",…, StrategyDNA, _all_rulesets(), Rule features that are neither static nor produced by a declared indicator.… (+23 more)

### Community 29 - "backtesting/engine.py"
Cohesion: 0.06
Nodes (51): BacktestData, BacktestResult, BacktestTrade, Event-driven backtesting engine (spec section 22; phase 22 "backtest parity").…, compute_missed_trade_stats(), compute_reality_gap(), latest_stage_metrics(), _metric_value() (+43 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.07
Nodes (53): Ollama-driven strategy research (spec section 26). Ollama proposes candidate…, OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError (+45 more)

### Community 31 - "test_strategy_regime_matrix.py"
Cohesion: 0.08
Nodes (36): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+28 more)

### Community 32 - "lockbox.py"
Cohesion: 0.08
Nodes (57): Experiment, Experiment registry, research epochs (dataset registry) and the OOS lockbox…, ResearchEpoch, _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments() (+49 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.12
Nodes (30): champion_evidence_ok(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, make_population(), world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions() (+22 more)

### Community 34 - "ExecutionRequest"
Cohesion: 0.14
Nodes (14): ExecutionRequest, ExecutionResult, Submits an order and returns its fill result. Implementations MUST be…, new_client_order_id(), Deterministic idempotency key: same (agent, decision, action) always yields the…, asyncio, test_duplicate_client_order_id_is_rejected_not_double_filled(), test_live_adapter_refuses_to_place_orders_when_not_implemented() (+6 more)

### Community 35 - "test_promotion_service.py"
Cohesion: 0.11
Nodes (35): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+27 more)

### Community 36 - "pipeline.py"
Cohesion: 0.08
Nodes (39): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation… (+31 more)

### Community 37 - "dataset.py"
Cohesion: 0.11
Nodes (31): _build_epoch(), count_confirmed_candles(), EpochIntegrityError, fingerprint_frame(), get_active_epoch(), get_or_create_epoch(), load_confirmed_candles(), load_funding() (+23 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.19
Nodes (21): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), _agent(), _pop() (+13 more)

### Community 39 - "analyze_trade"
Cohesion: 0.16
Nodes (29): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+21 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.09
Nodes (50): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+42 more)

### Community 41 - "test_evolution_gate_and_champions.py"
Cohesion: 0.08
Nodes (51): BreedingResult, check_candidate_schema(), NoValidCandidatesError, AsyncSession, Random, RuntimeError, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the… (+43 more)

### Community 42 - "compute_fitness"
Cohesion: 0.16
Nodes (27): _clip(), compute_fitness(), FitnessInputs, FitnessResult, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,…, [-1, 1]. A 0% win rate over real trades is the WORST score (-1), not neutral;… (+19 more)

### Community 43 - "routes/correlation.py"
Cohesion: 0.23
Nodes (14): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+6 more)

### Community 44 - "trades.py"
Cohesion: 0.09
Nodes (41): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), list_agents(), AsyncSession, get (+33 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.13
Nodes (23): L2Book, parse_book(), Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter, walk_book(), book(), FakeBook (+15 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "Trade"
Cohesion: 0.09
Nodes (37): datetime, Ends a superseded generation cleanly: every open position is closed at…, retire_generation(), PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult (+29 more)

### Community 48 - "test_ws_ingest_and_smoke.py"
Cohesion: 0.16
Nodes (10): WsCandleIngestor, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format., _raws(), WebSocket -> store glue, and an end-to-end paper-mode smoke test of the real…, `python -m scripts.run_cycle --once` in paper mode against a fake exchange:…, test_paper_mode_worker_smoke_run() (+2 more)

### Community 49 - "test_council_integration.py"
Cohesion: 0.19
Nodes (16): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, test_not_run_means_approved_only_when_the_council_was_not_required() (+8 more)

### Community 50 - "sqlalchemy"
Cohesion: 0.03
Nodes (52): do_run_migrations(), run_migrations_online(), _decision(), history(), latest(), AsyncSession, get, exit_analytics() (+44 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.12
Nodes (13): 10. Market-data dependency direction, BookProvider, Protocol, HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context. (+5 more)

### Community 52 - "regime_validation_engine.py"
Cohesion: 0.20
Nodes (18): _all_regimes(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID, Per-regime performance breakdown and robustness classification. Every promising… (+10 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.11
Nodes (36): PaperExecutionAdapter, Random, Paper execution adapter v2 (spec sections 5/19; phase 7). A research-grade fill…, OrderStatus, _orders(), _pos(), Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close…, Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the… (+28 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (36): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+28 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.16
Nodes (17): estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, _samples(), ShadowConfig, TradeEvidence (+9 more)

### Community 57 - "test_worker_fencing.py"
Cohesion: 0.12
Nodes (27): LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _close_keepers(), _counts(), _keeper(), paper(), fixture (+19 more)

### Community 58 - "test_sqlite_locking.py"
Cohesion: 0.24
Nodes (11): factory(), fixture, SQLite write-lock behaviour on a real WAL file shared by two connections…, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle() (+3 more)

### Community 59 - "OllamaClient"
Cohesion: 0.05
Nodes (39): 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, Improvements achieved, Intentional coupling (do not "fix"), Post-Refactoring Architecture Review (+31 more)

### Community 60 - "below_min_order_notional"
Cohesion: 0.06
Nodes (64): 12. Live/backtest duplication, backtest_risk_check(), Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, approve_against_margin(), below_min_order_notional(), build_sizing_result(), normalize_method() (+56 more)

### Community 61 - "test_analytics_store.py"
Cohesion: 0.07
Nodes (53): _bar_ms(), _components_of(), _is_uuid(), _ms(), AsyncSession, Bar, datetime, Rebuild the matrix for `computation_version` (derived aggregate: DELETE the… (+45 more)

### Community 62 - "Bias"
Cohesion: 0.06
Nodes (53): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), apply_judge(), compute_consensus() (+45 more)

### Community 63 - "Local Migration"
Cohesion: 0.18
Nodes (10): Future Production Migration, Local Migration, PostgreSQL Migration Guide, Prerequisites, Step 2 — Apply the schema, Step 3 — Migrate the data, Step 4 — Verify, Step 5 — Run the app on Postgres (+2 more)

### Community 64 - "test_postgres_concurrency.py"
Cohesion: 0.28
Nodes (7): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, REAL PostgreSQL behaviour (spec phase 25): true multi-connection races, the…, asyncpg allows 32767 bind parameters per statement; ~17 per candle row made…, test_5000_candles_upsert_on_asyncpg_and_large_gap_recovery(), test_a_lock_wait_times_out_instead_of_blocking_forever(), test_session_timeouts_are_applied_to_every_pooled_connection()

### Community 65 - "test_as_of_boundaries.py"
Cohesion: 0.10
Nodes (44): entry_condition_similarity(), feature_similarity(), Jaccard similarity over each DNA's (indicator name, sorted params) set plus its…, Jaccard similarity over (feature, operator, value) entry conditions, averaged…, apply_diversity_pressure(), compute_generation_correlation_report(), GenerationCorrelationReport, persist_generation_correlation() (+36 more)

### Community 66 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 67 - "prune_decisions.py"
Cohesion: 0.29
Nodes (12): count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,…, Deletes no-op rows older than `cutoff` in batches. Returns rows deleted. (+4 more)

### Community 68 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (19): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+11 more)

### Community 69 - "get_adversarial_report_history"
Cohesion: 0.60
Nodes (5): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID

### Community 70 - "test_funding.py"
Cohesion: 0.44
Nodes (9): _dna(), _hold_across(), Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long(), test_no_funding_rows_means_no_charge_not_an_invented_one(), test_short_receives_positive_funding() (+1 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.14
Nodes (13): 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Experiment Guide, From the CLI (+5 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "Settings"
Cohesion: 0.07
Nodes (27): 3. Current cross-community bridge nodes, What should NOT be refactored, field_validator, model_validator, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real… (+19 more)

### Community 74 - "performance_metrics_service.py"
Cohesion: 0.48
Nodes (6): compute_agent_performance_metric(), compute_and_persist_agent_performance_metric(), AsyncSession, datetime, Persists PerformanceMetric snapshots from real Trade/Agent state. Regime-…, Builds (does not persist) a PerformanceMetric snapshot for `agent` from its…

### Community 75 - "cycle.py"
Cohesion: 0.11
Nodes (27): AsyncSession, Single string (or None) the risk engine uses to block NEW entries., trading_halt_reason(), _last_done_open_time(), make_cycle_id(), pending_open_times(), process_candle(), AsyncSession (+19 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.12
Nodes (22): _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess, fixture (+14 more)

### Community 77 - "PositionSizing"
Cohesion: 0.20
Nodes (19): PositionSizing, test_position_sizing_max_notional_caps_the_order(), _decisions(), _orders(), Minimum order notional is enforced at DECISION time, not discovered a bar later…, test_entry_at_the_minimum_still_creates_a_pending_order(), test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason(), test_the_minimum_can_be_disabled_like_at_the_adapter() (+11 more)

### Community 78 - "set_kill_switch"
Cohesion: 0.20
Nodes (11): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+3 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.16
Nodes (12): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+4 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.23
Nodes (13): alembic_autogenerate, alembic_migration, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs() (+5 more)

### Community 81 - "dashboard_service.py"
Cohesion: 0.15
Nodes (26): _agent_age_days(), _agent_group_stats(), get_agent_metrics(), get_champions_analysis(), get_equity_curve(), get_fitness_components(), get_overview(), get_ranking_stability() (+18 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.21
Nodes (11): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_dna_field_is_either_runtime_covered_or_documented_metadata() (+3 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.26
Nodes (11): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+3 more)

### Community 84 - "test_decision_loop_characterization.py"
Cohesion: 0.23
Nodes (13): _build_scenario(), capture_state(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, See module docstring for exactly what is/isn't included and why. (+5 more)

### Community 85 - "get_latest_regime_validation"
Cohesion: 0.60
Nodes (5): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID

### Community 86 - "test_dashboard_api.py"
Cohesion: 0.18
Nodes (14): _backdate_generation(), datetime, Tests for the read-only /api/dashboard/* endpoints and the additive fields…, Real generations accumulate trades over real elapsed time; tests run in…, test_agent_metrics_sorts_and_paginates(), test_champions_analysis_cross_tab(), test_equity_curve_insufficient_data_outside_the_requested_range(), test_equity_curve_tracks_cumulative_pnl_and_drawdown() (+6 more)

### Community 87 - "evaluate_fitness_versions.py"
Cohesion: 0.12
Nodes (27): AgentFacts, The immutable facts of an agent needed at any T (no mutable state)., _bucket_report(), _capture_rate(), _evaluate_version(), _future_for(), _future_profit_factor(), _grid_as_of_points() (+19 more)

### Community 88 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.13
Nodes (17): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., One row of headline aggregates, computed identically against either engine, for… (+9 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.33
Nodes (9): rank_correlation(), Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat(), main(), READ-ONLY side-by-side report of the production fitness and the SHADOW (Phase… (+1 more)

### Community 90 - "StrategyStage"
Cohesion: 0.10
Nodes (59): comparability(), compute_live_stage_metrics(), _max_drawdown(), Computes the same 4 base metrics from actual Trade/Agent history for every…, Peak-to-trough drawdown of the account built from `starting` plus each closed…, Whether the two stages can be used as RELIABLE evidence against each other.…, advance_pipeline_stage(), _build_advisory_criteria() (+51 more)

### Community 91 - "report_agent_evidence.py"
Cohesion: 0.07
Nodes (41): argparse, FitnessForwardPerformance, main(), migrate(), One-off: copy every row from the live Postgres database into a fresh SQLite…, _explanation(), main(), READ-ONLY agent evidence report (Report E): is a high fitness GENUINE? python… (+33 more)

### Community 92 - "test_fitness_edge_cases.py"
Cohesion: 0.18
Nodes (16): capped_profit_factor(), compute_trade_stats(), _max_streaks(), Pure trade-statistics engine feeding PerformanceMetric snapshots.…, gross_win / gross_loss; the no-loss case is capped, and no evidence at all (no…, Longest consecutive-win and consecutive-loss streaks, in trade order. Flat…, TradeStatsResult, inp() (+8 more)

### Community 93 - "24-Hour Data Validation & Next-Phase Execution — Research Report"
Cohesion: 0.12
Nodes (15): 10. FINAL STATUS, 24-Hour Data Validation & Next-Phase Execution — Research Report, 4. 24-HOUR BASELINE, 6. EXIT EXPERIMENT PLAN, 7. POSTGRESQL MIGRATION PLAN, 9. ACCEPTANCE CRITERIA, Backup strategy, Files changed (+7 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (11): cmd_backup(), cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), env_value(), is_running() (+3 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "Side"
Cohesion: 0.07
Nodes (49): stop_price(), take_profit_price(), compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL (+41 more)

### Community 97 - "test_backtesting.py"
Cohesion: 0.20
Nodes (16): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+8 more)

### Community 98 - "config.py"
Cohesion: 0.08
Nodes (37): Centralized application configuration. Every environment-dependent value in the…, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory(), _is_secret_key() (+29 more)

### Community 99 - "test_promotion_evidence.py"
Cohesion: 0.14
Nodes (29): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, _average_agent_fitness(), _candidate_metrics(), evaluate_and_promote() (+21 more)

### Community 100 - "Decision"
Cohesion: 0.11
Nodes (38): _cancel_stale_pending(), _load_funding(), protect_open_positions(), AsyncSession, DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, Protective-only pass for `context`'s bar: funding, stop, take-profit, trailing,…, A pending entry that was not filled on the bar after its signal is CANCELLED -… (+30 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "test_gap_cycle.py"
Cohesion: 0.31
Nodes (10): active_flags(), Returns {flag_name: reason} for every currently-active flag., _crash(), _delete_bar(), _open_positions_at_bar_398(), paper(), fixture, Gap recovery through the REAL cycle path (spec phase 14): gap -> backfill ->… (+2 more)

### Community 104 - "1. Current architecture (as it actually is, not as the graph implies)"
Cohesion: 0.25
Nodes (7): 1. Current architecture (as it actually is, not as the graph implies), 4. Proposed target architecture, 5. Migration phases (revised order — risk-ascending, not the original numbering), 6. Risks, 7. Behavior that must remain unchanged (explicit checklist for every phase), 8. What Phase 0 deliberately does not conclude, Refactor Plan — Phase 0 Analysis

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "run_cycle.py"
Cohesion: 0.06
Nodes (26): asyncio, _escape(), _fmt(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, Thin async client for Hyperliquid's public `info` REST endpoint and websocket…, HyperliquidWebSocket, Any, Hyperliquid WebSocket market-data stream (spec phase 17). Primary real-time… (+18 more)

### Community 108 - "routes/status.py"
Cohesion: 0.08
Nodes (39): _acquire_stream_slot(), _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37). (+31 more)

### Community 109 - "test_fitness_versions.py"
Cohesion: 0.09
Nodes (30): FitnessWeights, Weights are configuration, not code: FITNESS_W_* environment variables., The weights of a recorded snapshot (fitness_scores.weights_used), falling back…, weights_from_recorded(), FitnessVersionSpec, Research-only registry of named fitness formula/timing variants for offline…, Hardcoded to today's production values (fitness_engine.FitnessWeights defaults…, A smooth alternative to the hard clip(-1, 1): tanh never fully flattens two… (+22 more)

### Community 110 - "ExecutionVenue"
Cohesion: 0.10
Nodes (26): ABC, ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+18 more)

### Community 111 - "shadow_summary"
Cohesion: 0.40
Nodes (4): AsyncSession, get, Expected-vs-actual market execution measured by shadow mode., shadow_summary()

### Community 112 - "schemas/reality_gap.py"
Cohesion: 0.60
Nodes (4): BaseModel, RealityGapChainReportOut, RealityGapReportOut, StageTransitionGapOut

### Community 113 - "helpers_shadow.py"
Cohesion: 0.17
Nodes (13): ShadowAgentInput, current_fitness(), _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, (production compute_fitness, max drawdown) fed the way fitness_service feeds… (+5 more)

### Community 114 - "test_fitness_forward.py"
Cohesion: 0.24
Nodes (17): forward_window(), The honest (T, T+h] window: truncated at the earliest real boundary., facts(), point(), Phase 3 tests: look-ahead protection, historical reconstruction, censoring,…, test_dead_agent_reconstruction_endstops_at_death(), test_forward_window_uses_only_trades_after_t(), test_full_coverage_when_no_boundary_hits() (+9 more)

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "schemas/adversarial.py"
Cohesion: 0.67
Nodes (3): AdversarialTestReportOut, BaseModel, ScenarioBreakdownOut

### Community 118 - "fitness_forward.py"
Cohesion: 0.18
Nodes (19): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), _overlaps_oos_window(), datetime (+11 more)

### Community 119 - "StrategyVersion"
Cohesion: 0.10
Nodes (45): create_generation(), Creates a new Generation row and one Agent per strategy_version_id, each…, _preserve_family_distribution(), Biases fresh-DNA injection toward minority families apply_diversity_pressure…, StrategyFamily, A strategy lineage, e.g. STRAT-MOM-001. Immutable identity; the DNA itself…, Strategy, StrategyVersion (+37 more)

### Community 121 - "MarketRegime"
Cohesion: 0.22
Nodes (19): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, MarketRegime, _bar_regimes(), DataFrame, parametrize, Regime detector v2 (correctness fixes only; no new thresholds). v1 defects,…, (regime, break_of_structure feature) for each of the last `last` bars, each… (+11 more)

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "test_reality_gap_engine.py"
Cohesion: 0.12
Nodes (26): 9. Database dependency direction, get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…, compute_full_reality_gap_chain() (+18 more)

### Community 135 - "test_margin_liquidation.py"
Cohesion: 0.48
Nodes (6): _levered_dna(), Margin & liquidation (spec phase 9): explicit margin model; leverage is a real…, test_dead_agents_are_never_processed_again_or_revived(), test_leverage_multiplies_notional_but_margin_stays_within_the_cap(), test_liquidation_closes_the_position_charges_penalty_and_can_kill_the_agent(), test_notional_never_exceeds_available_margin_times_leverage()

### Community 137 - "get_regime_performance"
Cohesion: 0.25
Nodes (8): get_regime_performance(), Breaks down closed-trade performance by the market regime that was active when…, load_regime_lookup(), AsyncSession, Returns (open_times, regimes) sorted ascending by candle_open_time — pass both…, asyncio, Regression guard for the shared regime_lookup.py extraction: the per-strategy…, test_compute_regime_breakdown_live_agrees_with_the_by_regime_route()

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 141 - "correlation_service.py"
Cohesion: 0.06
Nodes (55): _most_correlated_pair(), The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _condition_set(), exit_condition_similarity(), feature_set(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the… (+47 more)

### Community 143 - "tradability.py"
Cohesion: 0.24
Nodes (11): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, Which agents can be TESTED at their capital (Option D of the min-notional…, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids() (+3 more)

### Community 144 - "test_regime_validation_engine.py"
Cohesion: 0.20
Nodes (17): classify_robustness(), Classifies a strategy's cross-regime behavior. Never used to reject a strategy…, cfg(), fixture, _bt_trade(), UUID, RegimeValidationEngine: per-regime breakdown from backtest and live trade…, _stats() (+9 more)

### Community 146 - "test_no_live_orders.py"
Cohesion: 0.10
Nodes (17): code_only(), fixture, FINAL SAFETY PROOF (spec phase 32): TRADING_MODE=paper cannot send a real…, Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, recorded_requests(), _sources(), test_even_with_every_gate_open_the_live_adapter_cannot_place_an_order() (+9 more)

### Community 155 - "helpers_agents.py"
Cohesion: 0.10
Nodes (38): CooldownConfig, StopLossConfig, TakeProfitConfig, TrailingStopConfig, _base_exits(), Builders for decision-loop level tests (contexts, DNA, agents, cycle runner)., _dna(), Cooldown and max-trades-per-day are hard runtime gates (spec phase 11). (+30 more)

### Community 159 - "ImmutableRecordError"
Cohesion: 0.47
Nodes (6): _dna_is_immutable(), ImmutableRecordError, listens_for, RuntimeError, _snapshot_is_undeletable(), _snapshot_is_write_once()

### Community 160 - "test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison"
Cohesion: 0.50
Nodes (4): _crash_bar(), _positions_at(), test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison(), test_skipped_catchup_bars_still_protect_open_positions()

### Community 161 - "constraints.py"
Cohesion: 0.50
Nodes (3): attach_constraints(), Database-level invariants (spec phase 26). Python validation alone is not…, Idempotently attaches every CHECK and the extra partial unique indexes to…

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1266 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `enums.py`, `test_live_safety.py`, `test_margin_liquidation.py`, `Agent`, `MarketCandle`, `test_evolution_pipeline.py`, `run_backtest`, `test_stops_trailing.py`, `tradability.py`, `RiskDecision`, `make_agents`, `test_regime_validation_engine.py`, `test_metrics_emission.py`, `test_frozen_oos_epoch.py`, `test_no_live_orders.py`, `test_worker_cycle.py`, `lease.py`, `test_council_failclosed.py`, `AgentStatus`, `helpers_agents.py`, `backtesting/engine.py`, `test_ollama_failure_modes.py`, `lockbox.py`, `ExecutionRequest`, `test_promotion_service.py`, `pipeline.py`, `dataset.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `test_paper_cycles_with_a_council_only_ever_touch_read_endpoints`, `test_shadow_mode.py`, `Trade`, `test_ws_ingest_and_smoke.py`, `test_council_integration.py`, `sqlalchemy`, `HyperliquidClient`, `PaperExecutionAdapter`, `test_worker_fencing.py`, `OllamaClient`, `below_min_order_notional`, `Bias`, `test_postgres_concurrency.py`, `prune_decisions.py`, `test_council_deadline.py`, `test_funding.py`, `Settings`, `cycle.py`, `PositionSizing`, `set_kill_switch`, `dashboard_service.py`, `test_dashboard_api.py`, `migrate_sqlite_to_postgres.py`, `StrategyStage`, `report_agent_evidence.py`, `Side`, `config.py`, `test_promotion_evidence.py`, `Decision`, `test_gap_cycle.py`, `1. Current architecture (as it actually is, not as the graph implies)`, `run_cycle.py`, `routes/status.py`, `test_fitness_versions.py`, `ExecutionVenue`, `fitness_forward.py`, `StrategyVersion`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Why does `OllamaClient` connect `OllamaClient` to `ExecutionRequest`, `test_council_deadline.py`, `test_paper_cycles_with_a_council_only_ever_touch_read_endpoints`, `Settings`, `Agent`, `cycle.py`, `run_cycle.py`, `1. Current architecture (as it actually is, not as the graph implies)`, `test_metrics_emission.py`, `test_ollama_schema_normalization.py`, `test_no_live_orders.py`, `test_worker_cycle.py`, `Bias`, `test_council_failclosed.py`, `MarketContext`, `below_min_order_notional`, `test_ollama_failure_modes.py`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `FakeHyperliquid` connect `MarketCandle` to `test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison`, `test_postgres_concurrency.py`, `test_gap_cycle.py`, `test_paper_cycles_with_a_council_only_ever_touch_read_endpoints`, `test_ws_ingest_and_smoke.py`, `make_agents`, `test_metrics_emission.py`, `test_ollama_schema_normalization.py`, `test_no_live_orders.py`, `test_worker_cycle.py`, `test_council_failclosed.py`, `test_worker_fencing.py`, `helpers_agents.py`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 104 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 104 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._