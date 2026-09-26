# Graph Report - reserch_model  (2026-09-26)

## Corpus Check
- 316 files · ~211,367 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 3, .service 3, .ini 2)

## Summary
- 3870 nodes · 14538 edges · 150 communities (124 shown, 26 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2044 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `498ed498`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- PaperExecutionAdapter
- Base
- StrategyStage
- Agent
- config.py
- get_settings
- Settings
- routes/status.py
- test_ws_client.py
- decision_loop.py
- indicators.py
- FakeHyperliquid
- shadow_adapter.py
- run_backtest
- Side
- RiskDecision
- StrategyVersion
- compute_features
- test_worker_fencing.py
- test_ollama_schema_normalization.py
- test_champion_challenger_service.py
- test_council_failclosed.py
- test_metrics_emission.py
- test_postgres_concurrency.py
- Bias
- MarketContext
- RuleSet
- AgentStatus
- StrategyDNA
- backtesting/engine.py
- make_client
- test_strategy_regime_matrix.py
- tradability.py
- test_shadow_fitness_synthetic.py
- run_and_persist_adversarial_suite
- test_reality_gap_engine.py
- pipeline.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- OllamaError
- compute_fitness
- AIClientPort
- test_correlation.py
- test_shadow_mode.py
- families.py
- MarketDataService
- test_oos_lockbox.py
- cycle.py
- typing
- HyperliquidClient
- test_regime_validation_engine.py
- OrderStatus
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- trades.py
- test_stage_metrics.py
- test_council_deadline.py
- below_min_order_notional
- analytics_store.py
- shadow_summary
- OllamaClient
- test_ollama_client.py
- test_lifecycle_ports.py
- export.py
- Decision
- test_strategy_dna.py
- Trade
- make_dna
- test_stops_trailing.py
- What You Must Do When Invoked
- registry.py
- normalization.py
- test_worker_scheduler.py
- test_postgres.py
- pytest
- test_api_endpoints.py
- test_analytics_migration.py
- test_migrations.py
- fitness_service.py
- pathlib
- secret_scan.py
- test_decision_loop_characterization.py
- enums.py
- StrategyFamily
- _Sheet
- conftest.py
- shadow_rows_for_generation
- test_council_integration.py
- report_trade_quality.py
- test_promotion_evidence.py
- 24-Hour Data Validation & Next-Phase Execution — Research Report
- run.sh
- test_dashboard_js.py
- test_funding.py
- 7. POSTGRESQL MIGRATION PLAN
- AbuseGuard
- strategy_dna.py
- helpers_shadow.py
- WsCandle
- export_report
- test_backtesting.py
- strategy.py
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- Refactor Progress
- ImmutableAnalyticsRecordError
- routes/champion_challenger.py
- test_live_backtest_parity.py
- constraints.py
- list_challengers
- test_db_location.py
- graphify reference: extra exports and benchmark
- migrate_sqlite_to_postgres.py
- get_reality_gap_chain
- OllamaAuthError
- graphify reference: query, path, explain
- test_ollama_failure_modes.py
- purge_secrets_from_history.sh
- env.py
- latest
- migrate_postgres_to_sqlite.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- TakeoverEngine
- graphify reference: GitHub clone and cross-repo merge
- _fast
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 236 edges
2. `PaperExecutionAdapter` - 189 edges
3. `Agent` - 160 edges
4. `make_agents()` - 154 edges
5. `StrategyDNA` - 148 edges
6. `make_dna()` - 147 edges
7. `Side` - 138 edges
8. `make_context()` - 132 edges
9. `StrategyVersion` - 130 edges
10. `StrategyStage` - 124 edges

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

## Communities (150 total, 26 thin omitted)

### Community 0 - "PaperExecutionAdapter"
Cohesion: 0.09
Nodes (73): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), Residual of the cash identity (0.0 when the books balance). balance == starting…, reconcile(), PaperExecutionAdapter, cycle() (+65 more)

