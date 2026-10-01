# Graph Report - reserch_model  (2026-10-02)

## Corpus Check
- 341 files · ~262,694 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .service 4, (none) 3, .ini 2)

## Summary
- 4267 nodes · 15916 edges · 165 communities (140 shown, 25 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2192 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9acb2d7b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- breeding.py
- sqlalchemy
- test_reality_gap_normalisation.py
- _Sheet
- MarketDataService
- test_api_security.py
- Settings
- entry_quality_audit.py
- test_ws_client.py
- _process_agent_inner
- indicators.py
- MarketCandle
- pipeline.py
- run_backtest
- test_stops_trailing.py
- RiskDecision
- test_decision_loop_characterization.py
- routes/status.py
- MarketRegime
- test_ollama_schema_normalization.py
- requested_notional
- get_settings
- test_worker_cycle.py
- test_postgres_concurrency.py
- test_council_failclosed.py
- MarketContext
- RuleSet
- test_agent_lifecycle.py
- StrategyDNA
- test_stage_metrics.py
- test_ollama_failure_modes.py
- test_strategy_regime_matrix.py
- BacktestResult
- test_shadow_fitness_synthetic.py
- accounting.py
- research_exit_payoff.py
- test_oos_lockbox.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- test_evolution_gate_and_champions.py
- compute_fitness
- routes/correlation.py
- routes/evolution.py
- test_shadow_mode.py
- families.py
- Trade
- test_entry_quality_audit.py
- pydantic
- database.py
- Side
- test_regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- test_worker_fencing.py
- StrategyStage
- OllamaClient
- below_min_order_notional
- test_as_of_boundaries.py
- service.py
- compute_features
- market_data_service.py
- seal_epoch
- config.py
- Decision
- test_council_deadline.py
- HyperliquidClient
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- Local Migration
- compute_and_persist_agent_fitness
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- test_adversarial_extended.py
- test_analytics_migration.py
- test_migrations.py
- Agent
- test_dna_runtime_coverage.py
- secret_scan.py
- tradability.py
- Position
- make_agents
- evaluate_fitness_versions.py
- conftest.py
- shadow_rows_for_generation
- test_champion_challenger_service.py
- report_fitness_forward.py
- 1. Live execution flow (complete trace)
- test_entry_quality_page.py
- run.sh
- test_dashboard_js.py
- pytest
- test_backtesting.py
- logging.py
- test_promotion_evidence.py
- test_decision_loop.py
- time
- ImmutableAnalyticsRecordError
- load_rows
- 3. Actual coupling problems found (the real targets)
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- test_metrics_emission.py
- 5. Migration phases (revised order — risk-ascending, not the original numbering)
- test_fitness_versions.py
- paper_adapter.py
- env.py
- test_reality_gap_engine.py
- fitness_forward.py
- reconstruct_fitness_at
- graphify reference: extra exports and benchmark
- Bias
- alembic_config
- test_swing_points.py
- enums.py
- hash_api_key
- graphify reference: query, path, explain
- _build_advisory_criteria
- purge_secrets_from_history.sh
- ExecutionRequest
- numpy
- test_breeding.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- entry_quality.py
- test_correlation.py
- set_kill_switch
- test_adversarial_service.py
- propose_candidate
- graphify reference: GitHub clone and cross-repo merge
- code_only
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md
- KeyRefresher
- report_trade_quality.py
- test_cooldown_limits.py
- cycle.py
- migrate_sqlite_to_postgres.py
- helpers_agents.py
- test_fitness_v2.py
- recorded_requests

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 251 edges
2. `PaperExecutionAdapter` - 190 edges
3. `Agent` - 180 edges
4. `make_agents()` - 178 edges
5. `make_dna()` - 172 edges
6. `StrategyDNA` - 159 edges
7. `Side` - 153 edges
8. `StrategyVersion` - 140 edges
9. `Trade` - 138 edges
10. `make_context()` - 133 edges

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

## Communities (165 total, 25 thin omitted)

### Community 0 - "breeding.py"
Cohesion: 0.09
Nodes (31): BreedingResult, _most_correlated_pair(), Random, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the…, The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _make_candidates(), _blend() (+23 more)

### Community 1 - "sqlalchemy"
Cohesion: 0.06
Nodes (84): Wires compute_fitness to real persisted data, so Agent.fitness — read by…, Persists PerformanceMetric snapshots from real Trade/Agent state. Regime-…, get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, Persists backtest/walk-forward/live performance into StageMetrics and compares… (+76 more)

### Community 2 - "test_reality_gap_normalisation.py"
Cohesion: 0.17
Nodes (19): comparability(), compute_live_stage_metrics(), _max_drawdown(), Computes the same 4 base metrics from actual Trade/Agent history for every…, Peak-to-trough drawdown of the account built from `starting` plus each closed…, Whether the two stages can be used as RELIABLE evidence against each other.…, closed_position(), A real (closed) Position row so Trade.position_id satisfies its foreign key… (+11 more)

### Community 3 - "_Sheet"
Cohesion: 0.19
Nodes (9): _build(), _cell_value(), _flatten(), Any, datetime, Nested dicts become dotted columns; lists become JSON text., _Sheet, Workbook (+1 more)

### Community 4 - "MarketDataService"
Cohesion: 0.09
Nodes (23): _as_float(), _chunks(), _dialect_insert(), MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion., Fetches the last `lookback_candles` candles and upserts them. Returns the… (+15 more)

### Community 5 - "test_api_security.py"
Cohesion: 0.08
Nodes (17): create_app(), lifespan(), client(), _keys(), fixture, API authentication / authorization, kill switch, log redaction (spec sections…, A typo'd or stale variable in .env.example would silently do nothing in…, test_auth_required_without_configured_keys_fails_closed() (+9 more)

### Community 6 - "Settings"
Cohesion: 0.07
Nodes (35): 6. ExecutionEngine boundary, What should NOT be refactored, field_validator, str, All gates required by spec section 40 before ANY live order. This does not…, Settings, TradingMode, AbuseGuard (+27 more)

### Community 7 - "entry_quality_audit.py"
Cohesion: 0.21
Nodes (22): build_audit(), _calibration(), _drift(), _feature_importance(), _funnel(), _group_breakdown(), _hold_time_audit(), _metrics() (+14 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.06
Nodes (47): HyperliquidWebSocket, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., test_ws_reconnects_are_counted(), factory(), fixture, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot() (+39 more)

### Community 9 - "_process_agent_inner"
Cohesion: 0.06
Nodes (65): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+57 more)

### Community 10 - "indicators.py"
Cohesion: 0.06
Nodes (66): jitter(), mutate(), _mutate_indicator_period(), _mutate_ruleset_thresholds(), Random, DNA mutation (spec section 25). Produces a new, independently-valid StrategyDNA…, Changes one declared indicator's period AND rewrites every rule that referenced…, _atr() (+58 more)

### Community 11 - "MarketCandle"
Cohesion: 0.13
Nodes (36): MarketCandle, count_confirmed_candles(), clock_after_bar(), FakeHyperliquid, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format., In-memory stand-in for HyperliquidClient (only the methods the service uses). (+28 more)

### Community 12 - "pipeline.py"
Cohesion: 0.06
Nodes (78): argparse, asyncio, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), Wires app/backtesting/adversarial.py's run_adversarial_suite (previously…, derive_seed(), A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id,…, Experiment (+70 more)

### Community 13 - "run_backtest"
Cohesion: 0.10
Nodes (50): BacktestData, extend_with_specs(), prepare_backtest_data(), Adds any indicator series not yet present (idempotent; a spec whose series all…, DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame (+42 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.20
Nodes (26): advance_extremes(), Bar, bar_time(), evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of… (+18 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (41): Routes backtest/adversarial position sizing through the real…, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every…, RiskCheckInput, RiskCheckResult, _python_sources() (+33 more)

### Community 16 - "test_decision_loop_characterization.py"
Cohesion: 0.20
Nodes (15): _build_scenario(), capture_state(), _invalid_dna_agent(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the… (+7 more)

### Community 17 - "routes/status.py"
Cohesion: 0.10
Nodes (36): _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, Health, runtime status, realtime stream (SSE) and metrics (spec phases 36-37)., API-process counters + worker-published counters + DB-derived gauges… (+28 more)

### Community 18 - "MarketRegime"
Cohesion: 0.22
Nodes (19): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, MarketRegime, _bar_regimes(), DataFrame, parametrize, Regime detector v2 (correctness fixes only; no new thresholds). v1 defects,…, (regime, break_of_structure feature) for each of the last `last` bars, each… (+11 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.09
Nodes (58): _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any, ValueError (+50 more)

### Community 20 - "requested_notional"
Cohesion: 0.23
Nodes (16): build_sizing_result(), normalize_method(), Position sizing (spec phase 6): pure, deterministic, unit-tested. Supported DNA…, What the DNA wants, before risk clamps. Never negative., requested_notional(), SizingResult, _dna(), Position sizing (spec phase 6): mathematically explicit, all methods work,… (+8 more)

### Community 21 - "get_settings"
Cohesion: 0.06
Nodes (30): _acquire_stream_slot(), One concurrent-SSE slot; release() is idempotent (generator finally + response…, _StreamSlot, get_settings(), _fast(), fixture, test_sse_stream_slots_are_capped_and_released(), _fast() (+22 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.12
Nodes (32): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One immutable processing attempt for a confirmed market candle., WorkerCycle, _last_done_open_time(), pending_open_times(), AsyncSession (+24 more)

### Community 23 - "test_postgres_concurrency.py"
Cohesion: 0.07
Nodes (36): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, db_now(), _insert_fn(), LeaseKeeper, LeaseState, new_owner_id(), AsyncSession (+28 more)

### Community 24 - "test_council_failclosed.py"
Cohesion: 0.08
Nodes (51): AsyncSession, run_council_cycle(), CouncilDecision, One consensus outcome for one candle — shared by all agents., OllamaKeyHealth, In-memory credential health. Keys are intentionally never persisted or logged.…, council_on(), fixture (+43 more)

### Community 25 - "MarketContext"
Cohesion: 0.21
Nodes (23): minimal_context(), A NEUTRAL-feature context for one CONFIRMED stored candle…, MarketContext, MomentumFeatures, PriceActionFeatures, BaseModel, The shared market context computed once per candle and fanned out to the AI…, Flattened {feature_name: value} view used by the deterministic rule engine… (+15 more)

### Community 26 - "RuleSet"
Cohesion: 0.10
Nodes (46): Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), Condition, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple…, RuleSet, _all_rulesets(), available_feature_keys() (+38 more)

### Community 27 - "test_agent_lifecycle.py"
Cohesion: 0.22
Nodes (17): AgentAlreadyDeadError, format_agent_identifier(), RuntimeError, Updates equity, peak equity, drawdown, and milestone tracking. Never call this…, update_equity(), _fresh_agent(), _make_strategy_version(), asyncio (+9 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.18
Nodes (35): StrategyFamily, model_validator, Combinations the schema ACCEPTS but that silently do nothing (or something…, StrategyDNA, _base_risk(), _build_breakout(), _build_hybrid(), _build_market_structure() (+27 more)

### Community 29 - "test_stage_metrics.py"
Cohesion: 0.12
Nodes (29): BacktestTrade, compute_missed_trade_stats(), compute_reality_gap(), latest_stage_metrics(), _metric_value(), MissedTradeStats, pct_change(), persist_backtest_metrics() (+21 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.07
Nodes (52): counter_value(), OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError (+44 more)

### Community 31 - "test_strategy_regime_matrix.py"
Cohesion: 0.08
Nodes (36): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+28 more)

### Community 32 - "BacktestResult"
Cohesion: 0.08
Nodes (34): BacktestResult, diff_experiments(), list_experiments(), AsyncSession, Runs both DNAs against the SAME active epoch's train+validation frame (never…, Never overwrites, so this is simply every row, newest first — no "current…, {field: (a_value, b_value, difference_or_None)} for every numeric field present…, render_comparison() (+26 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.12
Nodes (30): champion_evidence_ok(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, make_population(), world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions() (+22 more)

### Community 34 - "accounting.py"
Cohesion: 0.11
Nodes (24): stop_price(), take_profit_price(), entry_levels(), EntryLevels, funding_payment(), The ONE implementation of position accounting (paper, shadow, backtest, walk-…, Residual of the cash identity (0.0 when the books balance). balance == starting…, One funding settlement. Positive = the trader PAYS. A positive rate makes longs… (+16 more)

### Community 35 - "research_exit_payoff.py"
Cohesion: 0.16
Nodes (25): class_deep_dive(), compute_rule_membership(), _extra_structure_features(), giveback_stats(), _hold_bucketed(), lifecycle_summary(), load_candles(), load_dataset() (+17 more)

### Community 36 - "test_oos_lockbox.py"
Cohesion: 0.06
Nodes (43): Fraction of windows that were profitable — a simple, auditable stand-in for…, WalkForwardReport, The ONLY data evolution/fitness/selection may see: everything up to and…, slice_train_validation(), evaluate_in_sample(), InSampleEvaluation, DataFrame, `frame`/`data` MUST be the train+validation frame (see… (+35 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.08
Nodes (41): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, EpochIntegrityError, load_epoch_candles() (+33 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.20
Nodes (20): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), _agent(), _pop() (+12 more)

### Community 39 - "analyze_trade"
Cohesion: 0.12
Nodes (36): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+28 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.08
Nodes (56): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+48 more)

### Community 41 - "test_evolution_gate_and_champions.py"
Cohesion: 0.12
Nodes (31): check_candidate_schema(), NoValidCandidatesError, RuntimeError, Selects survivors from `generation_number`, breeds children via…, Every candidate (and every replacement founder) failed the validation gate:…, Gate 1 of the candidate pipeline: the DNA must survive a strict round-trip…, Champion/challenger state that actually drives the population: current…, select_and_breed_next_generation() (+23 more)

### Community 42 - "compute_fitness"
Cohesion: 0.17
Nodes (24): _clip(), compute_fitness(), FitnessInputs, FitnessResult, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,…, [-1, 1]. A 0% win rate over real trades is the WORST score (-1), not neutral;… (+16 more)

### Community 43 - "routes/correlation.py"
Cohesion: 0.18
Nodes (18): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+10 more)

### Community 44 - "routes/evolution.py"
Cohesion: 0.12
Nodes (25): _decision(), history(), latest(), AsyncSession, get, events(), experiment_diff(), experiments() (+17 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.12
Nodes (24): BookProvider, L2Book, parse_book(), Protocol, Shadow execution (spec phase 26) — NOT "paper with a different label". Consumes…, Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter (+16 more)

### Community 46 - "families.py"
Cohesion: 0.07
Nodes (29): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+21 more)

### Community 47 - "Trade"
Cohesion: 0.07
Nodes (57): datetime, Ends a superseded generation cleanly: every open position is closed at…, retire_generation(), PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult (+49 more)

### Community 48 - "test_entry_quality_audit.py"
Cohesion: 0.12
Nodes (28): _add_trade(), api(), datetime, fixture, UUID, Entry Quality Model V1 - SHADOW AUDIT tests (spec: Phase-4 forensic audit…, The funnel's actual_trades count must equal what's really in the trades table…, Purely a read/aggregation service - Trade.net_pnl and count must be bit-for-bit… (+20 more)

### Community 49 - "pydantic"
Cohesion: 0.13
Nodes (17): 11. AI/Ollama dependency direction, AICallStats, AIClientPort, Protocol, T, The council's dependency contract on an AI client (Phase 1 dependency-boundary…, The subset of OllamaCallStats the council actually reads., Everything the council needs from an AI client. Signature matches… (+9 more)

### Community 50 - "database.py"
Cohesion: 0.04
Nodes (94): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), list_agents(), AsyncSession, get (+86 more)

### Community 51 - "Side"
Cohesion: 0.17
Nodes (23): 12. Live/backtest duplication, Per-candle agent evaluation loop (spec sections 3/4/12/32; phases 3-12, 39).…, compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL (+15 more)

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.11
Nodes (39): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+31 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.13
Nodes (35): PaperExecutionAdapter, OrderStatus, _run_live(), _decisions(), _orders(), Minimum order notional is enforced at DECISION time, not discovered a bar later…, test_entry_at_the_minimum_still_creates_a_pending_order(), test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason() (+27 more)

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
Cohesion: 0.10
Nodes (33): new_client_order_id(), Deterministic idempotency key: same (agent, decision, action) always yields the…, LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _close_keepers(), _counts(), _keeper() (+25 more)

### Community 58 - "StrategyStage"
Cohesion: 0.18
Nodes (29): evaluate_and_promote(), Evaluates whether `strategy_version_id`'s metrics at `stage` justify promoting…, StrategyStage, One performance snapshot for a StrategyVersion at a given pipeline stage.…, StageMetrics, add_promotion_evidence(), The full evidence set the promotion gate demands beyond PnL: adversarial…, test_min_stage_days_is_honoured_including_zero() (+21 more)

### Community 59 - "OllamaClient"
Cohesion: 0.06
Nodes (35): 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, Improvements achieved, Intentional coupling (do not "fix"), Post-Refactoring Architecture Review, Recommended next initiatives (+27 more)

### Community 60 - "below_min_order_notional"
Cohesion: 0.07
Nodes (39): backtest_risk_check(), Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, below_min_order_notional(), True when an ENTRY of `notional` at `price` would be refused by the exchange…, decision(), test_check_mirrors_the_adapter_lot_rounding(), 10. Required characterization/parity tests before implementation (+31 more)

### Community 61 - "test_as_of_boundaries.py"
Cohesion: 0.06
Nodes (65): _bar_ms(), _components_of(), _is_uuid(), _ms(), AsyncSession, Bar, datetime, DB I/O for the analytics foundation. The ONLY module that writes, and it writes… (+57 more)

### Community 62 - "service.py"
Cohesion: 0.09
Nodes (41): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), apply_judge(), compute_consensus() (+33 more)

### Community 63 - "compute_features"
Cohesion: 0.16
Nodes (24): _compute_contexts(), Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, _atr(), _bollinger(), compute_features(), _ema(), InsufficientDataError, _macd() (+16 more)

### Community 64 - "market_data_service.py"
Cohesion: 0.12
Nodes (20): active_flags(), AsyncSession, Read/write helpers for durable system flags (kill switch, data-gap halt)., Returns {flag_name: reason} for every currently-active flag., Single string (or None) the risk engine uses to block NEW entries., set_flag(), trading_halt_reason(), GapReport (+12 more)

### Community 65 - "seal_epoch"
Cohesion: 0.13
Nodes (23): _build_epoch(), fingerprint_frame(), get_active_epoch(), get_or_create_epoch(), _oos_fingerprint(), AsyncSession, DataFrame, Freezes `candles` as an epoch: TRAIN and VALIDATION strictly before a fixed,… (+15 more)

### Community 66 - "config.py"
Cohesion: 0.20
Nodes (12): Enum, Centralized application configuration. Every environment-dependent value in the…, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, resolve_sqlite_url(), All SQLite files live in one folder (backend/data/), independent of the launch…, test_absolute_memory_and_other_urls_are_untouched(), test_defaults_point_at_the_single_data_folder(), test_parent_folder_is_created() (+4 more)

### Community 67 - "Decision"
Cohesion: 0.16
Nodes (26): Decision, count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,… (+18 more)

### Community 68 - "test_council_deadline.py"
Cohesion: 0.19
Nodes (19): analyst_from(), _analyst_json(), make_client(), parametrize, Council latency & failure handling (spec phases 13, 16): concurrent analysts,…, test_all_429_makes_council_incomplete_and_fast(), test_analysts_run_concurrently_not_sequentially(), h() (+11 more)

### Community 69 - "HyperliquidClient"
Cohesion: 0.11
Nodes (15): 10. Market-data dependency direction, HyperliquidClient, HyperliquidError, Any, RuntimeError, Thin async client for Hyperliquid's public `info` REST endpoint and websocket…, Fetches perp metadata + current funding/open-interest context., Wraps Hyperliquid's `/info` endpoint. Live order placement (the exchange-… (+7 more)

### Community 70 - "test_funding.py"
Cohesion: 0.38
Nodes (11): FundingPayment, One funding settlement charged to (or credited to) one position. The (position,…, _dna(), _hold_across(), Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.11
Nodes (17): 1. Running a baseline vs. candidate experiment, 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Custom configs (+9 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "Local Migration"
Cohesion: 0.09
Nodes (18): model_validator, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real…, Three processes share the database. If their pools alone could exceed the…, Future Production Migration, Local Migration, PostgreSQL Migration Guide (+10 more)

### Community 74 - "compute_and_persist_agent_fitness"
Cohesion: 0.19
Nodes (15): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+7 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.10
Nodes (25): _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database(), CompletedProcess, fixture (+17 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.33
Nodes (13): AsyncSession, Ranks every agent in `generation_number` by `Agent.fitness` (falling back to…, select_survivors(), Agents that cannot reach the exchange minimum order at their capital are…, _run_bars(), test_agents_without_any_blocked_entries_rank_exactly_as_before(), test_blocked_entry_decision_records_the_minimum_it_missed(), test_exclusion_can_be_switched_off_to_reproduce_the_old_ranking() (+5 more)

### Community 78 - "test_adversarial_extended.py"
Cohesion: 0.10
Nodes (20): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, candles_fingerprint(), DataFrame, AsyncSession, DataFrame, UUID, Loads `strategy_version_id`'s DNA, runs the full adversarial suite (risk-gated… (+12 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.15
Nodes (13): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+5 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.23
Nodes (13): alembic_autogenerate, alembic_migration, _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs() (+5 more)

### Community 81 - "Agent"
Cohesion: 0.11
Nodes (37): _agent_age_days(), _agent_group_stats(), get_agent_metrics(), get_champions_analysis(), get_equity_curve(), get_fitness_components(), get_overview(), get_ranking_stability() (+29 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.14
Nodes (16): 3. Current cross-community bridge nodes, ast, test_default_bind_is_loopback(), test_every_env_example_key_is_a_real_setting(), has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty… (+8 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.23
Nodes (12): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+4 more)

### Community 84 - "tradability.py"
Cohesion: 0.24
Nodes (11): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, Which agents can be TESTED at their capital (Option D of the min-notional…, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids() (+3 more)

### Community 85 - "Position"
Cohesion: 0.13
Nodes (22): Order, Position, _levered_dna(), Margin & liquidation (spec phase 9): explicit margin model; leverage is a real…, test_dead_agents_are_never_processed_again_or_revived(), test_leverage_multiplies_notional_but_margin_stays_within_the_cap(), test_liquidation_closes_the_position_charges_penalty_and_can_kill_the_agent(), test_notional_never_exceeds_available_margin_times_leverage() (+14 more)

### Community 86 - "make_agents"
Cohesion: 0.07
Nodes (65): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), publish_status(), make_agents(), make_context(), make_dna() (+57 more)

### Community 87 - "evaluate_fitness_versions.py"
Cohesion: 0.12
Nodes (27): AgentFacts, The immutable facts of an agent needed at any T (no mutable state)., _bucket_report(), _capture_rate(), _evaluate_version(), _future_for(), _future_profit_factor(), _grid_as_of_points() (+19 more)

### Community 88 - "conftest.py"
Cohesion: 0.21
Nodes (10): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+2 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.33
Nodes (9): rank_correlation(), Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat(), main(), READ-ONLY side-by-side report of the production fitness and the SHADOW (Phase… (+1 more)

### Community 90 - "test_champion_challenger_service.py"
Cohesion: 0.19
Nodes (30): list_challengers(), Every non-retired StrategyVersion in this lineage with its latest…, advance_pipeline_stage(), Attempts to move `strategy_version_id` one step forward in the pipeline.…, asyncio, datetime, ChampionChallengerEngine: the Candidate -> Validation -> Challenger ->…, This is the one place advance_pipeline_stage calls evaluate_and_promote — no… (+22 more)

### Community 91 - "report_fitness_forward.py"
Cohesion: 0.29
Nodes (10): cohort_stats(), _flat(), main(), _pearson(), _ranks(), READ-ONLY fitness -> future-performance report (Reports F and H). python -m…, Average ranks (ties share the mean rank) — deterministic., One cohort (as_of, horizon): the study's statistics, over flattened rows. (+2 more)

### Community 92 - "1. Live execution flow (complete trace)"
Cohesion: 0.16
Nodes (20): Deterministic settlement at the modelled price when the engine keeps failing to…, _synthetic_exit_fill(), close(), slip(), cooldown_bars_after(), cooldown_expiry_ms(), liquidation_penalty(), Bars the agent must sit out after a close (0 with no DNA: e.g. an orphan being… (+12 more)

### Community 93 - "test_entry_quality_page.py"
Cohesion: 0.36
Nodes (10): _minimal_payload(), Path, entry_quality.html must render the SHADOW audit payload without throwing, must…, The funnel panel must show actual_trades unchanged and labelled as such - it…, run(), test_funnel_never_claims_actual_trades_changed(), test_insufficient_sample_renders_as_insufficient_not_a_number(), test_live_vs_shadow_table_labels_shadow_as_hypothetical() (+2 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (11): cmd_backup(), cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), env_value(), is_running() (+3 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "pytest"
Cohesion: 0.14
Nodes (18): _dna_is_immutable(), ImmutableRecordError, listens_for, RuntimeError, _snapshot_is_undeletable(), _snapshot_is_write_once(), _alembic(), Immutable snapshots (phase 32), death & generation rollover (phase 31). (+10 more)

### Community 97 - "test_backtesting.py"
Cohesion: 0.20
Nodes (16): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+8 more)

### Community 98 - "logging.py"
Cohesion: 0.09
Nodes (31): configure_logging(), get_logger(), _install_stdlib_redaction(), factory(), _is_secret_key(), Structured logging setup. All log lines are JSON (when `log_json=True`) and…, Scrub every stdlib/uvicorn/library log record at creation time. A record…, _redact() (+23 more)

### Community 99 - "test_promotion_evidence.py"
Cohesion: 0.24
Nodes (16): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, test_criteria_come_from_settings(), good(), parametrize (+8 more)

### Community 100 - "test_decision_loop.py"
Cohesion: 0.24
Nodes (21): DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, run_decision_cycle(), _context(), _make_agent(), asyncio, Integration test for the per-candle agent decision loop: entry, exit, and the…, Phase 4.0 characterization gap: the day-rollover reset (day_start_equity,… (+13 more)

### Community 101 - "time"
Cohesion: 0.12
Nodes (11): Any, BaseModel, field_validator, Hyperliquid WebSocket market-data stream (spec phase 17). Primary real-time…, The REST wire format MarketDataService.upsert_candles consumes., WsCandle, WsStats, Controlled Ollama credential reload for the long-running worker.… (+3 more)

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "load_rows"
Cohesion: 0.12
Nodes (19): load_rows(), _load_rows(), AsyncSession, datetime, Public entry point for callers (e.g. the CSV export route) that need row-level…, Returns (scored rows, total_signals_considered, unscorable_count)., compute_features(), feature_row_at_or_before() (+11 more)

### Community 104 - "3. Actual coupling problems found (the real targets)"
Cohesion: 0.17
Nodes (11): Submits an order and returns its fill result. Implementations MUST be…, 3. Actual coupling problems found (the real targets), 2. PositionCloseSettler review, 3. Dependency-direction map, 4-5. Test results, Full test suite (both phases combined), Phase 3 — Boundary verification and hardening (no `decision_loop.py`), Phase 4 — CLOSED (+3 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "test_metrics_emission.py"
Cohesion: 0.08
Nodes (32): _escape(), _fmt(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint…, record_db_error(), render_prometheus() (+24 more)

### Community 108 - "5. Migration phases (revised order — risk-ascending, not the original numbering)"
Cohesion: 0.29
Nodes (6): 4. Proposed target architecture, 5. Migration phases (revised order — risk-ascending, not the original numbering), 6. Risks, 7. Behavior that must remain unchanged (explicit checklist for every phase), 8. What Phase 0 deliberately does not conclude, Refactor Plan — Phase 0 Analysis

### Community 109 - "test_fitness_versions.py"
Cohesion: 0.11
Nodes (25): FitnessVersionSpec, Research-only registry of named fitness formula/timing variants for offline…, Hardcoded to today's production values (fitness_engine.FitnessWeights defaults…, A smooth alternative to the hard clip(-1, 1): tanh never fully flattens two…, _signed_sqrt_tanh(), _v1_weights(), _facts(), datetime (+17 more)

### Community 110 - "paper_adapter.py"
Cohesion: 0.10
Nodes (26): ABC, ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+18 more)

### Community 111 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 112 - "test_reality_gap_engine.py"
Cohesion: 0.12
Nodes (28): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…, compute_full_reality_gap_chain(), persist_reality_gap_report() (+20 more)

### Community 113 - "fitness_forward.py"
Cohesion: 0.13
Nodes (22): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), _overlaps_oos_window(), datetime (+14 more)

### Community 114 - "reconstruct_fitness_at"
Cohesion: 0.22
Nodes (19): forward_window(), The production fitness an agent WOULD have had at T, from closed trades only.…, The honest (T, T+h] window: truncated at the earliest real boundary., reconstruct_fitness_at(), facts(), point(), Phase 3 tests: look-ahead protection, historical reconstruction, censoring,…, test_dead_agent_reconstruction_endstops_at_death() (+11 more)

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "Bias"
Cohesion: 0.21
Nodes (17): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, Bias (+9 more)

### Community 118 - "test_swing_points.py"
Cohesion: 0.18
Nodes (19): Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), _candles(), _path(), DataFrame, parametrize, Series, Swing-structure features: higher-high / higher-low / lower-high / lower-low,… (+11 more)

### Community 119 - "enums.py"
Cohesion: 0.09
Nodes (39): 9. Database dependency direction, bankruptcy_threshold(), create_generation(), AsyncSession, UUID, Agent + population lifecycle (spec sections 12-16, 52-53). Rules enforced here,…, Equity at or below which the agent is DEAD (default 0 = fully depleted)., Creates a new Generation row and one Agent per strategy_version_id, each… (+31 more)

### Community 121 - "hash_api_key"
Cohesion: 0.12
Nodes (12): hash_api_key(), main(), Generate an API key and the API_KEYS entry for it. python -m…, api(), _db(), fixture, test_health_returns_503_when_the_database_is_down(), api() (+4 more)

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "_build_advisory_criteria"
Cohesion: 0.53
Nodes (6): _build_advisory_criteria(), _latest_adversarial_report(), _latest_regime_validation_report(), AsyncSession, UUID, Tightens `min_fitness_improvement` for FRAGILE/UNSTABLE regime classification —…

### Community 135 - "ExecutionRequest"
Cohesion: 0.22
Nodes (8): ExecutionRequest, ExecutionResult, asyncio, Paper mode must NEVER send real orders; live mode must require explicit…, test_duplicate_client_order_id_is_rejected_not_double_filled(), test_live_adapter_refuses_to_place_orders_when_not_implemented(), test_paper_adapter_applies_fees_and_slippage(), test_paper_adapter_never_makes_network_calls()

### Community 136 - "numpy"
Cohesion: 0.16
Nodes (14): ShadowAgentInput, current_fitness(), _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, (production compute_fitness, max drawdown) fed the way fitness_service feeds… (+6 more)

### Community 137 - "test_breeding.py"
Cohesion: 0.24
Nodes (13): _preserve_family_distribution(), Biases fresh-DNA injection toward minority families apply_diversity_pressure…, asyncio, Generation-breeding orchestrator: survivor selection and the population-…, Without the cap, 5 high-fitness MOMENTUM agents would take every survivor slot…, _seed_generation(), test_breeding_accepts_diversity_pressure_signals_without_error(), test_breeding_enforces_diversity_floor() (+5 more)

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 140 - "entry_quality.py"
Cohesion: 0.27
Nodes (11): export_rows(), Audit-export field list, per the dashboard spec: timestamp, agent_id,…, entry_quality_audit(), entry_quality_export(), AsyncSession, datetime, get, UUID (+3 more)

### Community 141 - "test_correlation.py"
Cohesion: 0.08
Nodes (57): _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity(), _jaccard(), DNA-structural similarity — extends app/evolution/diversity.py's…, Resolved indicator specs (EMA(20) and EMA(50) are DIFFERENT features) plus the… (+49 more)

### Community 142 - "set_kill_switch"
Cohesion: 0.20
Nodes (11): get_flags(), health(), KillSwitchRequest, AsyncSession, BaseModel, get, Request, Backward-compatible summary (the rich picture is /api/system/status). No… (+3 more)

### Community 143 - "test_adversarial_service.py"
Cohesion: 0.36
Nodes (8): asyncio, DataFrame, UUID, Wires run_adversarial_suite (previously uncalled anywhere outside its own test)…, _seed_strategy_version(), test_run_and_persist_adversarial_suite_persists_a_report(), test_run_and_persist_adversarial_suite_raises_for_unknown_strategy_version(), _trending_candles()

### Community 144 - "propose_candidate"
Cohesion: 0.22
Nodes (8): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _AlwaysFailsClient, asyncio, Duck-typed stand-in for OllamaClient — raises immediately rather than going…, test_propose_candidate_returns_none_on_ollama_rate_limit(), test_propose_candidate_returns_none_on_ollama_timeout(), Exception

### Community 146 - "code_only"
Cohesion: 0.18
Nodes (10): code_only(), Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, _sources(), test_every_http_post_in_the_codebase_targets_an_allowlisted_endpoint_or_is_internal(), test_no_module_contains_order_sending_signing_or_wallet_code(), test_the_scanner_itself_catches_real_violations_but_ignores_documentation(), For --cluster-only (+2 more)

### Community 150 - "KeyRefresher"
Cohesion: 0.20
Nodes (4): KeyRefresher, Safe to call from a signal handler., test_key_refresher_never_raises_into_the_trading_loop(), test_key_refresher_periodic_and_forced()

### Community 151 - "report_trade_quality.py"
Cohesion: 0.33
Nodes (9): _flat(), getattr_r(), main(), _mean(), _median(), _pct(), READ-ONLY trade-quality report (Reports B, C, D): entry quality, exit quality,…, Group value as a plain string ('SIDE.SHORT' enum repr -> 'SHORT', None -> '-'). (+1 more)

### Community 152 - "test_cooldown_limits.py"
Cohesion: 0.38
Nodes (9): _dna(), Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe(), test_max_trades_per_day_stops_new_entries_and_resets_next_utc_day(), test_no_cooldown_configured_allows_immediate_reentry(), _trade_round_trip() (+1 more)

### Community 153 - "cycle.py"
Cohesion: 0.36
Nodes (6): is_population_extinct(), _ensure_features_persisted(), make_cycle_id(), process_candle(), One trading cycle per *confirmed* candle (spec section 61's pipeline):…, Processes ONE confirmed candle. Returns None if it was already completed.

### Community 154 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.36
Nodes (7): _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., One row of headline aggregates, computed identically against either engine, for…, upgrade_schema()

### Community 155 - "helpers_agents.py"
Cohesion: 0.11
Nodes (38): ComparisonOperator, CooldownConfig, IndicatorConfig, PositionSizing, BaseModel, Enum, field_validator, str (+30 more)

### Community 156 - "test_fitness_v2.py"
Cohesion: 0.13
Nodes (22): FitnessWeights, Weights are configuration, not code: FITNESS_W_* environment variables., The weights of a recorded snapshot (fitness_scores.weights_used), falling back…, weights_from_recorded(), base(), Composite fitness (spec phase 30): not raw PnL, bounded, configurable,…, BUG: FitnessInputs.daily_consistency is computed and passed by every caller…, test_consistency_score_blends_walk_forward_and_daily_when_both_available() (+14 more)

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1306 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `sqlalchemy`, `test_reality_gap_normalisation.py`, `MarketDataService`, `test_api_security.py`, `Settings`, `entry_quality_audit.py`, `_process_agent_inner`, `MarketCandle`, `pipeline.py`, `run_backtest`, `set_kill_switch`, `RiskDecision`, `test_stops_trailing.py`, `routes/status.py`, `requested_notional`, `test_worker_cycle.py`, `test_postgres_concurrency.py`, `test_council_failclosed.py`, `cycle.py`, `test_cooldown_limits.py`, `helpers_agents.py`, `test_fitness_v2.py`, `test_ollama_failure_modes.py`, `accounting.py`, `test_oos_lockbox.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `test_shadow_mode.py`, `Trade`, `test_entry_quality_audit.py`, `database.py`, `Side`, `test_regime_validation_engine.py`, `PaperExecutionAdapter`, `test_worker_fencing.py`, `StrategyStage`, `OllamaClient`, `below_min_order_notional`, `service.py`, `market_data_service.py`, `seal_epoch`, `config.py`, `Decision`, `test_council_deadline.py`, `HyperliquidClient`, `test_funding.py`, `test_untestable_agents.py`, `test_adversarial_extended.py`, `Agent`, `tradability.py`, `Position`, `make_agents`, `conftest.py`, `test_champion_challenger_service.py`, `1. Live execution flow (complete trace)`, `pytest`, `logging.py`, `test_promotion_evidence.py`, `test_decision_loop.py`, `load_rows`, `3. Actual coupling problems found (the real targets)`, `test_metrics_emission.py`, `5. Migration phases (revised order — risk-ascending, not the original numbering)`, `paper_adapter.py`, `env.py`, `fitness_forward.py`, `Bias`, `enums.py`, `hash_api_key`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `breeding.py`, `sqlalchemy`, `test_reality_gap_normalisation.py`, `entry_quality_audit.py`, `_process_agent_inner`, `test_breeding.py`, `pipeline.py`, `test_correlation.py`, `run_backtest`, `RiskDecision`, `test_decision_loop_characterization.py`, `routes/status.py`, `test_postgres_concurrency.py`, `cycle.py`, `test_agent_lifecycle.py`, `helpers_agents.py`, `research_exit_payoff.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `routes/evolution.py`, `Trade`, `database.py`, `Side`, `test_regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `test_worker_fencing.py`, `StrategyStage`, `below_min_order_notional`, `test_as_of_boundaries.py`, `compute_and_persist_agent_fitness`, `test_untestable_agents.py`, `tradability.py`, `Position`, `make_agents`, `evaluate_fitness_versions.py`, `shadow_rows_for_generation`, `test_champion_challenger_service.py`, `1. Live execution flow (complete trace)`, `test_promotion_evidence.py`, `test_decision_loop.py`, `load_rows`, `test_reality_gap_engine.py`, `enums.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `StrategyDNA` connect `StrategyDNA` to `breeding.py`, `sqlalchemy`, `_process_agent_inner`, `indicators.py`, `test_breeding.py`, `pipeline.py`, `run_backtest`, `test_correlation.py`, `RiskDecision`, `test_adversarial_service.py`, `MarketRegime`, `requested_notional`, `test_worker_cycle.py`, `test_council_failclosed.py`, `RuleSet`, `helpers_agents.py`, `test_agent_lifecycle.py`, `test_stage_metrics.py`, `BacktestResult`, `accounting.py`, `test_oos_lockbox.py`, `test_frozen_oos_epoch.py`, `analyze_trade`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `Side`, `test_regime_validation_engine.py`, `StrategyStage`, `below_min_order_notional`, `test_as_of_boundaries.py`, `market_data_service.py`, `Experiment Guide`, `compute_and_persist_agent_fitness`, `test_untestable_agents.py`, `test_adversarial_extended.py`, `test_dna_runtime_coverage.py`, `Position`, `make_agents`, `test_champion_challenger_service.py`, `1. Live execution flow (complete trace)`, `test_backtesting.py`, `test_decision_loop.py`, `test_reality_gap_engine.py`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 106 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 106 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._