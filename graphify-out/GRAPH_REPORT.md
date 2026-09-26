# Graph Report - reserch_model  (2026-09-26)

## Corpus Check
- 316 files · ~211,415 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 3, .service 3, .ini 2)

## Summary
- 3869 nodes · 14535 edges · 148 communities (126 shown, 22 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2044 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `498ed498`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_agents
- Base
- test_promotion_service.py
- sqlalchemy
- config.py
- get_settings
- Settings
- routes/status.py
- test_ws_client.py
- _process_agent_inner
- indicators.py
- FakeHyperliquid
- 3. Side-by-side comparison
- run_backtest
- Side
- RiskDecision
- StrategyVersion
- MarketRegime
- decision_loop.py
- test_ollama_schema_normalization.py
- test_champion_challenger_service.py
- test_council_failclosed.py
- test_metrics_emission.py
- lease.py
- Bias
- compute_features
- strategies/engine.py
- Agent
- StrategyDNA
- backtesting/engine.py
- test_ollama_failure_modes.py
- strategy_regime.py
- untestable_agent_ids
- test_shadow_fitness_synthetic.py
- test_position_protection.py
- StrategyStage
- enums.py
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
- ExecutionRequest
- test_worker_fencing.py
- typing
- HyperliquidClient
- regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- models/market.py
- test_fitness_edge_cases.py
- test_council_deadline.py
- margin_state
- analytics_store.py
- ExecutionVenue
- test_no_live_orders.py
- test_ollama_client.py
- test_lifecycle_ports.py
- routes/correlation.py
- Decision
- Heartbeat
- Position
- make_dna
- test_stops_trailing.py
- What You Must Do When Invoked
- test_fitness_forward.py
- normalization.py
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- test_api_endpoints.py
- test_analytics_migration.py
- test_migrations.py
- Trade
- pathlib
- secret_scan.py
- test_decision_loop_characterization.py
- test_execution_stress_harness.py
- fitness_forward.py
- export.py
- migrate_sqlite_to_postgres.py
- shadow_rows_for_generation
- test_council_integration.py
- analytics.py
- test_promotion_evidence.py
- 24-Hour Data Validation & Next-Phase Execution — Research Report
- run.sh
- test_dashboard_js.py
- HyperliquidWebSocket
- dataset.py
- AbuseGuard
- propose_candidate
- test_cooldown_limits.py
- WsCandle
- _manage_open_position
- Strategy
- Post-Refactoring Architecture Review
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- Phase 4.3 — Sizing/margin ownership investigation (no code changed)
- factory
- RegimeValidationReport
- FakeServer
- constraints.py
- report_strategy_regime.py
- test_db_location.py
- 1. Current architecture (as it actually is, not as the graph implies)
- graphify reference: extra exports and benchmark
- performance_metrics_engine.py
- alembic_config
- test_identical_frame_is_redelivered_after_a_failed_delivery
- ImmutableResearchRecordError
- deterministic
- get_reality_gap_chain
- test_key_refresher_periodic_and_forced
- graphify reference: query, path, explain
- OllamaClient
- purge_secrets_from_history.sh
- env.py
- CouncilDecision
- migrate_postgres_to_sqlite.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: transcribe video and audio
- Echo
- _reset_metrics
- test_key_refresher_never_raises_into_the_trading_loop
- graphify reference: GitHub clone and cross-repo merge
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
- `7. Candidate extraction boundary, if justified` --references--> `backtest_risk_check()`  [INFERRED]
  REFACTOR_PROGRESS.md → backend/app/backtesting/risk_adapter.py
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py

## Import Cycles
- None detected.

## Communities (148 total, 22 thin omitted)

### Community 0 - "make_agents"
Cohesion: 0.12
Nodes (44): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), PositionSizing, cycle(), make_agents(), make_context() (+36 more)

### Community 1 - "Base"
Cohesion: 0.12
Nodes (45): Base, Async SQLAlchemy engine/session management., Persisted adversarial-suite results — insert-only, one row per run, so…, datetime, Shared mixins for ORM models., A timezone-aware DateTime that stays timezone-aware on SQLite too. Postgres's…, TimestampMixin, UTCDateTime (+37 more)