### Community 1 - "Base"
Cohesion: 0.10
Nodes (50): Base, Read/write helpers for durable system flags (kill switch, data-gap halt)., FitnessForwardPerformance, Derived analytical tables (the analytics foundation). These tables store ONLY…, StrategyRegimeMatrix, datetime, Shared mixins for ORM models., A timezone-aware DateTime that stays timezone-aware on SQLite too. Postgres's… (+42 more)

### Community 2 - "StrategyStage"
Cohesion: 0.14
Nodes (38): latest_stage_metrics(), _average_agent_fitness(), _candidate_metrics(), evaluate_and_promote(), AsyncSession, UUID, Assembles ALL promotion evidence for a version. The final OOS score comes from…, Evaluates whether `strategy_version_id`'s metrics at `stage` justify promoting… (+30 more)

### Community 3 - "Agent"
Cohesion: 0.08
Nodes (38): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), list_agents(), AsyncSession, get (+30 more)

### Community 4 - "config.py"
Cohesion: 0.06
Nodes (50): 9. Database dependency direction, argparse, asyncio, Centralized application configuration. Every environment-dependent value in the…, AsyncSession, Context manager for a transactional unit of work outside a request. Commits on…, SQLite writer processes (worker, research scheduler): take the write lock at…, session_scope() (+42 more)

### Community 5 - "get_settings"
Cohesion: 0.04
Nodes (47): Weights are configuration, not code: FITNESS_W_* environment variables., The weights of a recorded snapshot (fitness_scores.weights_used), falling back…, weights_from_recorded(), get_settings(), AsyncSession, Single string (or None) the risk engine uses to block NEW entries., trading_halt_reason(), create_app() (+39 more)

### Community 6 - "Settings"
Cohesion: 0.06
Nodes (53): ABC, 6. ExecutionEngine boundary, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Enum, field_validator, str, All gates required by spec section 40 before ANY live order. This does not… (+45 more)

