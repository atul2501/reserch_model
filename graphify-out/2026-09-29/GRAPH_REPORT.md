# Graph Report - reserch_model  (2026-09-27)

## Corpus Check
- 325 files · ~227,094 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 3, .service 3, .ini 2)

## Summary
- 4011 nodes · 15036 edges · 145 communities (114 shown, 31 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2128 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8af6d300`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- PaperExecutionAdapter
- sqlalchemy
- helpers_agents.py
- sqlalchemy_ext_asyncio
- run_cycle.py
- get_settings
- Settings
- routes/status.py
- test_ws_client.py
- decision_loop.py
- indicators.py
- MarketCandle
- BacktestResult
- run_backtest
- test_stops_trailing.py
- RiskDecision
- test_strategy_dna.py
- MarketRegime
- test_metrics_emission.py
- test_ollama_schema_normalization.py
- test_champion_challenger_service.py
- test_reality_gap_engine.py
- cycle.py
- test_postgres_concurrency.py
- run_council_cycle
- test_decision_loop.py
- RuleSet
- test_snapshots_and_lifecycle.py
- StrategyDNA
- test_oos_lockbox.py
- test_ollama_failure_modes.py
- strategy_regime.py
- lockbox.py
- test_shadow_fitness_synthetic.py
- ExecutionRequest
- StrategyStage
- pipeline.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- StrategyVersion
- compute_fitness
- OllamaCallStats
- correlation_service.py
- paper_adapter.py
- families.py
- MarketDataService
- new_client_order_id
- test_worker_fencing.py
- typing
- HyperliquidClient
- test_regime_validation_engine.py
- OrderStatus
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- export.py
- test_shadow_mode.py
- test_council_failclosed.py
- requested_notional
- Trade
- Bias
- Local Migration
- OllamaClient
- test_no_live_orders.py
- routes/correlation.py
- Decision
- run_and_persist_adversarial_suite
- test_check_constraints_are_enforced_by_postgres_itself
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- config.py
- tradability.py
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- test_api_endpoints.py
- test_analytics_migration.py
- test_migrations.py
- Agent
- test_dna_runtime_coverage.py
- sys
- test_decision_loop_characterization.py
- set_kill_switch
- routes/adversarial.py
- routes/regime_validation.py
- conftest.py
- shadow_rows_for_generation
- test_uvicorn_access_log_formats_and_is_redacted
- report_trade_quality.py
- Heartbeat
- compute_oos_score
- run.sh
- test_dashboard_js.py
- Side
- test_backtesting.py
- AbuseGuard
- propose_candidate
- test_cooldown_limits.py
- WsCandle
- ImmutableAnalyticsRecordError
- below_min_order_notional
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- pytest
- Multi-Week Research Readiness Report
- helpers_shadow.py
- graphify reference: extra exports and benchmark
- alembic_config
- routes/reality_gap.py
- migrate_sqlite_to_postgres.py
- graphify reference: query, path, explain
- purge_secrets_from_history.sh
- env.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: GitHub clone and cross-repo merge
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 236 edges
2. `PaperExecutionAdapter` - 189 edges
3. `Agent` - 164 edges
4. `StrategyDNA` - 157 edges
5. `make_agents()` - 154 edges
6. `Side` - 148 edges
7. `make_dna()` - 147 edges
8. `StrategyVersion` - 135 edges
9. `make_context()` - 132 edges
10. `StrategyStage` - 125 edges

## Surprising Connections (you probably didn't know these)
- `5. PositionCloseSettler boundary` --references--> `retire_generation()`  [INFERRED]
  ARCHITECTURE_REVIEW.md → backend/app/agents/lifecycle.py
- `Research` --references--> `experiments()`  [INFERRED]
  docs/runbook.md → backend/app/api/routes/evolution.py
- `7. Candidate extraction boundary, if justified` --references--> `backtest_risk_check()`  [INFERRED]
  REFACTOR_PROGRESS.md → backend/app/backtesting/risk_adapter.py
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py

## Import Cycles
- None detected.

## Communities (145 total, 31 thin omitted)

### Community 0 - "PaperExecutionAdapter"
Cohesion: 0.09
Nodes (86): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), PaperExecutionAdapter, cycle(), make_agents(), make_context() (+78 more)

### Community 1 - "sqlalchemy"
Cohesion: 0.07
Nodes (80): _components_of(), DB I/O for the analytics foundation. The ONLY module that writes, and it writes…, Base, Async SQLAlchemy engine/session management., Wires app/backtesting/adversarial.py's run_adversarial_suite (previously…, AdversarialTestReport, Persisted adversarial-suite results — insert-only, one row per run, so…, Trading agent — one independent paper/shadow/live account. Spec sections 12-16:… (+72 more)

### Community 2 - "helpers_agents.py"
Cohesion: 0.10
Nodes (44): CooldownConfig, IndicatorConfig, PositionSizing, BaseModel, Strategy DNA schema (spec section 10). This is the contract between the…, What Ollama (or the mutation/crossover engine) must produce for a new candidate…, One named indicator instance the strategy depends on, e.g. {"name": "rsi",…, RiskProfile (+36 more)

### Community 3 - "sqlalchemy_ext_asyncio"
Cohesion: 0.10
Nodes (35): get_regime_performance(), get_side_performance(), get_strategy_performance(), list_trades(), AsyncSession, get, Breaks down closed-trade performance by strategy family. A trade's strategy is…, Breaks down closed-trade performance by the market regime that was active when… (+27 more)

### Community 4 - "run_cycle.py"
Cohesion: 0.08
Nodes (39): argparse, asyncio, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory() (+31 more)

### Community 5 - "get_settings"
Cohesion: 0.03
Nodes (53): _acquire_stream_slot(), One concurrent-SSE slot; release() is idempotent (generator finally + response…, _StreamSlot, get_settings(), create_app(), lifespan(), FastAPI application entrypoint. This process serves the read API and realtime…, test_settings_drive_the_config_including_the_formerly_dead_knobs() (+45 more)

### Community 6 - "Settings"
Cohesion: 0.09
Nodes (37): 3. Current cross-community bridge nodes, field_validator, str, All gates required by spec section 40 before ANY live order. This does not…, Settings, TradingMode, HyperliquidLiveExecutionAdapter, Hyperliquid LIVE execution adapter — spec sections 5/19/39/40. STATUS:… (+29 more)

### Community 7 - "routes/status.py"
Cohesion: 0.09
Nodes (41): _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37)., API-process counters + worker-published counters + DB-derived gauges… (+33 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.07
Nodes (41): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, test_ws_reconnects_are_counted(), candle(), FakeServer, make() (+33 more)

### Community 9 - "decision_loop.py"
Cohesion: 0.06
Nodes (75): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+67 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (65): jitter(), mutate(), _mutate_indicator_period(), _mutate_ruleset_thresholds(), Random, DNA mutation (spec section 25). Produces a new, independently-valid StrategyDNA…, Changes one declared indicator's period AND rewrites every rule that referenced…, _atr() (+57 more)

### Community 11 - "MarketCandle"
Cohesion: 0.09
Nodes (52): active_flags(), Returns {flag_name: reason} for every currently-active flag., MarketCandle, clock_after_bar(), FakeHyperliquid, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format. (+44 more)

### Community 12 - "BacktestResult"
Cohesion: 0.18
Nodes (13): BacktestResult, persist_backtest_metrics(), Builds a StageMetrics row from a single backtest run (BACKTEST or OUT_OF_SAMPLE…, WalkForwardWindow, _backtest_result(), asyncio, UUID, Persisted per-stage performance snapshots and reality-gap comparison (spec… (+5 more)

### Community 13 - "run_backtest"
Cohesion: 0.12
Nodes (43): DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward(), _fingerprint(), Adversarial testing v2 (spec phase 28): execution-fault scenarios, configured… (+35 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.20
Nodes (26): advance_extremes(), Bar, bar_time(), evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of… (+18 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (43): backtest_risk_check(), Routes backtest/adversarial position sizing through the real…, Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every… (+35 more)

### Community 16 - "test_strategy_dna.py"
Cohesion: 0.19
Nodes (17): _blend(), crossover(), Random, DNA crossover (spec section 25): combine two successful parents' DNA into one…, dna_distance(), A simple, interpretable [0, 1] distance: 0 = identical family and near-…, _minimal_dna(), DNA validation, mutation, crossover, versioning (spec section 45). (+9 more)

### Community 17 - "MarketRegime"
Cohesion: 0.11
Nodes (38): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), MarketRegime, _bar_regimes(), DataFrame, parametrize (+30 more)

### Community 18 - "test_metrics_emission.py"
Cohesion: 0.11
Nodes (27): counter_value(), _escape(), _fmt(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint…, record_db_error() (+19 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.07
Nodes (65): Ollama-driven strategy research (spec section 26). Ollama proposes candidate…, BoundedResponse, _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json() (+57 more)

### Community 20 - "test_champion_challenger_service.py"
Cohesion: 0.16
Nodes (37): advance_pipeline_stage(), _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report(), AsyncSession, UUID, ChampionChallengerEngine: walks a StrategyVersion through the Candidate ->… (+29 more)

### Community 21 - "test_reality_gap_engine.py"
Cohesion: 0.17
Nodes (21): compute_full_reality_gap_chain(), persist_reality_gap_report(), AsyncSession, UUID, Full-lifecycle reality-gap report: Backtest -> Walk-Forward -> Out-of-Sample ->…, Compares every consecutive pair of stages this strategy version has actually…, Insert-only — caller commits., RealityGapChainReport (+13 more)

### Community 22 - "cycle.py"
Cohesion: 0.09
Nodes (43): AsyncSession, Read/write helpers for durable system flags (kill switch, data-gap halt)., Single string (or None) the risk engine uses to block NEW entries., set_flag(), trading_halt_reason(), CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar… (+35 more)

### Community 23 - "test_postgres_concurrency.py"
Cohesion: 0.07
Nodes (37): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, utcnow(), db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id() (+29 more)

### Community 24 - "run_council_cycle"
Cohesion: 0.06
Nodes (71): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), AICallStats, AIClientPort (+63 more)

### Community 25 - "test_decision_loop.py"
Cohesion: 0.09
Nodes (61): DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, run_decision_cycle(), _atr(), _bollinger(), compute_features(), _ema(), _macd() (+53 more)

### Community 26 - "RuleSet"
Cohesion: 0.09
Nodes (51): Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet, _all_rulesets(), available_feature_keys() (+43 more)

### Community 27 - "test_snapshots_and_lifecycle.py"
Cohesion: 0.05
Nodes (70): AgentAlreadyDeadError, bankruptcy_threshold(), create_generation(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession, datetime (+62 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.14
Nodes (42): StrategyFamily, ComparisonOperator, Enum, field_validator, model_validator, str, Combinations the schema ACCEPTS but that silently do nothing (or something…, StrategyDNA (+34 more)

### Community 29 - "test_oos_lockbox.py"
Cohesion: 0.08
Nodes (41): BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, Adds any indicator series not yet present (idempotent; a spec whose series all… (+33 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.06
Nodes (54): OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError, OllamaServerError (+46 more)

### Community 31 - "strategy_regime.py"
Cohesion: 0.09
Nodes (37): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+29 more)

### Community 32 - "lockbox.py"
Cohesion: 0.07
Nodes (55): derive_seed(), A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id,…, _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments(), AsyncSession (+47 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.14
Nodes (31): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, current_fitness(), make_population(), (production compute_fitness, max drawdown) fed the way fitness_service feeds…, world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions() (+23 more)

### Community 34 - "ExecutionRequest"
Cohesion: 0.13
Nodes (17): Deterministic settlement at the modelled price when the engine keeps failing to…, _synthetic_exit_fill(), close(), slip(), ExecutionRequest, ExecutionResult, Submits an order and returns its fill result. Implementations MUST be…, fee_rate_for() (+9 more)

### Community 35 - "StrategyStage"
Cohesion: 0.06
Nodes (86): What should NOT be refactored, comparability(), compute_live_stage_metrics(), compute_missed_trade_stats(), compute_reality_gap(), latest_stage_metrics(), _max_drawdown(), _metric_value() (+78 more)

### Community 36 - "pipeline.py"
Cohesion: 0.07
Nodes (51): events(), experiment_diff(), experiments(), generations(), AsyncSession, get, Baseline-vs-candidate diff for two experiment_ids (see…, summary() (+43 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.06
Nodes (69): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, ResearchEpoch, _build_epoch() (+61 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.13
Nodes (22): TradeEvidence, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), with_extra_cost(), _agent() (+14 more)

### Community 39 - "analyze_trade"
Cohesion: 0.17
Nodes (28): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+20 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.08
Nodes (54): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+46 more)

### Community 41 - "StrategyVersion"
Cohesion: 0.06
Nodes (83): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+75 more)

### Community 42 - "compute_fitness"
Cohesion: 0.05
Nodes (80): _clip(), compute_fitness(), FitnessInputs, FitnessResult, FitnessWeights, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,… (+72 more)

### Community 43 - "OllamaCallStats"
Cohesion: 0.16
Nodes (13): OllamaCallStats, BareMinimumClient, asyncio, parametrize, The boundary is real: neither council module imports app.services.ollama_client…, OllamaClient itself is UNCHANGED and still works as the council's AI client -…, Deliberately NOT an OllamaClient, not a subclass, not registered with it - only…, End-to-end proof: the full council cycle (quorum, consensus, persistence) runs… (+5 more)

### Community 44 - "correlation_service.py"
Cohesion: 0.07
Nodes (47): _most_correlated_pair(), The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _make_candidates(), _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity() (+39 more)

### Community 45 - "paper_adapter.py"
Cohesion: 0.10
Nodes (26): ABC, ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+18 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "MarketDataService"
Cohesion: 0.09
Nodes (22): _as_float(), _chunks(), _dialect_insert(), GapReport, MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion. (+14 more)

### Community 48 - "new_client_order_id"
Cohesion: 0.28
Nodes (8): new_client_order_id(), Deterministic idempotency key: same (agent, decision, action) always yields the…, asyncio, test_duplicate_client_order_id_is_rejected_not_double_filled(), test_paper_adapter_applies_fees_and_slippage(), test_paper_adapter_never_makes_network_calls(), 3. Actual coupling problems found (the real targets), Phase 4 — proposed plan for `decision_loop.py` (NOT implemented; plan only, pending approval)

### Community 49 - "test_worker_fencing.py"
Cohesion: 0.10
Nodes (32): LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _close_keepers(), _counts(), _keeper(), paper(), fixture (+24 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.09
Nodes (21): BookProvider, Protocol, HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context., Wraps Hyperliquid's `/info` endpoint. Live order placement (the exchange-… (+13 more)

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.12
Nodes (37): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+29 more)

### Community 53 - "OrderStatus"
Cohesion: 0.19
Nodes (18): OrderStatus, Paper execution realism (spec phase 7): slippage, fees, latency, partial fills,…, _req(), test_entry_slippage_is_adverse_for_both_sides(), test_exit_slippage_is_adverse_too(), test_fee_is_charged_on_filled_notional(), test_fills_are_deterministic_per_order_id_and_independent_of_order_of_arrival(), test_idempotent_on_client_order_id() (+10 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (36): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+28 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.21
Nodes (17): champion_evidence_ok(), estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, _samples() (+9 more)

### Community 57 - "export.py"
Cohesion: 0.06
Nodes (43): _decision(), history(), latest(), AsyncSession, get, _build(), _cell_value(), _convergence_rows() (+35 more)

### Community 58 - "test_shadow_mode.py"
Cohesion: 0.14
Nodes (23): 6. ExecutionEngine boundary, L2Book, parse_book(), Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter, walk_book(), book() (+15 more)

### Community 59 - "test_council_failclosed.py"
Cohesion: 0.10
Nodes (25): OllamaKeyHealth, Re-read credentials from settings WITHOUT a restart. A key whose value is…, In-memory credential health. Keys are intentionally never persisted or logged.…, council_on(), fixture, Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, _run(), test_a_verdict_for_another_candle_is_never_applied() (+17 more)

### Community 60 - "requested_notional"
Cohesion: 0.12
Nodes (33): 12. Live/backtest duplication, approve_against_margin(), build_sizing_result(), normalize_method(), Position sizing (spec phase 6): pure, deterministic, unit-tested. Supported DNA…, Fractional distance from entry to the protective stop (matches the stop…, What the DNA wants, before risk clamps. Never negative., Caps notional so required margin never exceeds AVAILABLE margin — equity being… (+25 more)

### Community 61 - "Trade"
Cohesion: 0.06
Nodes (64): _bar_ms(), _is_uuid(), _ms(), AsyncSession, Bar, datetime, Rebuild the matrix for `computation_version` (derived aggregate: DELETE the…, For every recorded FitnessScore snapshot (plus an hourly reconstruction grid… (+56 more)

### Community 62 - "Bias"
Cohesion: 0.11
Nodes (37): _council_context(), apply_judge(), compute_consensus(), Deterministic consensus engine (spec section 9). Never produced by an LLM —…, A "strong" consensus is a lead of at least `consensus_margin` votes over the…, Overlays a judge's ruling onto a weak-consensus result. The risk engine…, tally_votes(), combine() (+29 more)

### Community 63 - "Local Migration"
Cohesion: 0.08
Nodes (22): model_validator, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real…, Three processes share the database. If their pools alone could exceed the…, Future Production Migration, Known limitations found during the local migration (apply to production too), Local Migration (+14 more)

### Community 64 - "OllamaClient"
Cohesion: 0.05
Nodes (40): 10. Market-data dependency direction, 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, 9. Database dependency direction, Improvements achieved (+32 more)

### Community 65 - "test_no_live_orders.py"
Cohesion: 0.12
Nodes (14): code_only(), fixture, FINAL SAFETY PROOF (spec phase 32): TRADING_MODE=paper cannot send a real…, Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, recorded_requests(), _sources(), test_every_http_post_in_the_codebase_targets_an_allowlisted_endpoint_or_is_internal() (+6 more)

### Community 66 - "routes/correlation.py"
Cohesion: 0.23
Nodes (14): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+6 more)

### Community 67 - "Decision"
Cohesion: 0.16
Nodes (24): Decision, count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,… (+16 more)

### Community 68 - "run_and_persist_adversarial_suite"
Cohesion: 0.18
Nodes (12): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, AsyncSession, DataFrame, UUID, Loads `strategy_version_id`'s DNA, runs the full adversarial suite (risk-gated…, run_and_persist_adversarial_suite(), asyncio (+4 more)

### Community 69 - "test_check_constraints_are_enforced_by_postgres_itself"
Cohesion: 0.67
Nodes (3): test_check_constraints_are_enforced_by_postgres_itself(), order(), pend()

### Community 70 - "test_funding.py"
Cohesion: 0.38
Nodes (11): FundingPayment, One funding settlement charged to (or credited to) one position. The (position,…, _dna(), _hold_across(), Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.14
Nodes (13): 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Experiment Guide, From the CLI (+5 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "config.py"
Cohesion: 0.20
Nodes (12): Enum, Centralized application configuration. Every environment-dependent value in the…, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch…, test_absolute_memory_and_other_urls_are_untouched(), test_defaults_point_at_the_single_data_folder(), test_parent_folder_is_created() (+4 more)

### Community 74 - "tradability.py"
Cohesion: 0.24
Nodes (11): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, Which agents can be TESTED at their capital (Option D of the min-notional…, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids() (+3 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.12
Nodes (22): _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess, fixture (+14 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.44
Nodes (10): Agents that cannot reach the exchange minimum order at their capital are…, _run_bars(), test_agents_without_any_blocked_entries_rank_exactly_as_before(), test_blocked_entry_decision_records_the_minimum_it_missed(), test_exclusion_can_be_switched_off_to_reproduce_the_old_ranking(), test_only_the_agent_whose_entries_are_blocked_is_untestable(), test_too_few_blocked_entries_is_not_enough_to_call_an_agent_untestable(), test_untestable_agent_is_never_selected_as_a_survivor_even_with_the_top_fitness() (+2 more)

### Community 78 - "test_api_endpoints.py"
Cohesion: 0.21
Nodes (10): publish_status(), candle(), Dashboard/API surface (spec phases 35-37): confirmed-candle market view,…, test_exit_analytics_endpoint_summarises_and_filters_trade_analytics(), test_market_endpoint_reports_the_confirmed_candle_and_keeps_the_forming_one_separate(), test_ollama_health_endpoint_needs_operator_and_never_leaks_key_values(), test_sse_stream_emits_status_and_cycle_events(), test_status_reports_stale_market_data_and_data_gap_halt() (+2 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.16
Nodes (12): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+4 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.26
Nodes (12): alembic_autogenerate, alembic_migration, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs() (+4 more)

### Community 81 - "Agent"
Cohesion: 0.07
Nodes (55): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+47 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.21
Nodes (11): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_dna_field_is_either_runtime_covered_or_documented_metadata() (+3 more)

### Community 83 - "sys"
Cohesion: 0.27
Nodes (10): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+2 more)

### Community 84 - "test_decision_loop_characterization.py"
Cohesion: 0.22
Nodes (13): _build_scenario(), capture_state(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, See module docstring for exactly what is/isn't included and why. (+5 more)

### Community 85 - "set_kill_switch"
Cohesion: 0.20
Nodes (11): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+3 more)

### Community 86 - "routes/adversarial.py"
Cohesion: 0.33
Nodes (8): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, AdversarialTestReportOut, BaseModel, ScenarioBreakdownOut

### Community 87 - "routes/regime_validation.py"
Cohesion: 0.33
Nodes (8): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID, BaseModel, RegimeStatsOut, RegimeValidationReportOut

### Community 88 - "conftest.py"
Cohesion: 0.21
Nodes (10): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+2 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.22
Nodes (12): rank_correlation(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat() (+4 more)

### Community 90 - "test_uvicorn_access_log_formats_and_is_redacted"
Cohesion: 0.22
Nodes (9): uvicorn's AccessFormatter unpacks record.args into 5 fields; the redaction…, test_uvicorn_access_log_formats_and_is_redacted(), test_repository_tracked_files_are_clean(), 4. Verification, Final test suite run, Final status, Local, PostgreSQL Migration Report (+1 more)

### Community 91 - "report_trade_quality.py"
Cohesion: 0.11
Nodes (26): cohort_stats(), _flat(), main(), _pearson(), _ranks(), READ-ONLY fitness -> future-performance report (Reports F and H). python -m…, Average ranks (ties share the mean rank) — deterministic., One cohort (as_of, horizon): the study's statistics, over flattened rows. (+18 more)

### Community 93 - "compute_oos_score"
Cohesion: 0.08
Nodes (28): Fraction of windows that were profitable — a simple, auditable stand-in for…, compute_oos_score(), [0, 1]. Zero without enough trades to say anything. Otherwise: (0.4 *…, A handful of trades cannot earn a near-full score regardless of how clean they…, The bug this fix closes: a 3-trade, ~flat-return, small-drawdown run used to…, test_oos_score_is_confidence_scaled_by_its_own_trade_count(), test_oos_score_needs_trades_and_cannot_be_high_for_a_losing_run(), test_oos_score_pain_term_no_longer_rewards_a_flat_low_drawdown_run_at_low_n() (+20 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (9): cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), is_running(), run.sh script, stop_one() (+1 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "Side"
Cohesion: 0.08
Nodes (49): stop_price(), take_profit_price(), compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL (+41 more)

### Community 97 - "test_backtesting.py"
Cohesion: 0.20
Nodes (16): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+8 more)

### Community 98 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 99 - "propose_candidate"
Cohesion: 0.22
Nodes (8): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _AlwaysFailsClient, asyncio, Duck-typed stand-in for OllamaClient — raises immediately rather than going…, test_propose_candidate_returns_none_on_ollama_rate_limit(), test_propose_candidate_returns_none_on_ollama_timeout(), Exception

### Community 100 - "test_cooldown_limits.py"
Cohesion: 0.38
Nodes (9): _dna(), Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe(), test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day(), test_no_cooldown_configured_allows_immediate_reentry(), _trade_round_trip() (+1 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "below_min_order_notional"
Cohesion: 0.08
Nodes (31): below_min_order_notional(), True when an ENTRY of `notional` at `price` would be refused by the exchange…, deterministic(), fixture, Initiative 1 (LIVE_BACKTEST_PARITY_PLAN.md), Phase 1.1 - characterization only,…, test_backtest_currently_agrees_with_below_min_order_notional_at_a_real_nonzero_threshold(), test_check_mirrors_the_adapter_lot_rounding(), 10. Required characterization/parity tests before implementation (+23 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 108 - "pytest"
Cohesion: 0.20
Nodes (13): factory(), fixture, SQLite write-lock behaviour on a real WAL file shared by two connections…, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle() (+5 more)

### Community 110 - "Multi-Week Research Readiness Report"
Cohesion: 0.20
Nodes (9): 10. FINAL READINESS CHECK, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 9. RECOVERY TEST — real, on the actual dev environment, Known limitations, Multi-Week Research Readiness Report, READY FOR MULTI-WEEK PAPER/SHADOW EXPERIMENT (+1 more)

### Community 113 - "helpers_shadow.py"
Cohesion: 0.27
Nodes (8): ShadowAgentInput, _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, Agents plus the ground truth. `truth_edge[i]` is the true net edge (R/trade) of…, math, types

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 121 - "routes/reality_gap.py"
Cohesion: 0.29
Nodes (10): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…, BaseModel, RealityGapChainReportOut (+2 more)

### Community 123 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.27
Nodes (9): _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., One row of headline aggregates, computed identically against either engine, for…, upgrade_schema(), os (+1 more)

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 135 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1227 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **31 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `PaperExecutionAdapter`, `sqlalchemy`, `helpers_agents.py`, `sqlalchemy_ext_asyncio`, `run_cycle.py`, `Settings`, `env.py`, `routes/status.py`, `decision_loop.py`, `MarketCandle`, `run_backtest`, `test_stops_trailing.py`, `RiskDecision`, `test_metrics_emission.py`, `test_ollama_schema_normalization.py`, `test_champion_challenger_service.py`, `cycle.py`, `test_postgres_concurrency.py`, `run_council_cycle`, `test_decision_loop.py`, `test_snapshots_and_lifecycle.py`, `test_oos_lockbox.py`, `lockbox.py`, `ExecutionRequest`, `StrategyStage`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `StrategyVersion`, `compute_fitness`, `paper_adapter.py`, `MarketDataService`, `new_client_order_id`, `test_worker_fencing.py`, `HyperliquidClient`, `test_regime_validation_engine.py`, `OrderStatus`, `export.py`, `test_shadow_mode.py`, `test_council_failclosed.py`, `requested_notional`, `Bias`, `OllamaClient`, `test_no_live_orders.py`, `Decision`, `run_and_persist_adversarial_suite`, `test_funding.py`, `config.py`, `tradability.py`, `test_untestable_agents.py`, `test_api_endpoints.py`, `set_kill_switch`, `conftest.py`, `Side`, `test_cooldown_limits.py`, `below_min_order_notional`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `StrategyDNA` connect `StrategyDNA` to `PaperExecutionAdapter`, `sqlalchemy`, `helpers_agents.py`, `Settings`, `decision_loop.py`, `indicators.py`, `BacktestResult`, `run_backtest`, `RiskDecision`, `test_strategy_dna.py`, `MarketRegime`, `test_champion_challenger_service.py`, `test_reality_gap_engine.py`, `cycle.py`, `test_decision_loop.py`, `RuleSet`, `test_snapshots_and_lifecycle.py`, `test_oos_lockbox.py`, `lockbox.py`, `StrategyStage`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_adversarial.py`, `StrategyVersion`, `correlation_service.py`, `test_regime_validation_engine.py`, `test_council_failclosed.py`, `requested_notional`, `Trade`, `run_and_persist_adversarial_suite`, `Agent`, `test_dna_runtime_coverage.py`, `Side`, `test_backtesting.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `PaperExecutionAdapter`, `sqlalchemy`, `helpers_agents.py`, `sqlalchemy_ext_asyncio`, `routes/status.py`, `decision_loop.py`, `RiskDecision`, `test_champion_challenger_service.py`, `test_reality_gap_engine.py`, `test_decision_loop.py`, `test_snapshots_and_lifecycle.py`, `StrategyDNA`, `test_oos_lockbox.py`, `StrategyStage`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `StrategyVersion`, `compute_fitness`, `correlation_service.py`, `test_worker_fencing.py`, `HyperliquidClient`, `test_regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `export.py`, `requested_notional`, `Trade`, `Decision`, `tradability.py`, `test_decision_loop_characterization.py`, `shadow_rows_for_generation`, `below_min_order_notional`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 95 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 95 INFERRED edges - model-reasoned connections that need verification._
- **Are the 81 inferred relationships involving `StrategyDNA` (e.g. with `2. Current high-degree nodes` and `3. Current cross-community bridge nodes`) actually correct?**
  _`StrategyDNA` has 81 INFERRED edges - model-reasoned connections that need verification._