### Community 2 - "test_promotion_service.py"
Cohesion: 0.09
Nodes (44): get_promotion_history(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, The full promotion/rejection audit log for this lineage — champion_id…, events() (+36 more)

### Community 3 - "sqlalchemy"
Cohesion: 0.04
Nodes (21): 9. Database dependency direction, get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, get_db(), AsyncSession (+13 more)

### Community 4 - "config.py"
Cohesion: 0.05
Nodes (68): argparse, asyncio, Which agents can be TESTED at their capital (Option D of the min-notional…, Centralized application configuration. Every environment-dependent value in the…, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger() (+60 more)

### Community 5 - "get_settings"
Cohesion: 0.07
Nodes (29): get_settings(), create_app(), lifespan(), FastAPI application entrypoint. This process serves the read API and realtime…, api(), _db(), fixture, test_health_returns_503_when_the_database_is_down() (+21 more)

### Community 6 - "Settings"
Cohesion: 0.09
Nodes (33): 3. Current cross-community bridge nodes, What should NOT be refactored, Enum, field_validator, str, All gates required by spec section 40 before ANY live order. This does not…, Settings, TradingMode (+25 more)

### Community 7 - "routes/status.py"
Cohesion: 0.06
Nodes (58): _acquire_stream_slot(), _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37). (+50 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.17
Nodes (24): candle(), make(), Hyperliquid WebSocket transport (spec phase 17) against an in-process fake…, _run_until(), test_exact_duplicates_dropped_but_updates_to_the_open_bar_pass(), script(), test_future_dated_frame_is_dropped_and_never_becomes_the_latest_candle(), script() (+16 more)

### Community 9 - "_process_agent_inner"
Cohesion: 0.11
Nodes (33): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _apply_fill_to_order(), _cancel_order(), _close_position(), CycleContext, _execute_next_open_decisions() (+25 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (56): _atr(), compute_indicator(), compute_indicator_features(), compute_indicator_series(), _ema(), _feature_keys_cached(), _ind_adx(), _ind_atr() (+48 more)

### Community 11 - "FakeHyperliquid"
Cohesion: 0.09
Nodes (51): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, active_flags(), Returns {flag_name: reason} for every currently-active flag., MarketCandle, clock_after_bar(), FakeHyperliquid, make_raw_candle() (+43 more)

### Community 12 - "3. Side-by-side comparison"
Cohesion: 0.18
Nodes (14): Deterministic settlement at the modelled price when the engine keeps failing to…, _synthetic_exit_fill(), close(), slip(), fee_rate_for(), The ONE cost model shared by the paper adapter, shadow estimates and the…, Adverse slippage in bps. Resting take-profit limit orders pay none; stops and…, `side` is the ORDER's position side: entering LONG buys (pay up), entering… (+6 more)

### Community 13 - "run_backtest"
Cohesion: 0.11
Nodes (46): DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward(), _fingerprint(), Adversarial testing v2 (spec phase 28): execution-fault scenarios, configured… (+38 more)

### Community 14 - "Side"
Cohesion: 0.13
Nodes (26): bar_time(), ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of…, stop_price(), take_profit_price(), entry_levels(), EntryLevels (+18 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (41): Routes backtest/adversarial position sizing through the real…, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every…, RiskCheckInput, RiskCheckResult, RiskProfile (+33 more)

### Community 16 - "StrategyVersion"
Cohesion: 0.05
Nodes (101): Wires app/backtesting/adversarial.py's run_adversarial_suite (previously…, BreedingResult, check_candidate_schema(), _most_correlated_pair(), NoValidCandidatesError, _preserve_family_distribution(), AsyncSession, Random (+93 more)

### Community 17 - "MarketRegime"
Cohesion: 0.11
Nodes (38): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), MarketRegime, _bar_regimes(), DataFrame, parametrize (+30 more)

### Community 18 - "decision_loop.py"
Cohesion: 0.07
Nodes (52): _cancel_stale_pending(), decision_id_for(), _load_funding(), _process_agent(), protect_open_positions(), AsyncSession, DataFrame, UUID (+44 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.12
Nodes (46): ValueError, The response cannot be safely normalised. `reason` is a short machine-readable…, ResponseNormalizationError, analyst_server(), client_for(), gen(), items(), long_vote() (+38 more)

### Community 20 - "test_champion_challenger_service.py"
Cohesion: 0.15
Nodes (39): list_challengers(), Every non-retired StrategyVersion in this lineage with its latest…, advance_pipeline_stage(), _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report(), AsyncSession (+31 more)

### Community 21 - "test_council_failclosed.py"
Cohesion: 0.16
Nodes (13): council_on(), fixture, Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, _run(), test_a_verdict_for_another_candle_is_never_applied(), test_config_rejects_a_council_that_cannot_reach_quorum_or_outlives_its_candle(), test_control_healthy_council_lets_agents_enter(), test_council_disabled_is_not_required() (+5 more)

### Community 22 - "test_metrics_emission.py"
Cohesion: 0.18
Nodes (15): counter_value(), render_prometheus(), CycleOutcome, _fresh_metrics(), fixture, Every important metric is actually EMITTED by the code path it describes (spec…, series(), test_cycle_latency_and_status_are_emitted_by_the_shared_recorder() (+7 more)

### Community 23 - "lease.py"
Cohesion: 0.09
Nodes (32): utcnow(), db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id(), AsyncSession, Durable single-worker lease (spec: only one active decision worker). The… (+24 more)

### Community 24 - "Bias"
Cohesion: 0.07
Nodes (66): AnalystRunResult, Carries this analyst's own timing/stats directly, rather than reading…, apply_judge(), compute_consensus(), Deterministic consensus engine (spec section 9). Never produced by an LLM —…, A "strong" consensus is a lead of at least `consensus_margin` votes over the…, Overlays a judge's ruling onto a weak-consensus result. The risk engine…, tally_votes() (+58 more)

### Community 25 - "compute_features"
Cohesion: 0.12
Nodes (43): _atr(), _bollinger(), compute_features(), _ema(), _macd(), minimal_context(), DataFrame, Series (+35 more)

### Community 26 - "strategies/engine.py"
Cohesion: 0.14
Nodes (31): build_feature_view(), compute_population_features(), _condition_features(), _entry_direction(), _eval_condition(), _eval_ruleset(), evaluate_signal(), FeatureView (+23 more)

### Community 27 - "Agent"
Cohesion: 0.07
Nodes (65): update_equity that is a no-op on an already-dead agent (a dead agent's account…, _set_equity(), AgentAlreadyDeadError, bankruptcy_threshold(), create_generation(), format_agent_identifier(), is_population_extinct(), mark_dead() (+57 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.16
Nodes (37): StrategyFamily, ComparisonOperator, IndicatorConfig, Enum, field_validator, model_validator, str, Strategy DNA schema (spec section 10). This is the contract between the… (+29 more)

### Community 29 - "backtesting/engine.py"
Cohesion: 0.05
Nodes (66): BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, Adds any indicator series not yet present (idempotent; a spec whose series all… (+58 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.11
Nodes (27): call(), make_client(), parametrize, Ollama client failure handling (spec phases 14-15): 401, 403, 429, timeout,…, test_200_with_malformed_envelope_is_a_typed_response_error(), test_200_with_non_json_body_is_a_typed_response_error_not_a_crash(), test_400_is_not_retried_and_is_a_typed_error(), test_401_single_key_is_not_retried_and_key_is_marked_unhealthy() (+19 more)

### Community 31 - "strategy_regime.py"
Cohesion: 0.09
Nodes (36): bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci(), episode_ids() (+28 more)

### Community 32 - "untestable_agent_ids"
Cohesion: 0.47
Nodes (6): blocked_entry_counts(), AsyncSession, UUID, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids(), Counter

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.10
Nodes (38): ShadowAgentInput, current_fitness(), _fake_backtest(), make_population(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps… (+30 more)

### Community 34 - "test_position_protection.py"
Cohesion: 0.12
Nodes (22): Residual of the cash identity (0.0 when the books balance). balance == starting…, reconcile(), _crash_bar(), FailingExits, open_position(), _positions_at(), Open positions never lose protection (spec phases 9, 24) and books always…, A hand-made open position (as if opened on an earlier bar). (+14 more)

### Community 35 - "StrategyStage"
Cohesion: 0.07
Nodes (62): comparability(), compute_live_stage_metrics(), compute_missed_trade_stats(), compute_reality_gap(), latest_stage_metrics(), _max_drawdown(), _metric_value(), MissedTradeStats (+54 more)

### Community 36 - "enums.py"
Cohesion: 0.07
Nodes (55): compute_full_reality_gap_chain(), persist_reality_gap_report(), AsyncSession, UUID, Full-lifecycle reality-gap report: Backtest -> Walk-Forward -> Out-of-Sample ->…, Compares every consecutive pair of stages this strategy version has actually…, Insert-only — caller commits., RealityGapChainReport (+47 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.06
Nodes (69): _build_epoch(), count_confirmed_candles(), fingerprint_frame(), get_active_epoch(), get_or_create_epoch(), load_confirmed_candles(), load_epoch_candles(), _oos_fingerprint() (+61 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.18
Nodes (20): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, TradeEvidence, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), _agent() (+12 more)

### Community 39 - "analyze_trade"
Cohesion: 0.17
Nodes (28): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+20 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.07
Nodes (60): AdversarialConfig, AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move() (+52 more)

### Community 41 - "OllamaError"
Cohesion: 0.19
Nodes (19): OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError, OllamaServerError (+11 more)

### Community 42 - "compute_fitness"
Cohesion: 0.13
Nodes (31): _clip(), compute_fitness(), FitnessInputs, FitnessResult, FitnessWeights, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,… (+23 more)

### Community 43 - "AIClientPort"
Cohesion: 0.08
Nodes (29): build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), AICallStats, AIClientPort, Protocol, T (+21 more)

### Community 44 - "test_correlation.py"
Cohesion: 0.08
Nodes (52): _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the… (+44 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.13
Nodes (23): L2Book, parse_book(), Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter, walk_book(), book(), FakeBook (+15 more)

### Community 46 - "families.py"
Cohesion: 0.19
Nodes (28): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+20 more)

### Community 47 - "MarketDataService"
Cohesion: 0.07
Nodes (25): _as_float(), _chunks(), _dialect_insert(), GapReport, MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion. (+17 more)

### Community 48 - "ExecutionRequest"
Cohesion: 0.14
Nodes (15): 6. ExecutionEngine boundary, Intentional coupling (do not "fix"), ExecutionRequest, ExecutionResult, Submits an order and returns its fill result. Implementations MUST be…, HyperliquidLiveExecutionAdapter, new_client_order_id(), Deterministic idempotency key: same (agent, decision, action) always yields the… (+7 more)

### Community 49 - "test_worker_fencing.py"
Cohesion: 0.09
Nodes (42): One immutable processing attempt for a confirmed market candle., WorkerCycle, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), test_database_errors_are_counted_when_a_cycle_fails_on_the_database(), _cycles(), Worker cycle integrity (spec phases 1, 2, 21): confirmed candles only,…, The council can take ~45s; the bar is re-verified right before decisions and a… (+34 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.15
Nodes (11): 10. Market-data dependency direction, HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context., Wraps Hyperliquid's `/info` endpoint. Live order placement (the exchange-…, Returns raw Hyperliquid candle dicts: {"t": open_ms, "T": close_ms,… (+3 more)

### Community 52 - "regime_validation_engine.py"
Cohesion: 0.12
Nodes (30): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+22 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.13
Nodes (33): PaperExecutionAdapter, OrderStatus, _orders(), _pos(), Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close…, Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the…, test_a_pending_entry_that_was_not_filled_on_the_next_bar_is_never_filled_late(), test_min_notional_rejects_a_sub_ten_dollar_order() (+25 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (37): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+29 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.18
Nodes (19): champion_evidence_ok(), estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, _samples() (+11 more)

### Community 57 - "models/market.py"
Cohesion: 0.11
Nodes (26): get_market_history(), get_market_snapshot(), AsyncSession, get, The last CONFIRMED (closed) candle is the source of truth; the still-forming…, load_regime_lookup(), AsyncSession, Shared regime-at-timestamp lookup, extracted from… (+18 more)

### Community 58 - "test_fitness_edge_cases.py"
Cohesion: 0.21
Nodes (13): capped_profit_factor(), gross_win / gross_loss; the no-loss case is capped, and no evidence at all (no…, Fraction of windows that were profitable — a simple, auditable stand-in for…, inp(), Fitness edge cases (spec phase 17): zero is a real value, idleness is not…, test_a_dead_agent_pays_a_death_penalty(), test_an_idle_agent_earns_no_survival_credit_and_is_penalised(), test_no_losing_trade_is_a_capped_infinite_profit_factor_not_neutral() (+5 more)

### Community 59 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (19): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+11 more)

### Community 60 - "margin_state"
Cohesion: 0.05
Nodes (70): 12. Live/backtest duplication, compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL, backtest_risk_check() (+62 more)

### Community 61 - "analytics_store.py"
Cohesion: 0.12
Nodes (32): _as_trade_rows(), _bar_ms(), _components_of(), _is_uuid(), _ms(), AsyncSession, Bar, datetime (+24 more)

### Community 62 - "ExecutionVenue"
Cohesion: 0.12
Nodes (13): ABC, ExecutionEngine, Execution engine abstraction (spec section 19). Every trading mode…, `immediate`: an order is filled when submitted (shadow/live: against the real…, The transaction holding these orders rolled back: release their ids (one agent,…, The cycle's transaction committed: the claimed ids are now durable (DB unique…, Release any network resources (no-op for pure-simulation engines)., Hyperliquid LIVE execution adapter — spec sections 5/19/39/40. STATUS:… (+5 more)

### Community 63 - "test_no_live_orders.py"
Cohesion: 0.10
Nodes (17): code_only(), fixture, FINAL SAFETY PROOF (spec phase 32): TRADING_MODE=paper cannot send a real…, Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, recorded_requests(), _sources(), test_even_with_every_gate_open_the_live_adapter_cannot_place_an_order() (+9 more)

### Community 64 - "test_ollama_client.py"
Cohesion: 0.19
Nodes (14): _Echo, _mock_transport(), asyncio, BaseModel, Ollama client failure handling: timeout, 429, malformed response (spec 45)., Root cause of the reported intermittent analyst 401s: with multiple…, test_401_on_every_key_exhausts_retries_and_raises_auth_error(), test_401_on_one_key_is_retried_and_recovers_on_the_next_key() (+6 more)

### Community 65 - "test_lifecycle_ports.py"
Cohesion: 0.14
Nodes (18): PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult, _AlwaysZeroBadDebtSettler, _FakeSettlement, Phase 2 dependency-boundary regression: app/agents/lifecycle.py must not import… (+10 more)

### Community 66 - "routes/correlation.py"
Cohesion: 0.19
Nodes (17): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+9 more)

### Community 67 - "Decision"
Cohesion: 0.13
Nodes (28): Decision, count_noop(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Deletes no-op rows older than `cutoff` in batches. Returns rows deleted., Nulls the duplicated market_context on every remaining row (batched). (+20 more)

### Community 69 - "Position"
Cohesion: 0.08
Nodes (31): Random, Paper execution adapter v2 (spec sections 5/19; phase 7). A research-grade fill…, Order, Position, _fast(), fixture, Independent agents, per-agent failure isolation and DB-level idempotency (spec…, test_a_failing_agent_is_isolated_and_the_rest_of_the_population_trades() (+23 more)

### Community 70 - "make_dna"
Cohesion: 0.10
Nodes (46): CooldownConfig, BaseModel, StopLossConfig, TakeProfitConfig, TrailingStopConfig, _base_exits(), make_dna(), Builders for decision-loop level tests (contexts, DNA, agents, cycle runner). (+38 more)

### Community 71 - "test_stops_trailing.py"
Cohesion: 0.24
Nodes (24): advance_extremes(), Bar, evaluate_bar(), PositionLevels, Peak/trough AFTER this bar, and whether trailing is now armed., trailing_is_active(), L(), _no_sleep() (+16 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "test_fitness_forward.py"
Cohesion: 0.18
Nodes (21): AgentFacts, forward_window(), The production fitness an agent WOULD have had at T, from closed trades only.…, The honest (T, T+h] window: truncated at the earliest real boundary., The immutable facts of an agent needed at any T (no mutable state)., reconstruct_fitness_at(), facts(), point() (+13 more)

### Community 74 - "normalization.py"
Cohesion: 0.19
Nodes (15): BoundedResponse, _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any (+7 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.14
Nodes (19): alembic_migration, _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess (+11 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.31
Nodes (13): is_untestable(), `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Agents that cannot reach the exchange minimum order at their capital are…, _run_bars(), test_agents_without_any_blocked_entries_rank_exactly_as_before(), test_blocked_entry_decision_records_the_minimum_it_missed(), test_exclusion_can_be_switched_off_to_reproduce_the_old_ranking(), test_only_the_agent_whose_entries_are_blocked_is_untestable() (+5 more)

### Community 78 - "test_api_endpoints.py"
Cohesion: 0.20
Nodes (11): publish_status(), candle(), Dashboard/API surface (spec phases 35-37): confirmed-candle market view,…, test_market_endpoint_reports_the_confirmed_candle_and_keeps_the_forming_one_separate(), test_metrics_endpoint_is_operator_only_and_exposes_the_required_series(), test_ollama_health_endpoint_needs_operator_and_never_leaks_key_values(), test_sse_stream_emits_status_and_cycle_events(), test_status_reports_stale_market_data_and_data_gap_halt() (+3 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.14
Nodes (14): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+6 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.29
Nodes (11): alembic_autogenerate, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs(), test_downgrade_then_upgrade_round_trips() (+3 more)

### Community 81 - "Trade"
Cohesion: 0.10
Nodes (43): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+35 more)

### Community 82 - "pathlib"
Cohesion: 0.21
Nodes (11): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_nested_dna_field_is_covered_by_a_named_behaviour_test() (+3 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.29
Nodes (10): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+2 more)

### Community 84 - "test_decision_loop_characterization.py"
Cohesion: 0.13
Nodes (20): _build_scenario(), capture_state(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, See module docstring for exactly what is/isn't included and why. (+12 more)

### Community 85 - "test_execution_stress_harness.py"
Cohesion: 0.20
Nodes (16): ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter, asyncio (+8 more)

### Community 86 - "fitness_forward.py"
Cohesion: 0.20
Nodes (15): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), datetime, Pure fitness->future engine: point-in-time reconstruction and forward windows.… (+7 more)

### Community 87 - "export.py"
Cohesion: 0.09
Nodes (24): _build(), _cell_value(), _convergence_rows(), _fetch(), _flatten(), _plain(), Any, AsyncSession (+16 more)

### Community 88 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.14
Nodes (15): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., upgrade_schema(), db_engine() (+7 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.24
Nodes (12): rank_correlation(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat() (+4 more)

### Community 90 - "test_council_integration.py"
Cohesion: 0.17
Nodes (18): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, test_not_run_means_approved_only_when_the_council_was_not_required() (+10 more)

### Community 91 - "analytics.py"
Cohesion: 0.10
Nodes (32): _ffp_is_write_once(), _ffp_never_delete(), FitnessForwardPerformance, ImmutableAnalyticsRecordError, listens_for, RuntimeError, Derived analytical tables (the analytics foundation). These tables store ONLY…, TradeAnalytics (+24 more)

### Community 92 - "test_promotion_evidence.py"
Cohesion: 0.14
Nodes (30): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, _average_agent_fitness(), _candidate_metrics(), evaluate_and_promote() (+22 more)

### Community 93 - "24-Hour Data Validation & Next-Phase Execution — Research Report"
Cohesion: 0.11
Nodes (17): 10. FINAL STATUS, 24-Hour Data Validation & Next-Phase Execution — Research Report, 4. 24-HOUR BASELINE, 5. EXIT ANALYSIS, 6. EXIT EXPERIMENT PLAN, 7. POSTGRESQL MIGRATION PLAN, 9. ACCEPTANCE CRITERIA, Backup strategy (+9 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (9): cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), is_running(), run.sh script, stop_one() (+1 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "HyperliquidWebSocket"
Cohesion: 0.16
Nodes (7): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, test_callback_failure_does_not_kill_the_stream(), script(), OnCandles

### Community 97 - "dataset.py"
Cohesion: 0.17
Nodes (13): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, FundingRate, Exchange-published funding rate per settlement interval (hourly on…, EpochIntegrityError (+5 more)

### Community 98 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 99 - "propose_candidate"
Cohesion: 0.18
Nodes (10): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, What Ollama (or the mutation/crossover engine) must produce for a new candidate…, StrategyCandidate, _AlwaysFailsClient, asyncio, Duck-typed stand-in for OllamaClient — raises immediately rather than going…, test_propose_candidate_returns_none_on_ollama_rate_limit() (+2 more)

### Community 100 - "test_cooldown_limits.py"
Cohesion: 0.23
Nodes (13): _dna(), _fast(), fixture, Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe(), test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day() (+5 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "_manage_open_position"
Cohesion: 0.29
Nodes (12): _accrue_funding(), _manage_open_position(), _protect_one(), Applies every exchange-published funding settlement in (last processed…, Returns True if the position was closed this bar. Idempotent per bar., Callers affected, Exact position-protection/management logic and its callers, Phase 4.2 — Extraction performed (+4 more)

### Community 103 - "Strategy"
Cohesion: 0.07
Nodes (53): get_regime_performance(), Breaks down closed-trade performance by the market regime that was active when…, A strategy lineage, e.g. STRAT-MOM-001. Immutable identity; the DNA itself…, Strategy, Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet (+45 more)

### Community 104 - "Post-Refactoring Architecture Review"
Cohesion: 0.20
Nodes (9): 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, Improvements achieved, Post-Refactoring Architecture Review, Recommended next initiatives (+1 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "Phase 4.3 — Sizing/margin ownership investigation (no code changed)"
Cohesion: 0.18
Nodes (10): 10. Expected blast radius, 11. Explicit recommendation: Phase 4.4 should NOT proceed as originally scoped, 5. Architectural problem, if any, 6. Would moving this logic change trading behavior?, 7. Candidate extraction boundary, if justified, 9. Risk assessment, Full test suite (both phases combined), Phase 4.3 — Sizing/margin ownership investigation (no code changed) (+2 more)

### Community 108 - "factory"
Cohesion: 0.28
Nodes (9): factory(), fixture, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle(), ws() (+1 more)

### Community 109 - "RegimeValidationReport"
Cohesion: 0.33
Nodes (9): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID, RegimeValidationReport, BaseModel, RegimeStatsOut (+1 more)

### Community 110 - "FakeServer"
Cohesion: 0.22
Nodes (3): FakeServer, Scriptable exchange: every accepted connection runs `script(ws, conn_index)`., test_graceful_shutdown_returns_promptly()

### Community 111 - "constraints.py"
Cohesion: 0.50
Nodes (3): attach_constraints(), Database-level invariants (spec phase 26). Python validation alone is not…, Idempotently attaches every CHECK and the extra partial unique indexes to…

### Community 112 - "report_strategy_regime.py"
Cohesion: 0.46
Nodes (7): StrategyRegimeMatrix, _flat(), _fmt(), _fmt_pct(), main(), READ-ONLY Strategy x Regime report (Reports A and G). python -m…, render()

### Community 113 - "test_db_location.py"
Cohesion: 0.14
Nodes (13): model_validator, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, Three processes share the database. If their pools alone could exceed the…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch…, test_absolute_memory_and_other_urls_are_untouched() (+5 more)

### Community 114 - "1. Current architecture (as it actually is, not as the graph implies)"
Cohesion: 0.25
Nodes (7): 1. Current architecture (as it actually is, not as the graph implies), 4. Proposed target architecture, 5. Migration phases (revised order — risk-ascending, not the original numbering), 6. Risks, 7. Behavior that must remain unchanged (explicit checklist for every phase), 8. What Phase 0 deliberately does not conclude, Refactor Plan — Phase 0 Analysis

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "performance_metrics_engine.py"
Cohesion: 0.38
Nodes (6): compute_trade_stats(), _max_streaks(), Pure trade-statistics engine feeding PerformanceMetric snapshots.…, Longest consecutive-win and consecutive-loss streaks, in trade order. Flat…, TradeStatsResult, statistics

### Community 118 - "test_identical_frame_is_redelivered_after_a_failed_delivery"
Cohesion: 0.29
Nodes (6): A DB hiccup must not turn the exchange's retry of the SAME frame into a…, test_client_survives_connection_refused_then_connects(), flaky(), script(), test_identical_frame_is_redelivered_after_a_failed_delivery(), script()

### Community 119 - "ImmutableResearchRecordError"
Cohesion: 0.47
Nodes (6): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError

### Community 120 - "deterministic"
Cohesion: 0.67
Nodes (3): deterministic(), fixture, 8. Expected blast radius

### Community 121 - "get_reality_gap_chain"
Cohesion: 0.47
Nodes (6): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "OllamaClient"
Cohesion: 0.09
Nodes (15): OllamaClient, OllamaKeyHealth, Returns (key, key_index). key_index is the position in OLLAMA_API_KEYS (never…, Safe operational state: positions/statuses only, never secrets., True if at least one credential could serve a request right now (or no…, Re-read credentials from settings WITHOUT a restart. A key whose value is…, Cooldown for a 429: honour Retry-After (seconds), else an escalating default…, In-memory credential health. Keys are intentionally never persisted or logged.… (+7 more)

### Community 135 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 136 - "CouncilDecision"
Cohesion: 0.35
Nodes (10): _decision(), history(), latest(), AsyncSession, get, CouncilAnalysis, CouncilDecision, One consensus outcome for one candle — shared by all agents. (+2 more)

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
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1173 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `make_agents`, `Base`, `test_promotion_service.py`, `sqlalchemy`, `config.py`, `Settings`, `env.py`, `routes/status.py`, `_process_agent_inner`, `migrate_postgres_to_sqlite.py`, `FakeHyperliquid`, `3. Side-by-side comparison`, `run_backtest`, `RiskDecision`, `StrategyVersion`, `decision_loop.py`, `test_champion_challenger_service.py`, `test_council_failclosed.py`, `test_metrics_emission.py`, `lease.py`, `Bias`, `Agent`, `backtesting/engine.py`, `untestable_agent_ids`, `test_position_protection.py`, `StrategyStage`, `enums.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `compute_fitness`, `test_shadow_mode.py`, `MarketDataService`, `ExecutionRequest`, `test_worker_fencing.py`, `HyperliquidClient`, `PaperExecutionAdapter`, `models/market.py`, `test_council_deadline.py`, `margin_state`, `ExecutionVenue`, `test_no_live_orders.py`, `test_lifecycle_ports.py`, `Decision`, `Position`, `make_dna`, `test_stops_trailing.py`, `test_untestable_agents.py`, `test_api_endpoints.py`, `test_execution_stress_harness.py`, `fitness_forward.py`, `migrate_sqlite_to_postgres.py`, `test_council_integration.py`, `test_promotion_evidence.py`, `dataset.py`, `test_cooldown_limits.py`, `_manage_open_position`, `Strategy`, `1. Current architecture (as it actually is, not as the graph implies)`, `deterministic`, `OllamaClient`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Why does `OllamaClient` connect `OllamaClient` to `config.py`, `Settings`, `_process_agent_inner`, `FakeHyperliquid`, `decision_loop.py`, `test_ollama_schema_normalization.py`, `test_council_failclosed.py`, `test_metrics_emission.py`, `compute_features`, `test_ollama_failure_modes.py`, `OllamaError`, `AIClientPort`, `ExecutionRequest`, `test_worker_fencing.py`, `test_council_deadline.py`, `margin_state`, `test_no_live_orders.py`, `test_ollama_client.py`, `propose_candidate`, `Post-Refactoring Architecture Review`, `1. Current architecture (as it actually is, not as the graph implies)`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `StrategyVersion` connect `StrategyVersion` to `make_agents`, `Base`, `test_promotion_service.py`, `sqlalchemy`, `FakeHyperliquid`, `decision_loop.py`, `test_champion_challenger_service.py`, `test_council_failclosed.py`, `Agent`, `backtesting/engine.py`, `test_position_protection.py`, `StrategyStage`, `enums.py`, `test_frozen_oos_epoch.py`, `test_adversarial.py`, `test_correlation.py`, `test_worker_fencing.py`, `Runbook`, `shadow_fitness.py`, `models/market.py`, `analytics_store.py`, `Position`, `make_dna`, `Trade`, `test_decision_loop_characterization.py`, `shadow_rows_for_generation`, `test_promotion_evidence.py`, `Strategy`, `1. Current architecture (as it actually is, not as the graph implies)`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 94 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._