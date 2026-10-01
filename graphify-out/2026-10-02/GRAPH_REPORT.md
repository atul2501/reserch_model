# Graph Report - reserch_model  (2026-09-30)

## Corpus Check
- 340 files · ~258,655 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .service 4, (none) 3, .ini 2)

## Summary
- 4239 nodes · 15825 edges · 171 communities (134 shown, 37 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2185 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e2bd42f3`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Heartbeat
- Base
- test_reality_gap_normalisation.py
- _Sheet
- MarketDataService
- get_settings
- ExecutionRequest
- entry_quality_audit.py
- test_ws_client.py
- Order
- indicators.py
- MarketCandle
- test_evolution_pipeline.py
- run_backtest
- test_stops_trailing.py
- RiskDecision
- AgentStatus
- runtime_status.py
- MarketRegime
- test_ollama_schema_normalization.py
- requested_notional
- Multi-Week Research Readiness Report
- test_worker_cycle.py
- lease.py
- test_council_failclosed.py
- compute_features
- RuleSet
- test_agent_lifecycle.py
- StrategyDNA
- test_regime_validation_engine.py
- test_ollama_failure_modes.py
- strategy_regime.py
- experiment_runner.py
- test_shadow_fitness_synthetic.py
- Side
- test_promotion_service.py
- pipeline.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- test_evolution_gate_and_champions.py
- compute_fitness
- routes/correlation.py
- CouncilDecision
- test_shadow_mode.py
- families.py
- test_lifecycle_ports.py
- test_entry_quality_audit.py
- AIClientPort
- sqlalchemy
- registry.py
- regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- test_worker_fencing.py
- StrategyStage
- OllamaClient
- below_min_order_notional
- analytics_store.py
- Bias
- promotion_service.py
- 24-Hour Data Validation & Next-Phase Execution — Research Report
- seal_epoch
- Settings
- test_decision_volume.py
- test_council_deadline.py
- get_adversarial_report_history
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- Local Migration
- fitness_service.py
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- agent_dna
- test_analytics_migration.py
- test_migrations.py
- dashboard_service.py
- test_dna_runtime_coverage.py
- secret_scan.py
- tradability.py
- get_latest_regime_validation
- make_agents
- evaluate_fitness_versions.py
- conftest.py
- shadow_rows_for_generation
- test_champion_challenger_service.py
- report_agent_evidence.py
- test_fitness_edge_cases.py
- test_entry_quality_page.py
- run.sh
- test_dashboard_js.py
- pytest
- test_backtesting.py
- logging.py
- test_promotion_evidence.py
- Agent
- WsCandle
- ImmutableAnalyticsRecordError
- _trade
- ExecutionEngine
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- cycle.py
- 5. Migration phases (revised order — risk-ascending, not the original numbering)
- fitness_forward.py
- OrderStatus
- env.py
- reality_gap_engine.py
- schemas/champion_challenger.py
- test_fitness_forward.py
- graphify reference: extra exports and benchmark
- schemas/reality_gap.py
- alembic_config
- TakeoverEngine
- enums.py
- constraints.py
- graphify reference: query, path, explain
- champion_challenger_service.py
- purge_secrets_from_history.sh
- EpochIntegrityError
- schemas/adversarial.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- test_config_audit.py
- correlation_service.py
- list_challengers
- test_adversarial_service.py
- schemas/regime_validation.py
- graphify reference: GitHub clone and cross-repo merge
- test_no_live_orders.py
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md
- Trade
- FitnessWeights
- _alembic
- _Ref
- graphify reference: transcribe video and audio

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 251 edges
2. `PaperExecutionAdapter` - 190 edges
3. `Agent` - 178 edges
4. `make_agents()` - 178 edges
5. `make_dna()` - 172 edges
6. `StrategyDNA` - 159 edges
7. `Side` - 153 edges
8. `StrategyVersion` - 140 edges
9. `Trade` - 136 edges
10. `make_context()` - 133 edges

## Surprising Connections (you probably didn't know these)
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py
- `5. AI council as *context*, not oracle` --references--> `Decision`  [INFERRED]
  docs/architecture.md → backend/app/models/decision.py
- `Local` --references--> `Side`  [INFERRED]
  POSTGRESQL_MIGRATION_REPORT.md → backend/app/models/enums.py
- `From the CLI` --references--> `render_comparison()`  [INFERRED]
  EXPERIMENT_GUIDE.md → backend/app/research/experiment_runner.py

## Import Cycles
- None detected.

## Communities (171 total, 37 thin omitted)

### Community 1 - "Base"
Cohesion: 0.09
Nodes (61): Base, AdversarialTestReport, Persisted adversarial-suite results — insert-only, one row per run, so…, Derived analytical tables (the analytics foundation). These tables store ONLY…, StrategyRegimeMatrix, datetime, Shared mixins for ORM models., A timezone-aware DateTime that stays timezone-aware on SQLite too. Postgres's… (+53 more)

### Community 2 - "test_reality_gap_normalisation.py"
Cohesion: 0.19
Nodes (17): comparability(), compute_live_stage_metrics(), _max_drawdown(), Computes the same 4 base metrics from actual Trade/Agent history for every…, Peak-to-trough drawdown of the account built from `starting` plus each closed…, Whether the two stages can be used as RELIABLE evidence against each other.…, _live(), Reality gap (spec phase 20): stages are compared per unit of time, and only… (+9 more)

### Community 3 - "_Sheet"
Cohesion: 0.17
Nodes (11): _build(), _cell_value(), _fetch(), _flatten(), _plain(), Any, datetime, Nested dicts become dotted columns; lists become JSON text. (+3 more)

### Community 4 - "MarketDataService"
Cohesion: 0.06
Nodes (34): 10. Market-data dependency direction, Read/write helpers for durable system flags (kill switch, data-gap halt)., set_flag(), HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context. (+26 more)

### Community 5 - "get_settings"
Cohesion: 0.03
Nodes (88): _acquire_stream_slot(), One concurrent-SSE slot; release() is idempotent (generator finally + response…, _StreamSlot, get_settings(), Centralized application configuration. Every environment-dependent value in the…, publish_status(), authenticate(), _client_id() (+80 more)

### Community 6 - "ExecutionRequest"
Cohesion: 0.11
Nodes (32): ABC, Enum, str, TradingMode, ExecutionRequest, Execution engine abstraction (spec section 19). Every trading mode…, HyperliquidLiveExecutionAdapter, Hyperliquid LIVE execution adapter — spec sections 5/19/39/40. STATUS:… (+24 more)

### Community 7 - "entry_quality_audit.py"
Cohesion: 0.08
Nodes (49): build_audit(), _calibration(), _drift(), export_rows(), _feature_importance(), _funnel(), _group_breakdown(), _hold_time_audit() (+41 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.07
Nodes (41): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, test_ws_reconnects_are_counted(), candle(), FakeServer, make() (+33 more)

### Community 9 - "Order"
Cohesion: 0.06
Nodes (68): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+60 more)

### Community 10 - "indicators.py"
Cohesion: 0.07
Nodes (65): jitter(), mutate(), _mutate_indicator_period(), _mutate_ruleset_thresholds(), Random, DNA mutation (spec section 25). Produces a new, independently-valid StrategyDNA…, Changes one declared indicator's period AND rewrites every rule that referenced…, _atr() (+57 more)

### Community 11 - "MarketCandle"
Cohesion: 0.09
Nodes (53): active_flags(), Returns {flag_name: reason} for every currently-active flag., MarketCandle, clock_after_bar(), FakeHyperliquid, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format. (+45 more)

### Community 12 - "test_evolution_pipeline.py"
Cohesion: 0.12
Nodes (29): derive_seed(), A stable 31-bit seed from arbitrary parts, e.g. (research_seed, epoch_id,…, evaluate_gates(), AsyncSession, datetime, Schedule + readiness gates. Returns (run?, reason_if_not, latest_generation)., _record_skip(), ResearchReport (+21 more)

### Community 13 - "run_backtest"
Cohesion: 0.09
Nodes (58): drop_random_candles(), duplicate_random_candles(), Re-emits `fraction` of bars twice in a row (duplicate feed messages)., Removes `fraction` of bars at random (missing-candle feed gaps): the indicator…, DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), DataFrame (+50 more)

### Community 14 - "test_stops_trailing.py"
Cohesion: 0.20
Nodes (26): advance_extremes(), Bar, bar_time(), evaluate_bar(), PositionLevels, ProtectiveTrigger, datetime, Open-position management on every confirmed bar (spec phases 8-11). Order of… (+18 more)

### Community 15 - "RiskDecision"
Cohesion: 0.14
Nodes (38): backtest_risk_check(), Routes backtest/adversarial position sizing through the real…, Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every… (+30 more)

### Community 16 - "AgentStatus"
Cohesion: 0.12
Nodes (26): AgentStatus, _build_scenario(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, _run_fixed_scenario() (+18 more)

### Community 17 - "runtime_status.py"
Cohesion: 0.09
Nodes (29): _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, Request, API-process counters + worker-published counters + DB-derived gauges…, Server-Sent Events: a `status` event every `interval` seconds (worker… (+21 more)

### Community 18 - "MarketRegime"
Cohesion: 0.11
Nodes (38): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), MarketRegime, _bar_regimes(), DataFrame, parametrize (+30 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.07
Nodes (63): CouncilAnalysis, One analyst's structured response feeding into a CouncilDecision., _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json() (+55 more)

### Community 20 - "requested_notional"
Cohesion: 0.13
Nodes (28): 12. Live/backtest duplication, build_sizing_result(), normalize_method(), Position sizing (spec phase 6): pure, deterministic, unit-tested. Supported DNA…, Fractional distance from entry to the protective stop (matches the stop…, What the DNA wants, before risk clamps. Never negative., requested_notional(), SizingResult (+20 more)

### Community 21 - "Multi-Week Research Readiness Report"
Cohesion: 0.18
Nodes (10): 10. FINAL READINESS CHECK, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 7. RESEARCH DASHBOARD, 9. RECOVERY TEST — real, on the actual dev environment, Known limitations, Multi-Week Research Readiness Report (+2 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.13
Nodes (26): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), test_database_errors_are_counted_when_a_cycle_fails_on_the_database(), usefixtures, test_paper_cycles_with_a_council_only_ever_touch_read_endpoints() (+18 more)

### Community 23 - "lease.py"
Cohesion: 0.08
Nodes (35): db_now(), _insert_fn(), LeaseKeeper, LeaseLost, LeaseState, new_owner_id(), AsyncSession, RuntimeError (+27 more)

### Community 24 - "test_council_failclosed.py"
Cohesion: 0.09
Nodes (45): _failure_bucket(), AsyncSession, run_council_cycle(), council_on(), fixture, Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, _run(), test_a_verdict_for_another_candle_is_never_applied() (+37 more)

### Community 25 - "compute_features"
Cohesion: 0.09
Nodes (52): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _atr(), _bollinger(), compute_features(), _ema(), _macd(), minimal_context() (+44 more)

### Community 26 - "RuleSet"
Cohesion: 0.08
Nodes (55): _gate_candidates(), gate(), Every feature key `MarketContext.flat_features()` can emit., static_feature_names(), Condition, BaseModel, A single testable condition against a named feature/indicator output, e.g.…, A set of conditions combined with AND/OR logic. Kept deliberately simple… (+47 more)

### Community 27 - "test_agent_lifecycle.py"
Cohesion: 0.18
Nodes (21): AgentAlreadyDeadError, bankruptcy_threshold(), mark_dead(), RuntimeError, Equity at or below which the agent is DEAD (default 0 = fully depleted)., Updates equity, peak equity, drawdown, and milestone tracking. Never call this…, Permanently marks an agent dead. Idempotent: calling twice on an already-dead…, update_equity() (+13 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.10
Nodes (51): _blend(), crossover(), Random, DNA crossover (spec section 25): combine two successful parents' DNA into one…, dna_distance(), A simple, interpretable [0, 1] distance: 0 = identical family and near-…, ComparisonOperator, IndicatorConfig (+43 more)

### Community 29 - "test_regime_validation_engine.py"
Cohesion: 0.08
Nodes (33): BacktestResult, BacktestTrade, compute_missed_trade_stats(), MissedTradeStats, persist_backtest_metrics(), persist_walk_forward_metrics(), UUID, Persists backtest/walk-forward/live performance into StageMetrics and compares… (+25 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.06
Nodes (56): counter_value(), OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError (+48 more)

### Community 31 - "strategy_regime.py"
Cohesion: 0.08
Nodes (39): _as_trade_rows(), bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci() (+31 more)

### Community 32 - "experiment_runner.py"
Cohesion: 0.11
Nodes (36): experiment_diff(), Baseline-vs-candidate diff for two experiment_ids (see…, Experiment, _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments() (+28 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.14
Nodes (31): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, current_fitness(), make_population(), (production compute_fitness, max drawdown) fed the way fitness_service feeds…, world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, _current_top(), _lfp_world_precisions() (+23 more)

### Community 34 - "Side"
Cohesion: 0.07
Nodes (54): Per-candle agent evaluation loop (spec sections 3/4/12/32; phases 3-12, 39).…, stop_price(), take_profit_price(), compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +… (+46 more)

### Community 35 - "test_promotion_service.py"
Cohesion: 0.25
Nodes (17): summary(), EvolutionEventType, str, TradingMode, EvolutionEvent, test_evolution_endpoints(), _agent_with_fitness(), _passing_metrics() (+9 more)

### Community 36 - "pipeline.py"
Cohesion: 0.06
Nodes (68): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame (+60 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.10
Nodes (37): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, evaluate_oos_once(), OosAlreadyConsumedError (+29 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.12
Nodes (27): ShadowAgentInput, TradeEvidence, _fake_backtest(), make_trades(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-… (+19 more)

### Community 39 - "analyze_trade"
Cohesion: 0.17
Nodes (28): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+20 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.08
Nodes (53): AdversarialReport, _clip01(), compute_robustness_score(), inject_abnormal_volume(), inject_extreme_move(), inject_gap(), inject_liquidity_reduction(), inject_stale_period() (+45 more)

### Community 41 - "test_evolution_gate_and_champions.py"
Cohesion: 0.13
Nodes (28): BreedingResult, NoValidCandidatesError, AsyncSession, Random, RuntimeError, UUID, Ranks every agent in `generation_number` by `Agent.fitness` (falling back to…, Selects survivors from `generation_number`, breeds children via… (+20 more)

### Community 42 - "compute_fitness"
Cohesion: 0.16
Nodes (27): _clip(), compute_fitness(), FitnessInputs, FitnessResult, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,…, [-1, 1]. A 0% win rate over real trades is the WORST score (-1), not neutral;… (+19 more)

### Community 43 - "routes/correlation.py"
Cohesion: 0.23
Nodes (14): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+6 more)

### Community 44 - "CouncilDecision"
Cohesion: 0.07
Nodes (41): _decision(), history(), latest(), AsyncSession, get, events(), experiments(), generations() (+33 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.13
Nodes (24): L2Book, parse_book(), Volume-weighted fill of `quantity` across `levels`. Returns (avg_price,…, One (book, book-after-latency) pair shared by all agents within the TTL., ShadowExecutionAdapter, walk_book(), book(), FakeBook (+16 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "test_lifecycle_ports.py"
Cohesion: 0.14
Nodes (18): PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult, _AlwaysZeroBadDebtSettler, _FakeSettlement, Phase 2 dependency-boundary regression: app/agents/lifecycle.py must not import… (+10 more)

### Community 48 - "test_entry_quality_audit.py"
Cohesion: 0.14
Nodes (26): _add_trade(), datetime, UUID, Entry Quality Model V1 - SHADOW AUDIT tests (spec: Phase-4 forensic audit…, The funnel's actual_trades count must equal what's really in the trades table…, Purely a read/aggregation service - Trade.net_pnl and count must be bit-for-bit…, Fewer than MIN_SAMPLE trades in a family/regime cell must report None / a…, A trade whose signal fired inside the model's own train+val window must never… (+18 more)

### Community 49 - "AIClientPort"
Cohesion: 0.08
Nodes (31): 11. AI/Ollama dependency direction, AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), AICallStats (+23 more)

### Community 50 - "sqlalchemy"
Cohesion: 0.06
Nodes (54): list_agents(), _to_summary(), Entry Quality Model V1 - SHADOW AUDIT API. Read-only; every response here is a…, exit_analytics(), _histogram(), AsyncSession, datetime, get (+46 more)

### Community 51 - "registry.py"
Cohesion: 0.15
Nodes (23): get_or_create_epoch(), The ACTIVE sealed epoch if there is one (whatever `candles` the caller happens…, fail_abandoned_experiments(), finish_experiment(), new_experiment_id(), AsyncSession, UUID, Experiment registry (spec phase 23): every research run is a reproducible,… (+15 more)

### Community 52 - "regime_validation_engine.py"
Cohesion: 0.15
Nodes (25): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+17 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.15
Nodes (23): PaperExecutionAdapter, _run_live(), _levered_dna(), Margin & liquidation (spec phase 9): explicit margin model; leverage is a real…, test_dead_agents_are_never_processed_again_or_revived(), test_leverage_multiplies_notional_but_margin_stays_within_the_cap(), test_liquidation_closes_the_position_charges_penalty_and_can_kill_the_agent(), test_notional_never_exceeds_available_margin_times_leverage() (+15 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (36): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+28 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.21
Nodes (22): _agent(), _candle(), _migration_module(), _order(), _position(), Impossible states cannot be written (spec phase 26): the DATABASE rejects them,…, _rejects(), test_a_pending_order_is_by_definition_unfilled() (+14 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.21
Nodes (17): champion_evidence_ok(), estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, _samples() (+9 more)

### Community 57 - "test_worker_fencing.py"
Cohesion: 0.11
Nodes (27): _seed_always_long_population(), _frame(), _funding(), DataFrame, parametrize, LIVE (paper, through the real worker cycle) vs BACKTEST parity (spec phases 5,…, Guard against a vacuous parity suite: across the scenarios stops, signal exits…, test_parity_scenarios_exercise_more_than_one_exit_reason() (+19 more)

### Community 58 - "StrategyStage"
Cohesion: 0.21
Nodes (22): evaluate_and_promote(), Evaluates whether `strategy_version_id`'s metrics at `stage` justify promoting…, StrategyStage, One performance snapshot for a StrategyVersion at a given pipeline stage.…, StageMetrics, add_promotion_evidence(), The full evidence set the promotion gate demands beyond PnL: adversarial…, test_min_stage_days_is_honoured_including_zero() (+14 more)

### Community 59 - "OllamaClient"
Cohesion: 0.06
Nodes (31): Ollama-driven strategy research (spec section 26). Ollama proposes candidate…, OllamaClient, OllamaKeyHealth, Returns (key, key_index). key_index is the position in OLLAMA_API_KEYS (never…, Safe operational state: positions/statuses only, never secrets., True if at least one credential could serve a request right now (or no…, Re-read credentials from settings WITHOUT a restart. A key whose value is…, Cooldown for a 429: honour Retry-After (seconds), else an escalating default… (+23 more)

### Community 60 - "below_min_order_notional"
Cohesion: 0.09
Nodes (26): below_min_order_notional(), True when an ENTRY of `notional` at `price` would be refused by the exchange…, deterministic(), fixture, test_check_mirrors_the_adapter_lot_rounding(), 10. Required characterization/parity tests before implementation, 11. Proposed implementation phases (NOT started - awaiting explicit approval), 12. What should explicitly remain duplicated (source of truth: existing production behavior) (+18 more)

### Community 61 - "analytics_store.py"
Cohesion: 0.08
Nodes (55): _bar_ms(), _components_of(), _is_uuid(), _ms(), AsyncSession, Bar, datetime, DB I/O for the analytics foundation. The ONLY module that writes, and it writes… (+47 more)

### Community 62 - "Bias"
Cohesion: 0.09
Nodes (45): _council_context(), apply_judge(), compute_consensus(), Deterministic consensus engine (spec section 9). Never produced by an LLM —…, A "strong" consensus is a lead of at least `consensus_margin` votes over the…, Overlays a judge's ruling onto a weak-consensus result. The risk engine…, tally_votes(), combine() (+37 more)

### Community 63 - "promotion_service.py"
Cohesion: 0.17
Nodes (16): compute_reality_gap(), latest_stage_metrics(), _metric_value(), pct_change(), AsyncSession, _rate(), Raw column, or a derived per-unit metric. Derived ones are what make a 14-day…, Pulls the most recent StageMetrics row per stage and returns per-metric {from,… (+8 more)

### Community 64 - "24-Hour Data Validation & Next-Phase Execution — Research Report"
Cohesion: 0.12
Nodes (16): 10. FINAL STATUS, 24-Hour Data Validation & Next-Phase Execution — Research Report, 4. 24-HOUR BASELINE, 5. EXIT ANALYSIS, 6. EXIT EXPERIMENT PLAN, 7. POSTGRESQL MIGRATION PLAN, 9. ACCEPTANCE CRITERIA, Backup strategy (+8 more)

### Community 65 - "seal_epoch"
Cohesion: 0.16
Nodes (18): _build_epoch(), count_confirmed_candles(), fingerprint_frame(), get_active_epoch(), load_epoch_candles(), _oos_fingerprint(), AsyncSession, DataFrame (+10 more)

### Community 66 - "Settings"
Cohesion: 0.07
Nodes (23): 3. Current cross-community bridge nodes, field_validator, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, Relative SQLite paths resolve against backend/ (not the CWD) and their folder…, All gates required by spec section 40 before ANY live order. This does not…, resolve_sqlite_url(), Settings, AbuseGuard (+15 more)

### Community 67 - "test_decision_volume.py"
Cohesion: 0.15
Nodes (23): count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,…, Deletes no-op rows older than `cutoff` in batches. Returns rows deleted. (+15 more)

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
Cohesion: 0.11
Nodes (17): 1. Running a baseline vs. candidate experiment, 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Custom configs (+9 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "Local Migration"
Cohesion: 0.08
Nodes (20): model_validator, A council that cannot possibly reach quorum, or that may outlive its own…, PostgreSQL is required for research, paper, shadow and production — every real…, Three processes share the database. If their pools alone could exceed the…, Future Production Migration, Local Migration, PostgreSQL Migration Guide, Prerequisites (+12 more)

### Community 74 - "fitness_service.py"
Cohesion: 0.16
Nodes (21): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+13 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.09
Nodes (31): alembic_autogenerate, alembic_migration, uvicorn's AccessFormatter unpacks record.args into 5 fields; the redaction…, test_uvicorn_access_log_formats_and_is_redacted(), _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing() (+23 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.44
Nodes (10): Agents that cannot reach the exchange minimum order at their capital are…, _run_bars(), test_agents_without_any_blocked_entries_rank_exactly_as_before(), test_blocked_entry_decision_records_the_minimum_it_missed(), test_exclusion_can_be_switched_off_to_reproduce_the_old_ranking(), test_only_the_agent_whose_entries_are_blocked_is_untestable(), test_too_few_blocked_entries_is_not_enough_to_call_an_agent_untestable(), test_untestable_agent_is_never_selected_as_a_survivor_even_with_the_top_fitness() (+2 more)

### Community 78 - "agent_dna"
Cohesion: 0.38
Nodes (10): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), AsyncSession, get, UUID (+2 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.16
Nodes (12): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+4 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.26
Nodes (12): _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs(), test_downgrade_then_upgrade_round_trips(), test_drift_detector_actually_detects_drift() (+4 more)

### Community 81 - "dashboard_service.py"
Cohesion: 0.16
Nodes (26): _agent_age_days(), _agent_group_stats(), get_agent_metrics(), get_champions_analysis(), get_equity_curve(), get_fitness_components(), get_overview(), get_ranking_stability() (+18 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.23
Nodes (10): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_nested_dna_field_is_covered_by_a_named_behaviour_test() (+2 more)

### Community 83 - "secret_scan.py"
Cohesion: 0.31
Nodes (9): _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files(), test_flags_real_looking_secrets_without_echoing_them(), test_placeholders_and_empty_values_pass() (+1 more)

### Community 84 - "tradability.py"
Cohesion: 0.22
Nodes (12): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, Which agents can be TESTED at their capital (Option D of the min-notional…, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids() (+4 more)

### Community 85 - "get_latest_regime_validation"
Cohesion: 0.60
Nodes (5): get_latest_regime_validation(), get_regime_validation_history(), AsyncSession, get, UUID

### Community 86 - "make_agents"
Cohesion: 0.12
Nodes (59): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), cycle(), make_agents(), make_context(), make_dna() (+51 more)

### Community 87 - "evaluate_fitness_versions.py"
Cohesion: 0.12
Nodes (27): AgentFacts, The immutable facts of an agent needed at any T (no mutable state)., _bucket_report(), _capture_rate(), _evaluate_version(), _future_for(), _future_profit_factor(), _grid_as_of_points() (+19 more)

### Community 88 - "conftest.py"
Cohesion: 0.12
Nodes (20): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+12 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.22
Nodes (12): rank_correlation(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat() (+4 more)

### Community 90 - "test_champion_challenger_service.py"
Cohesion: 0.21
Nodes (28): advance_pipeline_stage(), Attempts to move `strategy_version_id` one step forward in the pipeline.…, asyncio, datetime, ChampionChallengerEngine: the Candidate -> Validation -> Challenger ->…, This is the one place advance_pipeline_stage calls evaluate_and_promote — no…, A FRAGILE classification must never be an automatic block — it doubles the…, Regression guard: champion_status is nullable and most versions never had it… (+20 more)

### Community 91 - "report_agent_evidence.py"
Cohesion: 0.06
Nodes (41): argparse, main(), migrate(), One-off: copy every row from the live Postgres database into a fresh SQLite…, _aggregate_summary(), main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,… (+33 more)

### Community 92 - "test_fitness_edge_cases.py"
Cohesion: 0.15
Nodes (17): capped_profit_factor(), gross_win / gross_loss; the no-loss case is capped, and no evidence at all (no…, Fraction of windows that were profitable — a simple, auditable stand-in for…, inp(), Fitness edge cases (spec phase 17): zero is a real value, idleness is not…, test_a_dead_agent_pays_a_death_penalty(), test_an_idle_agent_earns_no_survival_credit_and_is_penalised(), test_no_losing_trade_is_a_capped_infinite_profit_factor_not_neutral() (+9 more)

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
Cohesion: 0.39
Nodes (7): _decisions(), _orders(), Minimum order notional is enforced at DECISION time, not discovered a bar later…, test_entry_at_the_minimum_still_creates_a_pending_order(), test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason(), test_the_minimum_can_be_disabled_like_at_the_adapter(), pytest

### Community 97 - "test_backtesting.py"
Cohesion: 0.18
Nodes (18): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+10 more)

### Community 98 - "logging.py"
Cohesion: 0.06
Nodes (46): asyncio, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory(), _is_secret_key() (+38 more)

### Community 99 - "test_promotion_evidence.py"
Cohesion: 0.24
Nodes (16): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, test_criteria_come_from_settings(), good(), parametrize (+8 more)

### Community 100 - "Agent"
Cohesion: 0.07
Nodes (57): decision_id_for(), _load_funding(), protect_open_positions(), AsyncSession, DataFrame, UUID, Deterministic decision id: one per (agent, candle). Combined with the unique…, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed… (+49 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "ImmutableAnalyticsRecordError"
Cohesion: 0.50
Nodes (5): _ffp_is_write_once(), _ffp_never_delete(), ImmutableAnalyticsRecordError, listens_for, RuntimeError

### Community 103 - "_trade"
Cohesion: 0.33
Nodes (7): _backdate_generation(), Real generations accumulate trades over real elapsed time; tests run in…, test_agent_metrics_sorts_and_paginates(), test_equity_curve_insufficient_data_outside_the_requested_range(), test_equity_curve_tracks_cumulative_pnl_and_drawdown(), test_overview_reflects_real_trades_and_champion_count(), _trade()

### Community 104 - "ExecutionEngine"
Cohesion: 0.07
Nodes (26): 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, 6. ExecutionEngine boundary, Improvements achieved, Intentional coupling (do not "fix"), Post-Refactoring Architecture Review (+18 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "cycle.py"
Cohesion: 0.07
Nodes (41): _escape(), _fmt(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint…, record_db_error(), render_prometheus() (+33 more)

### Community 108 - "5. Migration phases (revised order — risk-ascending, not the original numbering)"
Cohesion: 0.29
Nodes (6): 4. Proposed target architecture, 5. Migration phases (revised order — risk-ascending, not the original numbering), 6. Risks, 7. Behavior that must remain unchanged (explicit checklist for every phase), 8. What Phase 0 deliberately does not conclude, Refactor Plan — Phase 0 Analysis

### Community 109 - "fitness_forward.py"
Cohesion: 0.08
Nodes (42): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), _overlaps_oos_window(), datetime (+34 more)

### Community 110 - "OrderStatus"
Cohesion: 0.12
Nodes (22): close(), ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+14 more)

### Community 111 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 112 - "reality_gap_engine.py"
Cohesion: 0.16
Nodes (18): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…, compute_full_reality_gap_chain(), persist_reality_gap_report() (+10 more)

### Community 113 - "schemas/champion_challenger.py"
Cohesion: 0.60
Nodes (4): ChallengerEvaluationOut, ChampionSummaryOut, EvolutionEventOut, BaseModel

### Community 114 - "test_fitness_forward.py"
Cohesion: 0.24
Nodes (17): forward_window(), The honest (T, T+h] window: truncated at the earliest real boundary., facts(), point(), Phase 3 tests: look-ahead protection, historical reconstruction, censoring,…, test_dead_agent_reconstruction_endstops_at_death(), test_forward_window_uses_only_trades_after_t(), test_full_coverage_when_no_boundary_hits() (+9 more)

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "schemas/reality_gap.py"
Cohesion: 0.60
Nodes (4): BaseModel, RealityGapChainReportOut, RealityGapReportOut, StageTransitionGapOut

### Community 118 - "TakeoverEngine"
Cohesion: 0.40
Nodes (3): Paper engine that lets a rival worker take over the lease while the cycle is in…, TakeoverEngine, submit_order()

### Community 119 - "enums.py"
Cohesion: 0.04
Nodes (116): create_generation(), format_agent_identifier(), is_population_extinct(), AsyncSession, UUID, Agent + population lifecycle (spec sections 12-16, 52-53). Rules enforced here,…, Creates a new Generation row and one Agent per strategy_version_id, each…, record_extinction() (+108 more)

### Community 121 - "constraints.py"
Cohesion: 0.50
Nodes (3): attach_constraints(), Database-level invariants (spec phase 26). Python validation alone is not…, Idempotently attaches every CHECK and the extra partial unique indexes to…

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "champion_challenger_service.py"
Cohesion: 0.22
Nodes (14): 9. Database dependency direction, AsyncSession, Context manager for a transactional unit of work outside a request. Commits on…, session_scope(), _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report() (+6 more)

### Community 135 - "EpochIntegrityError"
Cohesion: 0.50
Nodes (4): EpochIntegrityError, NoActiveEpochError, RuntimeError, The candles now stored for a sealed epoch no longer match what was sealed…

### Community 137 - "schemas/adversarial.py"
Cohesion: 0.67
Nodes (3): AdversarialTestReportOut, BaseModel, ScenarioBreakdownOut

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 140 - "test_config_audit.py"
Cohesion: 0.29
Nodes (9): _python_sources(), No fake configuration (spec phase 29) and no dead code (phase 30). Every…, Everything goes through Settings (one validated, documented surface)., risk_engine, market_data_service and the setting used to carry three copies of…, _readers(), test_every_setting_has_a_runtime_reader_or_a_documented_reason(), test_no_module_reads_the_environment_directly(), test_removed_dead_code_stays_removed() (+1 more)

### Community 141 - "correlation_service.py"
Cohesion: 0.08
Nodes (46): _most_correlated_pair(), The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _make_candidates(), _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity() (+38 more)

### Community 142 - "list_challengers"
Cohesion: 0.31
Nodes (9): get_promotion_history(), list_challengers(), list_champions(), AsyncSession, get, UUID, Current champion per Strategy lineage — promotion is scoped per- lineage (not…, Every non-retired StrategyVersion in this lineage with its latest… (+1 more)

### Community 143 - "test_adversarial_service.py"
Cohesion: 0.36
Nodes (8): asyncio, DataFrame, UUID, Wires run_adversarial_suite (previously uncalled anywhere outside its own test)…, _seed_strategy_version(), test_run_and_persist_adversarial_suite_persists_a_report(), test_run_and_persist_adversarial_suite_raises_for_unknown_strategy_version(), _trending_candles()

### Community 144 - "schemas/regime_validation.py"
Cohesion: 0.67
Nodes (3): BaseModel, RegimeStatsOut, RegimeValidationReportOut

### Community 146 - "test_no_live_orders.py"
Cohesion: 0.12
Nodes (15): code_only(), fixture, FINAL SAFETY PROOF (spec phase 32): TRADING_MODE=paper cannot send a real…, Executable code only: docstrings (AST) and comments (tokenize) are blanked, so…, `.post(` call sites outside tests: exactly the two known clients (plus…, recorded_requests(), _sources(), test_every_http_post_in_the_codebase_targets_an_allowlisted_endpoint_or_is_internal() (+7 more)

### Community 155 - "Trade"
Cohesion: 0.13
Nodes (32): A closed round-trip (or partial close) — the unit fitness/metrics are computed…, Trade, CooldownConfig, StopLossConfig, TakeProfitConfig, TrailingStopConfig, _base_exits(), _dna() (+24 more)

### Community 156 - "FitnessWeights"
Cohesion: 0.22
Nodes (8): FitnessWeights, Weights are configuration, not code: FITNESS_W_* environment variables., The weights of a recorded snapshot (fitness_scores.weights_used), falling back…, weights_from_recorded(), FitnessVersionSpec, Research-only registry of named fitness formula/timing variants for offline…, A smooth alternative to the hard clip(-1, 1): tanh never fully flattens two…, _signed_sqrt_tanh()

### Community 157 - "_alembic"
Cohesion: 0.50
Nodes (5): _alembic(), _insert(), Path, test_migration_downgrade_removes_the_constraints(), test_migration_refuses_when_existing_rows_violate_a_constraint_and_changes_nothing()

## Knowledge Gaps
- **124 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+119 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1300 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **37 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `Base`, `test_reality_gap_normalisation.py`, `MarketDataService`, `ExecutionRequest`, `entry_quality_audit.py`, `Order`, `MarketCandle`, `test_evolution_pipeline.py`, `run_backtest`, `test_config_audit.py`, `RiskDecision`, `AgentStatus`, `runtime_status.py`, `test_no_live_orders.py`, `test_stops_trailing.py`, `requested_notional`, `test_worker_cycle.py`, `lease.py`, `test_council_failclosed.py`, `test_agent_lifecycle.py`, `FitnessWeights`, `test_regime_validation_engine.py`, `test_ollama_failure_modes.py`, `Trade`, `Side`, `test_promotion_service.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `CouncilDecision`, `test_shadow_mode.py`, `test_lifecycle_ports.py`, `test_entry_quality_audit.py`, `sqlalchemy`, `registry.py`, `PaperExecutionAdapter`, `test_worker_fencing.py`, `StrategyStage`, `OllamaClient`, `below_min_order_notional`, `Bias`, `seal_epoch`, `Settings`, `test_decision_volume.py`, `test_council_deadline.py`, `test_funding.py`, `test_untestable_agents.py`, `dashboard_service.py`, `tradability.py`, `make_agents`, `conftest.py`, `test_champion_challenger_service.py`, `report_agent_evidence.py`, `pytest`, `logging.py`, `test_promotion_evidence.py`, `Agent`, `ExecutionEngine`, `cycle.py`, `5. Migration phases (revised order — risk-ascending, not the original numbering)`, `fitness_forward.py`, `OrderStatus`, `env.py`, `enums.py`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Why does `StrategyDNA` connect `StrategyDNA` to `Order`, `indicators.py`, `test_evolution_pipeline.py`, `run_backtest`, `correlation_service.py`, `RiskDecision`, `test_adversarial_service.py`, `MarketRegime`, `requested_notional`, `test_worker_cycle.py`, `test_council_failclosed.py`, `RuleSet`, `test_agent_lifecycle.py`, `Trade`, `test_regime_validation_engine.py`, `experiment_runner.py`, `Side`, `test_promotion_service.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `test_worker_fencing.py`, `Settings`, `Experiment Guide`, `test_dna_runtime_coverage.py`, `make_agents`, `test_champion_challenger_service.py`, `test_backtesting.py`, `Agent`, `enums.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `Base`, `test_reality_gap_normalisation.py`, `MarketDataService`, `entry_quality_audit.py`, `Order`, `test_evolution_pipeline.py`, `correlation_service.py`, `RiskDecision`, `AgentStatus`, `runtime_status.py`, `requested_notional`, `test_agent_lifecycle.py`, `Trade`, `test_regime_validation_engine.py`, `Side`, `test_promotion_service.py`, `pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_evolution_gate_and_champions.py`, `CouncilDecision`, `sqlalchemy`, `regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `test_worker_fencing.py`, `StrategyStage`, `below_min_order_notional`, `analytics_store.py`, `promotion_service.py`, `fitness_service.py`, `agent_dna`, `dashboard_service.py`, `tradability.py`, `make_agents`, `evaluate_fitness_versions.py`, `shadow_rows_for_generation`, `test_champion_challenger_service.py`, `report_agent_evidence.py`, `test_fitness_edge_cases.py`, `test_promotion_evidence.py`, `ExecutionEngine`, `enums.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 105 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 105 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `make_agents()` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`make_agents()` has 7 INFERRED edges - model-reasoned connections that need verification._