### Community 7 - "routes/status.py"
Cohesion: 0.08
Nodes (39): _acquire_stream_slot(), _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37). (+31 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.06
Nodes (50): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, test_ws_reconnects_are_counted(), factory(), fixture, Documents the failure mode seen on the worker (API keeps this default). (+42 more)

### Community 9 - "decision_loop.py"
Cohesion: 0.07
Nodes (66): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+58 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (65): jitter(), mutate(), _mutate_indicator_period(), _mutate_ruleset_thresholds(), Random, DNA mutation (spec section 25). Produces a new, independently-valid StrategyDNA…, Changes one declared indicator's period AND rewrites every rule that referenced…, _atr() (+57 more)

### Community 11 - "FakeHyperliquid"
Cohesion: 0.09
Nodes (55): active_flags(), Returns {flag_name: reason} for every currently-active flag., MarketCandle, clock_after_bar(), FakeHyperliquid, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format. (+47 more)

### Community 12 - "shadow_adapter.py"
Cohesion: 0.13
Nodes (17): Deterministic settlement at the modelled price when the engine keeps failing to…, _synthetic_exit_fill(), close(), slip(), ExecutionResult, fee_rate_for(), The ONE cost model shared by the paper adapter, shadow estimates and the…, Adverse slippage in bps. Resting take-profit limit orders pay none; stops and… (+9 more)

### Community 13 - "run_backtest"
Cohesion: 0.10
Nodes (50): DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward(), _simulate(), validate() (+42 more)

### Community 14 - "Side"
Cohesion: 0.08
Nodes (45): stop_price(), take_profit_price(), compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL (+37 more)

### Community 15 - "RiskDecision"
Cohesion: 0.11
Nodes (46): backtest_risk_check(), Routes backtest/adversarial position sizing through the real…, Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every… (+38 more)

### Community 16 - "StrategyVersion"
Cohesion: 0.11
Nodes (38): BreedingResult, check_candidate_schema(), NoValidCandidatesError, Random, RuntimeError, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the…, Selects survivors from `generation_number`, breeds children via… (+30 more)

### Community 17 - "compute_features"
Cohesion: 0.07
Nodes (57): _atr(), _bollinger(), compute_features(), detect_regime(), _ema(), _macd(), DataFrame, Series (+49 more)

### Community 18 - "test_worker_fencing.py"
Cohesion: 0.11
Nodes (29): LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _close_keepers(), _counts(), _keeper(), paper(), fixture (+21 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.11
Nodes (49): CouncilAnalysis, One analyst's structured response feeding into a CouncilDecision., ValueError, The response cannot be safely normalised. `reason` is a short machine-readable…, ResponseNormalizationError, test_council_endpoints_expose_analysts_failures_latency_and_judge(), analyst_server(), client_for() (+41 more)

### Community 20 - "test_champion_challenger_service.py"
Cohesion: 0.16
Nodes (36): advance_pipeline_stage(), _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report(), AsyncSession, UUID, Tightens `min_fitness_improvement` for FRAGILE/UNSTABLE regime classification —… (+28 more)

### Community 21 - "test_council_failclosed.py"
Cohesion: 0.10
Nodes (45): AsyncSession, run_council_cycle(), CouncilDecision, One consensus outcome for one candle — shared by all agents., council_on(), fixture, Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, _run() (+37 more)

### Community 22 - "test_metrics_emission.py"
Cohesion: 0.07
Nodes (39): counter_value(), _escape(), _fmt(), inc(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint… (+31 more)

### Community 23 - "test_postgres_concurrency.py"
Cohesion: 0.08
Nodes (35): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id(), AsyncSession (+27 more)

### Community 24 - "Bias"
Cohesion: 0.11
Nodes (36): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), apply_judge(), compute_consensus() (+28 more)

### Community 25 - "MarketContext"
Cohesion: 0.15
Nodes (28): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, minimal_context(), A NEUTRAL-feature context for one CONFIRMED stored candle…, MarketContext, MomentumFeatures, PriceActionFeatures, BaseModel (+20 more)

### Community 26 - "RuleSet"
Cohesion: 0.11
Nodes (43): Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet, _all_rulesets(), available_feature_keys() (+35 more)

### Community 27 - "AgentStatus"
Cohesion: 0.10
Nodes (45): AgentAlreadyDeadError, bankruptcy_threshold(), create_generation(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession, RuntimeError (+37 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.23
Nodes (28): MarketRegime, IndicatorConfig, field_validator, model_validator, Combinations the schema ACCEPTS but that silently do nothing (or something…, One named indicator instance the strategy depends on, e.g. {"name": "rsi",…, StrategyDNA, _base_risk() (+20 more)

### Community 29 - "backtesting/engine.py"
Cohesion: 0.10
Nodes (31): BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, Adds any indicator series not yet present (idempotent; a spec whose series all… (+23 more)

### Community 30 - "make_client"
Cohesion: 0.10
Nodes (23): call(), make_client(), parametrize, test_200_with_malformed_envelope_is_a_typed_response_error(), test_200_with_non_json_body_is_a_typed_response_error_not_a_crash(), test_400_is_not_retried_and_is_a_typed_error(), test_401_single_key_is_not_retried_and_key_is_marked_unhealthy(), h() (+15 more)

### Community 31 - "test_strategy_regime_matrix.py"
Cohesion: 0.08
Nodes (36): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+28 more)

### Community 32 - "tradability.py"
Cohesion: 0.24
Nodes (11): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, Which agents can be TESTED at their capital (Option D of the min-notional…, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids() (+3 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.12
Nodes (30): champion_evidence_ok(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, make_population(), world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions() (+22 more)

### Community 34 - "run_and_persist_adversarial_suite"
Cohesion: 0.25
Nodes (7): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, AsyncSession, DataFrame, UUID, Loads `strategy_version_id`'s DNA, runs the full adversarial suite (risk-gated…, run_and_persist_adversarial_suite()

### Community 35 - "test_reality_gap_engine.py"
Cohesion: 0.09
Nodes (44): compute_full_reality_gap_chain(), persist_reality_gap_report(), AsyncSession, UUID, Full-lifecycle reality-gap report: Backtest -> Walk-Forward -> Out-of-Sample ->…, Compares every consecutive pair of stages this strategy version has actually…, Insert-only — caller commits., RealityGapChainReport (+36 more)

### Community 36 - "pipeline.py"
Cohesion: 0.14
Nodes (31): derive_seed(), A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id,…, Experiment, _adversarial(), evaluate_gates(), AsyncSession, datetime, Scheduled research/evolution pipeline (spec phases 22-30, 32). Population ->… (+23 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.08
Nodes (51): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, ResearchEpoch, _build_epoch() (+43 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.20
Nodes (20): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), _agent(), _pop() (+12 more)

### Community 39 - "analyze_trade"
Cohesion: 0.17
Nodes (28): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+20 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.06
Nodes (58): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+50 more)

### Community 41 - "OllamaError"
Cohesion: 0.16
Nodes (18): _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError, OllamaServerError, OllamaTimeoutError (+10 more)

### Community 42 - "compute_fitness"
Cohesion: 0.05
Nodes (77): _clip(), compute_fitness(), FitnessInputs, FitnessResult, FitnessWeights, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,… (+69 more)

### Community 43 - "AIClientPort"
Cohesion: 0.10
Nodes (21): AICallStats, AIClientPort, Protocol, T, The council's dependency contract on an AI client (Phase 1 dependency-boundary…, The subset of OllamaCallStats the council actually reads., Everything the council needs from an AI client. Signature matches…, OllamaCallStats (+13 more)

### Community 44 - "test_correlation.py"
Cohesion: 0.08
Nodes (52): _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the… (+44 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.13
Nodes (24): L2Book, parse_book(), Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter, walk_book(), book(), FakeBook (+16 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "MarketDataService"
Cohesion: 0.09
Nodes (20): _as_float(), _chunks(), _dialect_insert(), GapReport, MarketDataService, AsyncSession, DataFrame, MarketDataService — the single shared market-data pipeline (spec 6). 500 agents… (+12 more)

### Community 48 - "test_oos_lockbox.py"
Cohesion: 0.11
Nodes (34): OosEvaluation, compute_oos_score(), evaluate_oos_once(), OosAlreadyConsumedError, OosLineageExhaustedError, AsyncSession, DataFrame, RuntimeError (+26 more)

### Community 49 - "cycle.py"
Cohesion: 0.09
Nodes (41): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One immutable processing attempt for a confirmed market candle., WorkerCycle, _ensure_features_persisted(), _last_done_open_time(), make_cycle_id() (+33 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.14
Nodes (10): HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context., Wraps Hyperliquid's `/info` endpoint. Live order placement (the exchange-…, Returns raw Hyperliquid candle dicts: {"t": open_ms, "T": close_ms,…, Returns Hyperliquid's published funding settlements: [{"coin", "fundingRate",… (+2 more)

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.10
Nodes (43): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID, _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest() (+35 more)

### Community 53 - "OrderStatus"
Cohesion: 0.11
Nodes (32): ExecutionStressResult, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter, OrderStatus, asyncio, Execution-quality stress testing: StressedExecutionAdapter injects partial… (+24 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (37): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+29 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.16
Nodes (17): estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, _samples(), ShadowConfig, TradeEvidence (+9 more)

### Community 57 - "trades.py"
Cohesion: 0.12
Nodes (28): get_regime_performance(), get_side_performance(), get_strategy_performance(), list_trades(), AsyncSession, get, Breaks down closed-trade performance by strategy family. A trade's strategy is…, Breaks down closed-trade performance by the market regime that was active when… (+20 more)

### Community 58 - "test_stage_metrics.py"
Cohesion: 0.12
Nodes (24): BacktestTrade, persist_backtest_metrics(), persist_walk_forward_metrics(), UUID, Builds a StageMetrics row from a single backtest run (BACKTEST or OUT_OF_SAMPLE…, Builds a StageMetrics row (WALK_FORWARD stage) from a walk-forward report,…, Fraction of windows that were profitable — a simple, auditable stand-in for…, WalkForwardReport (+16 more)

### Community 59 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (19): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+11 more)

### Community 60 - "below_min_order_notional"
Cohesion: 0.06
Nodes (60): 12. Live/backtest duplication, approve_against_margin(), below_min_order_notional(), build_sizing_result(), normalize_method(), Position sizing (spec phase 6): pure, deterministic, unit-tested. Supported DNA…, Fractional distance from entry to the protective stop (matches the stop…, What the DNA wants, before risk clamps. Never negative. (+52 more)

### Community 61 - "analytics_store.py"
Cohesion: 0.11
Nodes (36): _bar_ms(), _components_of(), _is_uuid(), _ms(), AsyncSession, Bar, datetime, DB I/O for the analytics foundation. The ONLY module that writes, and it writes… (+28 more)

### Community 62 - "shadow_summary"
Cohesion: 0.22
Nodes (7): AsyncSession, get, Expected-vs-actual market execution measured by shadow mode., shadow_summary(), test_check_constraints_are_enforced_by_postgres_itself(), order(), pend()

### Community 63 - "OllamaClient"
Cohesion: 0.05
Nodes (38): 10. Market-data dependency direction, 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, Improvements achieved, Intentional coupling (do not "fix") (+30 more)

### Community 64 - "test_ollama_client.py"
Cohesion: 0.19
Nodes (14): _Echo, _mock_transport(), asyncio, BaseModel, Ollama client failure handling: timeout, 429, malformed response (spec 45)., Root cause of the reported intermittent analyst 401s: with multiple…, test_401_on_every_key_exhausts_retries_and_raises_auth_error(), test_401_on_one_key_is_retried_and_recovers_on_the_next_key() (+6 more)

### Community 65 - "test_lifecycle_ports.py"
Cohesion: 0.12
Nodes (23): datetime, Ends a superseded generation cleanly: every open position is closed at…, retire_generation(), PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult (+15 more)

### Community 66 - "export.py"
Cohesion: 0.11
Nodes (27): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+19 more)

### Community 67 - "Decision"
Cohesion: 0.12
Nodes (31): set_flag(), Decision, count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime (+23 more)

### Community 68 - "test_strategy_dna.py"
Cohesion: 0.08
Nodes (35): _most_correlated_pair(), The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _make_candidates(), _blend(), crossover(), Random, DNA crossover (spec section 25): combine two successful parents' DNA into one…, dna_distance() (+27 more)

### Community 69 - "Trade"
Cohesion: 0.15
Nodes (32): DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, run_decision_cycle(), Position, A closed round-trip (or partial close) — the unit fitness/metrics are computed…, Trade, _context(), _make_agent() (+24 more)

### Community 70 - "make_dna"
Cohesion: 0.15
Nodes (34): CooldownConfig, BaseModel, StopLossConfig, TakeProfitConfig, TrailingStopConfig, _base_exits(), make_dna(), Builders for decision-loop level tests (contexts, DNA, agents, cycle runner). (+26 more)

### Community 71 - "test_stops_trailing.py"
Cohesion: 0.21
Nodes (26): advance_extremes(), Bar, evaluate_bar(), PositionLevels, ProtectiveTrigger, Open-position management on every confirmed bar (spec phases 8-11). Order of…, Peak/trough AFTER this bar, and whether trailing is now armed., trailing_is_active() (+18 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "registry.py"
Cohesion: 0.15
Nodes (21): code_version(), new_experiment_id(), parameter_hash(), AsyncSession, UUID, Experiment registry (spec phase 23): every research run is a reproducible,…, Git commit (short) of the running code; `CODE_VERSION` env overrides…, Alembic head revision shipped with this code. (+13 more)

### Community 74 - "normalization.py"
Cohesion: 0.21
Nodes (14): BoundedResponse, _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any (+6 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.15
Nodes (18): _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess, fixture (+10 more)

### Community 77 - "pytest"
Cohesion: 0.18
Nodes (22): AsyncSession, Ranks every agent in `generation_number` by `Agent.fitness` (falling back to…, select_survivors(), PositionSizing, _decisions(), _orders(), Minimum order notional is enforced at DECISION time, not discovered a bar later…, test_entry_at_the_minimum_still_creates_a_pending_order() (+14 more)

### Community 78 - "test_api_endpoints.py"
Cohesion: 0.17
Nodes (13): publish_status(), candle(), Dashboard/API surface (spec phases 35-37): confirmed-candle market view,…, test_evolution_endpoints(), test_export_report_is_one_xlsx_with_every_dashboard_section(), test_metrics_endpoint_is_operator_only_and_exposes_the_required_series(), test_ollama_health_endpoint_needs_operator_and_never_leaks_key_values(), test_population_and_agent_detail_endpoints() (+5 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.15
Nodes (13): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+5 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.21
Nodes (14): alembic_autogenerate, alembic_migration, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs() (+6 more)

### Community 81 - "fitness_service.py"
Cohesion: 0.12
Nodes (31): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+23 more)

### Community 82 - "pathlib"
Cohesion: 0.21
Nodes (11): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_nested_dna_field_is_covered_by_a_named_behaviour_test() (+3 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.33
Nodes (9): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+1 more)

### Community 84 - "test_decision_loop_characterization.py"
Cohesion: 0.20
Nodes (15): _build_scenario(), capture_state(), _invalid_dna_agent(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the… (+7 more)

### Community 85 - "enums.py"
Cohesion: 0.12
Nodes (21): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+13 more)

### Community 86 - "StrategyFamily"
Cohesion: 0.17
Nodes (21): 3. Current cross-community bridge nodes, _preserve_family_distribution(), Biases fresh-DNA injection toward minority families apply_diversity_pressure…, StrategyFamily, test_default_bind_is_loopback(), _dna(), asyncio, Generation-breeding orchestrator: survivor selection and the population-… (+13 more)

### Community 87 - "_Sheet"
Cohesion: 0.16
Nodes (12): _build(), _cell_value(), _fetch(), _flatten(), _plain(), Any, AsyncSession, datetime (+4 more)

### Community 88 - "conftest.py"
Cohesion: 0.23
Nodes (9): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+1 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.33
Nodes (9): rank_correlation(), Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat(), main(), READ-ONLY side-by-side report of the production fitness and the SHADOW (Phase… (+1 more)

### Community 90 - "test_council_integration.py"
Cohesion: 0.17
Nodes (18): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, test_not_run_means_approved_only_when_the_council_was_not_required() (+10 more)

### Community 91 - "report_trade_quality.py"
Cohesion: 0.11
Nodes (26): cohort_stats(), _flat(), main(), _pearson(), _ranks(), READ-ONLY fitness -> future-performance report (Reports F and H). python -m…, Average ranks (ties share the mean rank) — deterministic., One cohort (as_of, horizon): the study's statistics, over flattened rows. (+18 more)

### Community 92 - "test_promotion_evidence.py"
Cohesion: 0.22
Nodes (17): What should NOT be refactored, CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, test_criteria_come_from_settings(), good() (+9 more)

### Community 93 - "24-Hour Data Validation & Next-Phase Execution — Research Report"
Cohesion: 0.13
Nodes (14): 10. FINAL STATUS, 24-Hour Data Validation & Next-Phase Execution — Research Report, 4. 24-HOUR BASELINE, 5. EXIT ANALYSIS, 6. EXIT EXPERIMENT PLAN, 9. ACCEPTANCE CRITERIA, Files changed, Is the system ready for the multi-week 500-agent run? (+6 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (9): cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), is_running(), run.sh script, stop_one() (+1 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "test_funding.py"
Cohesion: 0.33
Nodes (11): _dna(), _hold_across(), _no_sleep(), fixture, Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 97 - "7. POSTGRESQL MIGRATION PLAN"
Cohesion: 0.18
Nodes (8): model_validator, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, Three processes share the database. If their pools alone could exceed the…, 7. POSTGRESQL MIGRATION PLAN, Backup strategy, Concurrency considerations, Rollback strategy

### Community 98 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 99 - "strategy_dna.py"
Cohesion: 0.17
Nodes (14): ComparisonOperator, Enum, str, Strategy DNA schema (spec section 10). This is the contract between the…, What Ollama (or the mutation/crossover engine) must produce for a new candidate…, StrategyCandidate, asyncio, DataFrame (+6 more)

### Community 100 - "helpers_shadow.py"
Cohesion: 0.16
Nodes (14): ShadowAgentInput, current_fitness(), _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, (production compute_fitness, max drawdown) fed the way fitness_service feeds… (+6 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "export_report"
Cohesion: 0.20
Nodes (15): events(), experiments(), generations(), AsyncSession, get, summary(), export_report(), get (+7 more)

### Community 103 - "test_backtesting.py"
Cohesion: 0.18
Nodes (18): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+10 more)

### Community 104 - "strategy.py"
Cohesion: 0.14
Nodes (19): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, Wires app/backtesting/adversarial.py's run_adversarial_suite (previously…, ChampionChallengerEngine: walks a StrategyVersion through the Candidate ->…, Wires evolution/champion.py's promotion-decision logic (previously uncalled) to… (+11 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "Refactor Progress"
Cohesion: 0.20
Nodes (9): Submits an order and returns its fill result. Implementations MUST be…, 2. PositionCloseSettler review, 3. Dependency-direction map, 4-5. Test results, Full test suite (both phases combined), Phase 3 — Boundary verification and hardening (no `decision_loop.py`), Phase 4 — proposed plan for `decision_loop.py` (NOT implemented; plan only, pending approval), Refactor Progress (+1 more)

### Community 108 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 109 - "routes/champion_challenger.py"
Cohesion: 0.15
Nodes (15): AdversarialTestReportOut, BaseModel, ScenarioBreakdownOut, ChallengerEvaluationOut, ChampionSummaryOut, EvolutionEventOut, BaseModel, BaseModel (+7 more)

### Community 110 - "test_live_backtest_parity.py"
Cohesion: 0.29
Nodes (9): _frame(), _funding(), DataFrame, parametrize, LIVE (paper, through the real worker cycle) vs BACKTEST parity (spec phases 5,…, Guard against a vacuous parity suite: across the scenarios stops, signal exits…, _run_live(), test_parity_scenarios_exercise_more_than_one_exit_reason() (+1 more)

### Community 111 - "constraints.py"
Cohesion: 0.50
Nodes (3): attach_constraints(), Database-level invariants (spec phase 26). Python validation alone is not…, Idempotently attaches every CHECK and the extra partial unique indexes to…

### Community 112 - "list_challengers"
Cohesion: 0.31
Nodes (9): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+1 more)

### Community 113 - "test_db_location.py"
Cohesion: 0.31
Nodes (8): Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch…, test_absolute_memory_and_other_urls_are_untouched(), test_defaults_point_at_the_single_data_folder(), test_parent_folder_is_created(), test_relative_path_is_resolved_against_backend_not_the_cwd(), test_settings_from_env_use_the_resolved_path()

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 117 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.32
Nodes (6): alembic_config, main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., upgrade_schema()

### Community 121 - "get_reality_gap_chain"
Cohesion: 0.47
Nodes (6): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…

### Community 123 - "OllamaAuthError"
Cohesion: 0.33
Nodes (4): OllamaAuthError, Raised on 401/403. Deliberately retried (see generate_structured's @retry…, test_after_a_401_further_calls_fail_fast_without_any_network_call(), test_request_id_is_sent_and_returned_and_secrets_never_logged()

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "test_ollama_failure_modes.py"
Cohesion: 0.12
Nodes (12): Cooldown for a 429: honour Retry-After (seconds), else an escalating default…, Echo, BaseModel, fixture, Ollama client failure handling (spec phases 14-15): 401, 403, 429, timeout,…, _reset_metrics(), test_429_backoff_escalates_without_retry_after(), test_429_retry_after_http_date_is_honoured_and_clamped() (+4 more)

### Community 135 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 136 - "latest"
Cohesion: 0.60
Nodes (5): _decision(), history(), latest(), AsyncSession, get

### Community 137 - "migrate_postgres_to_sqlite.py"
Cohesion: 0.67
Nodes (3): main(), migrate(), One-off: copy every row from the live Postgres database into a fresh SQLite…

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

## Knowledge Gaps
- **100 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+95 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1174 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **26 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `PaperExecutionAdapter`, `StrategyStage`, `Agent`, `config.py`, `Settings`, `env.py`, `routes/status.py`, `decision_loop.py`, `migrate_postgres_to_sqlite.py`, `FakeHyperliquid`, `shadow_adapter.py`, `run_backtest`, `RiskDecision`, `StrategyVersion`, `_fast`, `test_worker_fencing.py`, `test_champion_challenger_service.py`, `test_council_failclosed.py`, `test_metrics_emission.py`, `test_postgres_concurrency.py`, `Bias`, `AgentStatus`, `backtesting/engine.py`, `tradability.py`, `run_and_persist_adversarial_suite`, `test_reality_gap_engine.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `compute_fitness`, `test_shadow_mode.py`, `MarketDataService`, `test_oos_lockbox.py`, `cycle.py`, `HyperliquidClient`, `test_regime_validation_engine.py`, `OrderStatus`, `test_stage_metrics.py`, `test_council_deadline.py`, `below_min_order_notional`, `OllamaClient`, `test_lifecycle_ports.py`, `export.py`, `Decision`, `Trade`, `make_dna`, `test_stops_trailing.py`, `registry.py`, `pytest`, `test_api_endpoints.py`, `enums.py`, `conftest.py`, `test_council_integration.py`, `test_promotion_evidence.py`, `test_funding.py`, `strategy.py`, `test_live_backtest_parity.py`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Why does `StrategyVersion` connect `StrategyVersion` to `PaperExecutionAdapter`, `Base`, `StrategyStage`, `Agent`, `config.py`, `get_settings`, `decision_loop.py`, `FakeHyperliquid`, `test_champion_challenger_service.py`, `test_council_failclosed.py`, `test_postgres_concurrency.py`, `AgentStatus`, `backtesting/engine.py`, `run_and_persist_adversarial_suite`, `test_reality_gap_engine.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_correlation.py`, `test_oos_lockbox.py`, `cycle.py`, `test_regime_validation_engine.py`, `Runbook`, `shadow_fitness.py`, `trades.py`, `test_stage_metrics.py`, `analytics_store.py`, `test_lifecycle_ports.py`, `test_strategy_dna.py`, `Trade`, `make_dna`, `pytest`, `fitness_service.py`, `test_decision_loop_characterization.py`, `StrategyFamily`, `shadow_rows_for_generation`, `test_promotion_evidence.py`, `strategy_dna.py`, `export_report`, `strategy.py`, `routes/champion_challenger.py`, `list_challengers`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `PaperExecutionAdapter`, `Base`, `StrategyStage`, `get_settings`, `routes/status.py`, `decision_loop.py`, `shadow_adapter.py`, `RiskDecision`, `StrategyVersion`, `test_worker_fencing.py`, `test_champion_challenger_service.py`, `AgentStatus`, `backtesting/engine.py`, `tradability.py`, `test_reality_gap_engine.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `compute_fitness`, `test_correlation.py`, `test_regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `trades.py`, `below_min_order_notional`, `analytics_store.py`, `test_lifecycle_ports.py`, `Decision`, `Trade`, `make_dna`, `pytest`, `fitness_service.py`, `test_decision_loop_characterization.py`, `StrategyFamily`, `shadow_rows_for_generation`, `test_promotion_evidence.py`, `export_report`, `strategy.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 94 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._