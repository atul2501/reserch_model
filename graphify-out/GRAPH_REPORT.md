# Graph Report - reserch_model  (2026-09-26)

## Corpus Check
- 323 files · ~222,753 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 3, .service 3, .ini 2)

## Summary
- 3982 nodes · 14973 edges · 166 communities (128 shown, 38 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2113 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5aaf98a0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_agents
- sqlalchemy
- test_promotion_service.py
- schemas/reality_gap.py
- service.py
- get_settings
- config.py
- runtime_status.py
- test_ws_client.py
- decision_loop.py
- indicators.py
- MarketCandle
- BacktestResult
- run_backtest
- Side
- RiskDecision
- test_strategy_dna.py
- test_regime_v2.py
- cycle.py
- test_ollama_schema_normalization.py
- test_champion_challenger_service.py
- test_reality_gap_engine.py
- test_worker_cycle.py
- test_postgres_concurrency.py
- test_council_failclosed.py
- helpers_agents.py
- RuleSet
- Agent
- StrategyDNA
- pipeline.py
- test_ollama_failure_modes.py
- test_strategy_regime_matrix.py
- test_experiment_runner.py
- test_shadow_fitness_synthetic.py
- test_position_protection.py
- StrategyStage
- test_evolution_pipeline.py
- test_frozen_oos_epoch.py
- test_shadow_fitness.py
- analyze_trade
- test_adversarial.py
- test_evolution_gate_and_champions.py
- compute_fitness
- OllamaCallStats
- test_correlation.py
- test_shadow_mode.py
- families.py
- MarketDataService
- Post-Refactoring Architecture Review
- test_worker_fencing.py
- HyperliquidClient
- test_regime_validation_engine.py
- PaperExecutionAdapter
- Runbook
- test_db_constraints.py
- shadow_fitness.py
- database.py
- test_fitness_edge_cases.py
- OllamaClient
- below_min_order_notional
- refresh_trade_analytics
- Bias
- test_gap_cycle.py
- test_ollama_client.py
- pytest
- routes/correlation.py
- test_decision_volume.py
- test_adversarial_service.py
- test_check_constraints_are_enforced_by_postgres_itself
- test_funding.py
- Experiment Guide
- What You Must Do When Invoked
- test_fitness_forward.py
- normalization.py
- test_worker_scheduler.py
- test_postgres.py
- test_untestable_agents.py
- WorkerCycle
- test_analytics_migration.py
- test_migrations.py
- StrategyVersion
- test_dna_runtime_coverage.py
- sys
- test_decision_loop_characterization.py
- test_as_of_boundaries.py
- fitness_forward.py
- _Sheet
- conftest.py
- shadow_rows_for_generation
- test_council_integration.py
- analytics.py
- test_promotion_evidence.py
- 24-Hour Data Validation & Next-Phase Execution — Research Report
- run.sh
- test_dashboard_js.py
- margin_state
- test_backtesting.py
- AbuseGuard
- propose_candidate
- test_cooldown_limits.py
- WsCandle
- test_breeding.py
- Position
- FitnessInputs
- a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py
- b7d1f3a9c5e2_db_check_constraints.py
- Refactor Progress
- test_sqlite_locking.py
- compute_and_persist_agent_fitness
- Multi-Week Research Readiness Report
- constraints.py
- analysts.py
- helpers_shadow.py
- evaluate_generation.py
- graphify reference: extra exports and benchmark
- report_trade_quality.py
- alembic_config
- exit_analytics.py
- ImmutableRecordError
- test_min_notional_decision_time.py
- get_reality_gap_chain
- migrate_sqlite_to_postgres.py
- graphify reference: query, path, explain
- 1.1 Confirmed already-safe (no change)
- purge_secrets_from_history.sh
- env.py
- migrate_postgres_to_sqlite.py
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: transcribe video and audio
- graphify reference: GitHub clone and cross-repo merge
- CLAUDE.md
- .claude/CLAUDE.md
- extraction-spec.md
- _bar_ms
- test_no_production_trading_module_imports

## God Nodes (most connected - your core abstractions)
1. `get_settings()` - 236 edges
2. `PaperExecutionAdapter` - 189 edges
3. `Agent` - 163 edges
4. `StrategyDNA` - 157 edges
5. `make_agents()` - 154 edges
6. `make_dna()` - 147 edges
7. `Side` - 144 edges
8. `StrategyVersion` - 134 edges
9. `make_context()` - 132 edges
10. `StrategyStage` - 124 edges

## Surprising Connections (you probably didn't know these)
- `Files changed` --references--> `_execute_next_open_decisions()`  [INFERRED]
  REFACTOR_PROGRESS.md → backend/app/agents/decision_loop.py
- `5. PositionCloseSettler boundary` --references--> `retire_generation()`  [INFERRED]
  ARCHITECTURE_REVIEW.md → backend/app/agents/lifecycle.py
- `Research` --references--> `experiments()`  [INFERRED]
  docs/runbook.md → backend/app/api/routes/evolution.py
- `9. Risk assessment` --references--> `Settings`  [INFERRED]
  LIVE_BACKTEST_PARITY_PLAN.md → backend/app/core/config.py
- `3. Strategy DNA is real behaviour` --references--> `requested_notional()`  [INFERRED]
  docs/architecture.md → backend/app/execution/sizing.py

## Import Cycles
- None detected.

## Communities (166 total, 38 thin omitted)

### Community 0 - "make_agents"
Cohesion: 0.09
Nodes (67): 1. Current Graphify statistics, 2. Current high-degree nodes, 7. Agent/strategy boundaries, False positives (Graphify signal, not an architectural problem), publish_status(), A closed round-trip (or partial close) — the unit fitness/metrics are computed…, Trade, cycle() (+59 more)

### Community 1 - "sqlalchemy"
Cohesion: 0.08
Nodes (81): _components_of(), DB I/O for the analytics foundation. The ONLY module that writes, and it writes…, For every recorded FitnessScore snapshot (plus an hourly reconstruction grid…, refresh_fitness_forward(), RefreshResult, Wires compute_fitness to real persisted data, so Agent.fitness — read by…, Persists PerformanceMetric snapshots from real Trade/Agent state. Regime-…, Base (+73 more)

### Community 2 - "test_promotion_service.py"
Cohesion: 0.36
Nodes (11): _agent_with_fitness(), _passing_metrics(), asyncio, datetime, Champion/challenger promotion wiring: evaluate_promotion actually gets called…, Every rejection must be auditable, not just every promotion — until this was…, _seed_version(), test_no_promotion_under_minimum_track_record() (+3 more)

### Community 3 - "schemas/reality_gap.py"
Cohesion: 0.60
Nodes (4): BaseModel, RealityGapChainReportOut, RealityGapReportOut, StageTransitionGapOut

### Community 4 - "service.py"
Cohesion: 0.05
Nodes (61): argparse, asyncio, SQLite writer processes (worker, research scheduler): take the write lock at…, use_immediate_transactions(), configure_logging(), get_logger(), _install_stdlib_redaction(), factory() (+53 more)

### Community 5 - "get_settings"
Cohesion: 0.05
Nodes (52): _acquire_stream_slot(), Request, Server-Sent Events: a `status` event every `interval` seconds (worker…, One concurrent-SSE slot; release() is idempotent (generator finally + response…, stream(), gen(), _StreamSlot, get_settings() (+44 more)

### Community 6 - "config.py"
Cohesion: 0.04
Nodes (68): 3. Current cross-community bridge nodes, Enum, field_validator, model_validator, str, Centralized application configuration. Every environment-dependent value in the…, Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and…, Relative SQLite paths resolve against backend/ (not the CWD) and their folder… (+60 more)

### Community 7 - "runtime_status.py"
Cohesion: 0.11
Nodes (25): _db_gauges(), ollama_health(), prometheus_metrics(), AsyncSession, get, API-process counters + worker-published counters + DB-derived gauges…, Credential health by INDEX only (never the key itself) + last council outcome., system_status() (+17 more)

### Community 8 - "test_ws_client.py"
Cohesion: 0.07
Nodes (40): HyperliquidWebSocket, Any, Connect/serve/reconnect until `stop()`. Never raises (except cancellation)., WsStats, candle(), FakeServer, make(), Hyperliquid WebSocket transport (spec phase 17) against an in-process fake… (+32 more)

### Community 9 - "decision_loop.py"
Cohesion: 0.07
Nodes (71): 8. `decision_loop.py` remaining responsibilities, Before vs. After summary, Prioritized roadmap: next 3 architectural initiatives, _accrue_funding(), _apply_fill_to_order(), _cancel_order(), _cancel_stale_pending(), _close_position() (+63 more)

### Community 10 - "indicators.py"
Cohesion: 0.08
Nodes (53): _atr(), compute_indicator(), compute_indicator_features(), _ema(), _ind_adx(), _ind_atr(), _ind_bbands(), _ind_donchian() (+45 more)

### Community 11 - "MarketCandle"
Cohesion: 0.13
Nodes (38): MarketCandle, clock_after_bar(), FakeHyperliquid, make_raw_candle(), Deterministic fake exchange + candle factory shared by market/worker tests., i-th 1m candle after T0, Hyperliquid wire format., In-memory stand-in for HyperliquidClient (only the methods the service uses)., A clock value just after bar i has closed (past the 1.5s grace by default). (+30 more)

### Community 12 - "BacktestResult"
Cohesion: 0.08
Nodes (32): BacktestResult, BacktestTrade, persist_backtest_metrics(), persist_walk_forward_metrics(), UUID, Builds a StageMetrics row from a single backtest run (BACKTEST or OUT_OF_SAMPLE…, Builds a StageMetrics row (WALK_FORWARD stage) from a walk-forward report,…, WalkForwardReport (+24 more)

### Community 13 - "run_backtest"
Cohesion: 0.08
Nodes (66): _Pos, DataFrame, `candles` must be sorted ascending by open_time and contain at least…, run_backtest(), _upnl(), DataFrame, Every window runs under the SAME assumptions as the live research engine and…, run_walk_forward() (+58 more)

### Community 14 - "Side"
Cohesion: 0.09
Nodes (55): advance_extremes(), Bar, evaluate_bar(), PositionLevels, ProtectiveTrigger, Open-position management on every confirmed bar (spec phases 8-11). Order of…, Peak/trough AFTER this bar, and whether trailing is now armed., stop_price() (+47 more)

### Community 15 - "RiskDecision"
Cohesion: 0.12
Nodes (43): Routes backtest/adversarial position sizing through the real…, RiskDecision, check_trade(), _drawdown_fraction(), Deterministic Risk Engine (spec section 18). Ollama cannot override this. Every…, RiskCheckInput, RiskCheckResult, _python_sources() (+35 more)

### Community 16 - "test_strategy_dna.py"
Cohesion: 0.12
Nodes (29): _blend(), crossover(), Random, DNA crossover (spec section 25): combine two successful parents' DNA into one…, dna_distance(), A simple, interpretable [0, 1] distance: 0 = identical family and near-…, jitter(), mutate() (+21 more)

### Community 17 - "test_regime_v2.py"
Cohesion: 0.10
Nodes (37): detect_regime(), Deterministic regime classifier (spec section 7), detector v2. Thresholds are…, Fractal swing detection: a swing high (low) is a bar whose high (low) is the…, _swing_points(), _bar_regimes(), DataFrame, parametrize, Regime detector v2 (correctness fixes only; no new thresholds). v1 defects,… (+29 more)

### Community 18 - "cycle.py"
Cohesion: 0.08
Nodes (38): counter_value(), _escape(), _fmt(), inc(), _key(), observe(), Tiny dependency-free metrics registry (counters, summaries) with Prometheus…, One place to count database failures (connection loss, deadlock, constraint… (+30 more)

### Community 19 - "test_ollama_schema_normalization.py"
Cohesion: 0.12
Nodes (46): ValueError, The response cannot be safely normalised. `reason` is a short machine-readable…, ResponseNormalizationError, analyst_server(), client_for(), gen(), items(), long_vote() (+38 more)

### Community 20 - "test_champion_challenger_service.py"
Cohesion: 0.21
Nodes (28): advance_pipeline_stage(), Attempts to move `strategy_version_id` one step forward in the pipeline.…, asyncio, datetime, ChampionChallengerEngine: the Candidate -> Validation -> Challenger ->…, This is the one place advance_pipeline_stage calls evaluate_and_promote — no…, A FRAGILE classification must never be an automatic block — it doubles the…, Regression guard: champion_status is nullable and most versions never had it… (+20 more)

### Community 21 - "test_reality_gap_engine.py"
Cohesion: 0.10
Nodes (34): compute_full_reality_gap_chain(), persist_reality_gap_report(), AsyncSession, UUID, Full-lifecycle reality-gap report: Backtest -> Walk-Forward -> Out-of-Sample ->…, Compares every consecutive pair of stages this strategy version has actually…, Insert-only — caller commits., RealityGapChainReport (+26 more)

### Community 22 - "test_worker_cycle.py"
Cohesion: 0.13
Nodes (28): CandleNotFinalError, RuntimeError, A candle about to drive a decision is not (or is no longer) the confirmed bar…, One scheduler tick: sync -> gap check -> replay/process pending bars., run_pending_cycles(), _crash_bar(), _positions_at(), test_positions_are_protected_when_the_decision_phase_fails_and_when_the_bar_becomes_poison() (+20 more)

### Community 23 - "test_postgres_concurrency.py"
Cohesion: 0.09
Nodes (28): postgres_connect_args(), asyncpg session settings: a runaway query, a lock wait or a forgotten open…, db_now(), _insert_fn(), LeaseState, AsyncSession, Cheap, no I/O: raise LeaseLost if the lease was lost or could not be renewed…, Verify, INSIDE the caller's transaction, that we still own the lease at our… (+20 more)

### Community 24 - "test_council_failclosed.py"
Cohesion: 0.09
Nodes (46): _failure_bucket(), AsyncSession, run_council_cycle(), CouncilDecision, One consensus outcome for one candle — shared by all agents., test_council_endpoints_expose_analysts_failures_latency_and_judge(), Council fail-closed contract (spec phases 10-12). If the council is REQUIRED…, _run() (+38 more)

### Community 25 - "helpers_agents.py"
Cohesion: 0.13
Nodes (40): _atr(), _bollinger(), compute_features(), _ema(), _macd(), minimal_context(), DataFrame, Series (+32 more)

### Community 26 - "RuleSet"
Cohesion: 0.08
Nodes (59): check_candidate_schema(), Gate 1 of the candidate pipeline: the DNA must survive a strict round-trip…, _gate_candidates(), gate(), Extinction restart: fresh founders, each through the SAME gate as bred children…, _spawn_founders(), gate(), make_valid() (+51 more)

### Community 27 - "Agent"
Cohesion: 0.08
Nodes (56): _process_agent(), AgentAlreadyDeadError, bankruptcy_threshold(), create_generation(), format_agent_identifier(), is_population_extinct(), mark_dead(), AsyncSession (+48 more)

### Community 28 - "StrategyDNA"
Cohesion: 0.16
Nodes (39): MarketRegime, StrategyFamily, ComparisonOperator, IndicatorConfig, BaseModel, Enum, field_validator, model_validator (+31 more)

### Community 29 - "pipeline.py"
Cohesion: 0.05
Nodes (85): BacktestData, candles_fingerprint(), _compute_contexts(), extend_with_specs(), prepare_backtest_data(), DataFrame, Shared, precomputed backtest inputs (spec phase 5/39). Feature computation…, Adds any indicator series not yet present (idempotent; a spec whose series all… (+77 more)

### Community 30 - "test_ollama_failure_modes.py"
Cohesion: 0.05
Nodes (60): reset(), OllamaAuthError, _attempt(), _attempt_with_retry(), OllamaConnectionError, OllamaError, OllamaRateLimitError, OllamaResponseError (+52 more)

### Community 31 - "test_strategy_regime_matrix.py"
Cohesion: 0.09
Nodes (32): bootstrap_expectancy_ci(), cell_bootstrap_inputs(), cell_metrics(), _class_share(), _drawdown(), edge_flags(), episode_block_bootstrap_ci(), episode_ids() (+24 more)

### Community 32 - "test_experiment_runner.py"
Cohesion: 0.12
Nodes (29): _bars_from_frame(), compute_metrics(), diff_experiments(), ExperimentMetrics, list_experiments(), AsyncSession, Bar, DataFrame (+21 more)

### Community 33 - "test_shadow_fitness_synthetic.py"
Cohesion: 0.12
Nodes (30): champion_evidence_ok(), SHADOW-ONLY champion evidence: the posterior must show a positive true edge…, make_population(), The SAME trades under higher costs (2x fees + 3x slippage is roughly +13 bps…, world 'mixed': edges {-0.30,-0.10,0,+0.12,+0.30} with weights…, with_extra_cost(), _current_top(), _lfp_world_precisions() (+22 more)

### Community 34 - "test_position_protection.py"
Cohesion: 0.12
Nodes (21): Residual of the cash identity (0.0 when the books balance). balance == starting…, reconcile(), FailingExits, open_position(), paper(), fixture, Open positions never lose protection (spec phases 9, 24) and books always…, A hand-made open position (as if opened on an earlier bar). (+13 more)

### Community 35 - "StrategyStage"
Cohesion: 0.15
Nodes (30): comparability(), compute_live_stage_metrics(), _max_drawdown(), Computes the same 4 base metrics from actual Trade/Agent history for every…, Peak-to-trough drawdown of the account built from `starting` plus each closed…, Whether the two stages can be used as RELIABLE evidence against each other.…, StrategyStage, One performance snapshot for a StrategyVersion at a given pipeline stage.… (+22 more)

### Community 36 - "test_evolution_pipeline.py"
Cohesion: 0.14
Nodes (32): events(), experiment_diff(), experiments(), generations(), AsyncSession, get, Baseline-vs-candidate diff for two experiment_ids (see…, summary() (+24 more)

### Community 37 - "test_frozen_oos_epoch.py"
Cohesion: 0.07
Nodes (52): _epoch_is_sealed(), ImmutableResearchRecordError, _never_delete(), _oos_evaluation_is_write_once(), listens_for, RuntimeError, _build_epoch(), EpochIntegrityError (+44 more)

### Community 38 - "test_shadow_fitness.py"
Cohesion: 0.17
Nodes (21): compute_shadow(), Pure function: side-by-side rows for every agent. Priors are estimated per unit…, TradeEvidence, make_trades(), Poisson(lam*days) trades with true mean net return `edge_r` (in R), heavy-…, Pure exposure scaling: k times the size, identical trading decisions., scaled(), _agent() (+13 more)

### Community 39 - "analyze_trade"
Cohesion: 0.17
Nodes (28): analyze_trade(), Bar, classify_trade(), ExcursionResult, _is_long(), _pnl(), Pure trade-quality engine: MFE/MAE replay, entry/exit quality, classification.…, Signed PnL of a LONG/SHORT position between two prices (no costs). (+20 more)

### Community 40 - "test_adversarial.py"
Cohesion: 0.08
Nodes (53): AdversarialReport, _clip01(), compute_robustness_score(), drop_random_candles(), duplicate_random_candles(), inject_abnormal_volume(), inject_extreme_move(), inject_gap() (+45 more)

### Community 41 - "test_evolution_gate_and_champions.py"
Cohesion: 0.16
Nodes (25): BreedingResult, NoValidCandidatesError, AsyncSession, Random, RuntimeError, UUID, Generation-breeding orchestrator (spec sections 25, 27, 29). Wires the…, Selects survivors from `generation_number`, breeds children via… (+17 more)

### Community 42 - "compute_fitness"
Cohesion: 0.21
Nodes (19): compute_fitness(), FitnessWeights, Weights are configuration, not code: FITNESS_W_* environment variables., The weights of a recorded snapshot (fitness_scores.weights_used), falling back…, weights_from_recorded(), base(), Composite fitness (spec phase 30): not raw PnL, bounded, configurable,…, BUG: FitnessInputs.daily_consistency is computed and passed by every caller… (+11 more)

### Community 43 - "OllamaCallStats"
Cohesion: 0.16
Nodes (13): OllamaCallStats, BareMinimumClient, asyncio, parametrize, The boundary is real: neither council module imports app.services.ollama_client…, OllamaClient itself is UNCHANGED and still works as the council's AI client -…, Deliberately NOT an OllamaClient, not a subclass, not registered with it - only…, End-to-end proof: the full council cycle (quorum, consensus, persistence) runs… (+5 more)

### Community 44 - "test_correlation.py"
Cohesion: 0.05
Nodes (76): _most_correlated_pair(), The least-diverse pair (O(n^2) over precomputed signatures; kept for…, _make_candidates(), _condition_set(), entry_condition_similarity(), exit_condition_similarity(), feature_set(), feature_similarity() (+68 more)

### Community 45 - "test_shadow_mode.py"
Cohesion: 0.06
Nodes (51): ABC, ExecutionStressResult, Random, Execution-quality stress testing: delay, partial fills, and missed fills, run…, Submits every request through `adapter` sequentially and aggregates fill-…, Wraps PaperExecutionAdapter and stochastically injects partial fills, missed…, run_execution_stress_scenario(), StressedExecutionAdapter (+43 more)

### Community 46 - "families.py"
Cohesion: 0.20
Nodes (27): _bias(), _clip(), _dir_breakout(), _dir_hybrid(), _dir_mean_reversion(), _dir_momentum(), _dir_order_flow(), _dir_scalping() (+19 more)

### Community 47 - "MarketDataService"
Cohesion: 0.10
Nodes (18): _as_float(), _chunks(), _dialect_insert(), MarketDataService, AsyncSession, DataFrame, Finality rule shared by REST and WebSocket ingestion., Fetches the last `lookback_candles` candles and upserts them. Returns the… (+10 more)

### Community 48 - "Post-Refactoring Architecture Review"
Cohesion: 0.05
Nodes (41): 10. Market-data dependency direction, 11. AI/Ollama dependency direction, 13. Test architecture, 14. Any newly introduced coupling, 4. AIClientPort boundary, 5. PositionCloseSettler boundary, 6. ExecutionEngine boundary, 9. Database dependency direction (+33 more)

### Community 49 - "test_worker_fencing.py"
Cohesion: 0.10
Nodes (31): LeaseLost, RuntimeError, This worker no longer holds the lease (superseded, expired, or unable to renew…, _close_keepers(), _counts(), _keeper(), paper(), fixture (+23 more)

### Community 51 - "HyperliquidClient"
Cohesion: 0.08
Nodes (18): BookProvider, Protocol, HyperliquidClient, HyperliquidError, Any, RuntimeError, Fetches perp metadata + current funding/open-interest context., Wraps Hyperliquid's `/info` endpoint. Live order placement (the exchange-… (+10 more)

### Community 52 - "test_regime_validation_engine.py"
Cohesion: 0.09
Nodes (42): _all_regimes(), classify_robustness(), compute_regime_breakdown_backtest(), compute_regime_breakdown_live(), _coverage_note(), _max_drawdown_from_pnls(), AsyncSession, UUID (+34 more)

### Community 53 - "PaperExecutionAdapter"
Cohesion: 0.12
Nodes (34): PaperExecutionAdapter, Random, OrderStatus, _orders(), _pos(), Paper execution at the NEXT bar's open (spec phase 6): no signal-bar-close…, Bar N+1 opens at 101 and trades down to 95: the ATR stop (~100) is hit on the…, test_a_pending_entry_that_was_not_filled_on_the_next_bar_is_never_filled_late() (+26 more)

### Community 54 - "Runbook"
Cohesion: 0.05
Nodes (36): 10. Observability, 11. Failure handling, 1. System overview, 2. The trading cycle (one confirmed candle), 3. Strategy DNA is real behaviour, 4. Execution, margin, funding, 5. AI council as *context*, not oracle, 6. Ollama client (+28 more)

### Community 55 - "test_db_constraints.py"
Cohesion: 0.14
Nodes (29): _agent(), _alembic(), _candle(), _insert(), _migration_module(), _order(), _position(), Path (+21 more)

### Community 56 - "shadow_fitness.py"
Cohesion: 0.16
Nodes (20): estimate_prior(), Prior, ndarray, SHADOW evaluation of the proposed evidence-aware fitness architecture (Phase…, Empirical-Bayes population prior from the agents that traded enough to inform…, _samples(), ShadowConfig, unit_result() (+12 more)

### Community 57 - "database.py"
Cohesion: 0.05
Nodes (81): get_adversarial_report_history(), get_latest_adversarial_report(), AsyncSession, get, UUID, _decision(), history(), latest() (+73 more)

### Community 58 - "test_fitness_edge_cases.py"
Cohesion: 0.14
Nodes (19): capped_profit_factor(), compute_trade_stats(), _max_streaks(), Pure trade-statistics engine feeding PerformanceMetric snapshots.…, gross_win / gross_loss; the no-loss case is capped, and no evidence at all (no…, Longest consecutive-win and consecutive-loss streaks, in trade order. Flat…, TradeStatsResult, Fraction of windows that were profitable — a simple, auditable stand-in for… (+11 more)

### Community 59 - "OllamaClient"
Cohesion: 0.09
Nodes (30): OllamaClient, OllamaKeyHealth, Returns (key, key_index). key_index is the position in OLLAMA_API_KEYS (never…, Safe operational state: positions/statuses only, never secrets., Re-read credentials from settings WITHOUT a restart. A key whose value is…, In-memory credential health. Keys are intentionally never persisted or logged.…, analyst_from(), _analyst_json() (+22 more)

### Community 60 - "below_min_order_notional"
Cohesion: 0.05
Nodes (66): 12. Live/backtest duplication, backtest_risk_check(), Returns the risk-approved notional (0.0 if the real Risk Engine would reject…, _SyntheticAgentState, approve_against_margin(), below_min_order_notional(), build_sizing_result(), normalize_method() (+58 more)

### Community 61 - "refresh_trade_analytics"
Cohesion: 0.13
Nodes (30): _as_trade_rows(), _is_uuid(), _ms(), AsyncSession, datetime, Rebuild the matrix for `computation_version` (derived aggregate: DELETE the…, `as_of`, when given, bounds every piece of data this refresh may see (candles,…, refresh_strategy_regime_matrix() (+22 more)

### Community 62 - "Bias"
Cohesion: 0.18
Nodes (24): apply_judge(), compute_consensus(), Deterministic consensus engine (spec section 9). Never produced by an LLM —…, A "strong" consensus is a lead of at least `consensus_margin` votes over the…, Overlays a judge's ruling onto a weak-consensus result. The risk engine…, tally_votes(), _run_judge(), Bias (+16 more)

### Community 63 - "test_gap_cycle.py"
Cohesion: 0.12
Nodes (20): active_flags(), AsyncSession, Read/write helpers for durable system flags (kill switch, data-gap halt)., Returns {flag_name: reason} for every currently-active flag., Single string (or None) the risk engine uses to block NEW entries., set_flag(), trading_halt_reason(), GapReport (+12 more)

### Community 64 - "test_ollama_client.py"
Cohesion: 0.19
Nodes (14): _Echo, _mock_transport(), asyncio, BaseModel, Ollama client failure handling: timeout, 429, malformed response (spec 45)., Root cause of the reported intermittent analyst 401s: with multiple…, test_401_on_every_key_exhausts_retries_and_raises_auth_error(), test_401_on_one_key_is_retried_and_recovers_on_the_next_key() (+6 more)

### Community 65 - "pytest"
Cohesion: 0.14
Nodes (19): PositionCloseSettler, Protocol, Ports the agent-lifecycle domain depends on, so it does not reach directly into…, Matches `app.execution.accounting.settle_close` exactly - this describes that…, SettlementResult, _AlwaysZeroBadDebtSettler, _FakeSettlement, Phase 2 dependency-boundary regression: app/agents/lifecycle.py must not import… (+11 more)

### Community 66 - "routes/correlation.py"
Cohesion: 0.23
Nodes (14): get_agent_correlations(), get_convergence_history(), get_family_correlation_matrix(), get_top_correlated_pairs(), AsyncSession, get, UUID, Family x family mean-correlation grid for one generation — never the raw agent… (+6 more)

### Community 67 - "test_decision_volume.py"
Cohesion: 0.13
Nodes (25): count_noop(), main(), _noop_filter(), prune_noop_decisions(), AsyncSession, datetime, Reclaim space taken by legacy "nothing happened" decision rows. Before the fix,…, Deletes no-op rows older than `cutoff` in batches. Returns rows deleted. (+17 more)

### Community 68 - "test_adversarial_service.py"
Cohesion: 0.15
Nodes (16): AdversarialConfig, Every scenario parameter. `from_settings()` is the production source; the…, AsyncSession, DataFrame, UUID, Loads `strategy_version_id`'s DNA, runs the full adversarial suite (risk-gated…, run_and_persist_adversarial_suite(), asyncio (+8 more)

### Community 69 - "test_check_constraints_are_enforced_by_postgres_itself"
Cohesion: 0.67
Nodes (3): test_check_constraints_are_enforced_by_postgres_itself(), order(), pend()

### Community 70 - "test_funding.py"
Cohesion: 0.33
Nodes (11): _dna(), _hold_across(), _no_sleep(), fixture, Funding (spec phase 8): accrued from exchange-published settlements, never…, test_funding_is_idempotent_across_repeated_cycles(), test_long_pays_positive_funding_and_it_hits_balance_and_ledger(), test_negative_rate_credits_a_long() (+3 more)

### Community 71 - "Experiment Guide"
Cohesion: 0.11
Nodes (18): 1. Running a baseline vs. candidate experiment, 2. Comparing experiments, 3. Verifying `as_of` boundaries yourself, 4. Starting the dashboard, 5. Starting the 500-agent paper/shadow experiment, 6. Stopping safely, 7. Recovering after a restart, Custom configs (+10 more)

### Community 72 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 73 - "test_fitness_forward.py"
Cohesion: 0.19
Nodes (21): AgentFacts, forward_window(), The production fitness an agent WOULD have had at T, from closed trades only.…, The honest (T, T+h] window: truncated at the earliest real boundary., The immutable facts of an agent needed at any T (no mutable state)., reconstruct_fitness_at(), facts(), point() (+13 more)

### Community 74 - "normalization.py"
Cohesion: 0.24
Nodes (12): _loads(), _max_length(), NormalizationReport, _normalize_list(), normalize_payload(), parse_model_json(), Any, BaseModel (+4 more)

### Community 75 - "test_worker_scheduler.py"
Cohesion: 0.23
Nodes (14): confirmation_time_ms(), council_due(), last_confirmed_open_time(), Candle-boundary arithmetic for the worker (pure functions, no I/O). Hyperliquid…, Open time of the most recent bar whose close+grace is already in the past., Wall-clock instant (ms) at which the bar opening at `open_time_ms` becomes…, Seconds to sleep until the next bar becomes confirmable (never negative)., Deterministic, restart-safe council cadence derived from the candle timestamp… (+6 more)

### Community 76 - "test_postgres.py"
Cohesion: 0.13
Nodes (21): alembic_autogenerate, alembic_migration, _alembic(), pg(), fixture, test_migration_preflight_refuses_on_postgres_and_changes_nothing(), _drift(), pg_database() (+13 more)

### Community 77 - "test_untestable_agents.py"
Cohesion: 0.19
Nodes (21): blocked_entry_counts(), is_untestable(), AsyncSession, UUID, `blocked` entry attempts refused by the minimum vs `executed` entries actually…, Entry attempts refused by the exchange minimum, per agent (one grouped query)., untestable_agent_ids(), Ranks every agent in `generation_number` by `Agent.fitness` (falling back to… (+13 more)

### Community 78 - "WorkerCycle"
Cohesion: 0.22
Nodes (10): One immutable processing attempt for a confirmed market candle., WorkerCycle, candle(), test_sse_stream_emits_status_and_cycle_events(), test_status_reports_stale_market_data_and_data_gap_halt(), test_status_says_worker_down_when_no_heartbeat_and_ok_when_fresh(), WebSocket -> store glue, and an end-to-end paper-mode smoke test of the real…, `python -m scripts.run_cycle --once` in paper mode against a fake exchange:… (+2 more)

### Community 79 - "test_analytics_migration.py"
Cohesion: 0.15
Nodes (13): _alembic(), _insert_ffp_row(), migrated_db(), CompletedProcess, fixture, Path, Migration-level analytics guarantees: the evidence table is write-once at the…, Minimal valid parent chain (strategies -> strategy_versions -> agents) + one… (+5 more)

### Community 80 - "test_migrations.py"
Cohesion: 0.33
Nodes (10): _alembic(), CompletedProcess, Path, Alembic migrations must (a) apply cleanly from scratch, (b) leave the schema in…, Missing/extra tables and columns between the migrated DB and the ORM., _structural_diffs(), test_downgrade_then_upgrade_round_trips(), test_drift_detector_actually_detects_drift() (+2 more)

### Community 81 - "StrategyVersion"
Cohesion: 0.10
Nodes (39): agent_dna(), agent_equity_curve(), agent_fitness(), agent_regime_performance(), get_agent(), list_agents(), AsyncSession, get (+31 more)

### Community 82 - "test_dna_runtime_coverage.py"
Cohesion: 0.23
Nodes (10): ast, has_asserting_test(), _model_subfields(), Every DNA field must either change runtime behaviour (with a test proving it)…, The previous check was a substring search: a commented-out `def` or an empty…, A REAL test function (not a comment, docstring or helper) that contains at…, test_every_coverage_reference_points_at_a_real_asserting_test(), test_every_nested_dna_field_is_covered_by_a_named_behaviour_test() (+2 more)

### Community 83 - "sys"
Cohesion: 0.19
Nodes (13): main(), Generate an API key and the API_KEYS entry for it. python -m…, _is_placeholder(), main(), Path, Fail if a tracked file contains something shaped like a real credential. Usage:…, scan_text(), tracked_files() (+5 more)

### Community 84 - "test_decision_loop_characterization.py"
Cohesion: 0.29
Nodes (10): _build_scenario(), asyncio, Phase 4.0 characterization baseline for decision_loop.py (REFACTOR_PLAN.md…, 4 agents: A (normal entry -> signal exit), B (normal entry -> stopped out,…, Sanity checks independent of the golden snapshot below - these describe the…, THE regression test: byte-for-byte (modulo the documented exclusions in the…, _run_fixed_scenario(), test_fixed_scenario_is_internally_consistent() (+2 more)

### Community 85 - "test_as_of_boundaries.py"
Cohesion: 0.23
Nodes (15): compute_agent_performance_metric(), compute_and_persist_agent_performance_metric(), AsyncSession, datetime, Builds (does not persist) a PerformanceMetric snapshot for `agent` from its…, datetime, Regression coverage for the `as_of` hardening pass: for any evaluation with…, Backward-compatible default: as_of=None preserves the original unbounded… (+7 more)

### Community 86 - "fitness_forward.py"
Cohesion: 0.20
Nodes (15): CensoredWindow, _daily_consistency(), _drawdown_from_curve(), forward_performance(), ForwardPerformance, max_drawdown_currency(), datetime, Pure fitness->future engine: point-in-time reconstruction and forward windows.… (+7 more)

### Community 87 - "_Sheet"
Cohesion: 0.19
Nodes (9): _build(), _cell_value(), _flatten(), Any, datetime, Nested dicts become dotted columns; lists become JSON text., _Sheet, Workbook (+1 more)

### Community 88 - "conftest.py"
Cohesion: 0.19
Nodes (11): configure_sqlite_engine(), Make SQLite behave like the production database for transactions. * foreign…, db_engine(), db_session(), immediate_fills(), fixture, The async engine behind `db_session` (tests that need extra independent…, Legacy/shadow-style execution: an order fills on the signal bar's own close.… (+3 more)

### Community 89 - "shadow_rows_for_generation"
Cohesion: 0.22
Nodes (12): rank_correlation(), ranked(), Rows ordered best-first by 'current', 'R' or 'bps'. Proposed scores rank TESTED…, Spearman rank correlation between two scores over the agents that are ranked…, Side-by-side shadow rows for every agent of `generation`, built from persisted…, shadow_rows_for_generation(), ShadowRow, _flat() (+4 more)

### Community 90 - "test_council_integration.py"
Cohesion: 0.17
Nodes (18): _council_context(), combine(), out(), CombinedDecision, CouncilContext, Deterministic, auditable integration of the AI council into an agent's decision…, The context to use for `candle_open_time`. A result produced for a different…, test_not_run_means_approved_only_when_the_council_was_not_required() (+10 more)

### Community 91 - "analytics.py"
Cohesion: 0.09
Nodes (31): Which agents can be TESTED at their capital (Option D of the min-notional…, _ffp_is_write_once(), _ffp_never_delete(), FitnessForwardPerformance, ImmutableAnalyticsRecordError, listens_for, RuntimeError, Derived analytical tables (the analytics foundation). These tables store ONLY… (+23 more)

### Community 92 - "test_promotion_evidence.py"
Cohesion: 0.15
Nodes (28): CandidateMetrics, evaluate_promotion(), PromotionCriteria, PromotionDecision, Champion/challenger promotion logic (spec section 28). A challenger can NEVER…, _average_agent_fitness(), _candidate_metrics(), evaluate_and_promote() (+20 more)

### Community 93 - "24-Hour Data Validation & Next-Phase Execution — Research Report"
Cohesion: 0.12
Nodes (16): 10. FINAL STATUS, 24-Hour Data Validation & Next-Phase Execution — Research Report, 4. 24-HOUR BASELINE, 5. EXIT ANALYSIS, 6. EXIT EXPERIMENT PLAN, 7. POSTGRESQL MIGRATION PLAN, 9. ACCEPTANCE CRITERIA, Backup strategy (+8 more)

### Community 94 - "run.sh"
Cohesion: 0.36
Nodes (9): cmd_logs(), cmd_start(), cmd_status(), cmd_stop(), do_setup(), is_running(), run.sh script, stop_one() (+1 more)

### Community 95 - "test_dashboard_js.py"
Cohesion: 0.28
Nodes (12): Path, The dashboard's script must not introduce XSS from API text and must shout when…, Static guard: a template `${...}` that touches an API-supplied string field…, run(), status(), test_api_text_fields_are_never_interpolated_unescaped(), test_esc_neutralises_markup_from_api_text(), test_healthy_system_shows_all_components_and_no_banner() (+4 more)

### Community 96 - "margin_state"
Cohesion: 0.18
Nodes (14): compute_liquidation_price(), compute_trade_pnl(), compute_unrealized_pnl(), PnL engine (spec section 20). Profitability is never computed from raw price…, Cross-margin (single position) liquidation price: the mark at which `balance +…, TradePnL, margin_state(), MarginState (+6 more)

### Community 97 - "test_backtesting.py"
Cohesion: 0.20
Nodes (16): chronological_split(), DataSplit, DataFrame, Data split utilities (spec section 23). Enforces strict chronological…, Splits strictly in time order (never shuffled — this is time series data, and…, DataFrame, Event-driven backtester: no look-ahead, sane trade accounting (spec 22/45)., Regression guard against look-ahead: a fill price equal to the signal bar's… (+8 more)

### Community 98 - "AbuseGuard"
Cohesion: 0.22
Nodes (3): AbuseGuard, Returns True when this failure triggers a lockout., In-process brute-force lockout (per client address) and request-rate cap (per…

### Community 99 - "propose_candidate"
Cohesion: 0.19
Nodes (10): propose_candidate(), Returns None if Ollama's proposal fails schema validation — the caller must…, _AlwaysFailsClient, asyncio, Duck-typed stand-in for OllamaClient — raises immediately rather than going…, Every analyst call fails (simulated total Ollama outage). The council must…, test_council_cycle_falls_back_to_hold_when_ollama_is_completely_down(), test_propose_candidate_returns_none_on_ollama_rate_limit() (+2 more)

### Community 100 - "test_cooldown_limits.py"
Cohesion: 0.24
Nodes (14): CooldownConfig, _dna(), _fast(), fixture, Cooldown and max-trades-per-day are hard runtime gates (spec phase 11)., entry at bar i, exit (rsi<40) at bar i+1. Returns last ctx., test_cooldown_after_loss_blocks_reentry_for_n_bars_then_allows(), test_cooldown_is_counted_in_bars_of_the_configured_timeframe() (+6 more)

### Community 101 - "WsCandle"
Cohesion: 0.29
Nodes (4): BaseModel, field_validator, The REST wire format MarketDataService.upsert_candles consumes., WsCandle

### Community 102 - "test_breeding.py"
Cohesion: 0.24
Nodes (14): _preserve_family_distribution(), Biases fresh-DNA injection toward minority families apply_diversity_pressure…, _dna(), asyncio, Generation-breeding orchestrator: survivor selection and the population-…, Without the cap, 5 high-fitness MOMENTUM agents would take every survivor slot…, _seed_generation(), test_breeding_accepts_diversity_pressure_signals_without_error() (+6 more)

### Community 103 - "Position"
Cohesion: 0.13
Nodes (35): DataFrame, Evaluates every ACTIVE agent in `generation` against `context` (a confirmed…, run_decision_cycle(), Decision, Position, capture_state(), See module docstring for exactly what is/isn't included and why., _round() (+27 more)

### Community 104 - "FitnessInputs"
Cohesion: 0.22
Nodes (12): _clip(), FitnessInputs, FitnessResult, _profit_factor_component(), Composite fitness engine (spec section 21). Deliberately NOT raw PnL. Combines…, [-1, 1]. Explicit, never an `x or default` fallback (zero is a real, bad,…, [-1, 1]. A 0% win rate over real trades is the WORST score (-1), not neutral;…, _win_rate_component() (+4 more)

### Community 105 - "a4d1e8c2b9f7_t7_research_registry_lineage_snapshots.py"
Cohesion: 0.50
Nodes (3): # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in…, _ts_cols(), upgrade()

### Community 106 - "b7d1f3a9c5e2_db_check_constraints.py"
Cohesion: 0.50
Nodes (3): _pending_predicate(), database CHECK constraints + one-pending-entry-per-agent (impossible states…, upgrade()

### Community 107 - "Refactor Progress"
Cohesion: 0.17
Nodes (11): 2. PositionCloseSettler review, 3. Dependency-direction map, 4-5. Test results, Files changed, Full test suite (both phases combined), Phase 3 — Boundary verification and hardening (no `decision_loop.py`), Phase 4.1 — Extraction performed, Phase 4 — proposed plan for `decision_loop.py` (NOT implemented; plan only, pending approval) (+3 more)

### Community 108 - "test_sqlite_locking.py"
Cohesion: 0.24
Nodes (11): factory(), fixture, SQLite write-lock behaviour on a real WAL file shared by two connections…, Documents the failure mode seen on the worker (API keeps this default)., Regression guard for why _on_begin exists: rolling back a per-agent SAVEPOINT…, test_deferred_begin_fails_instantly_on_stale_snapshot(), test_immediate_begin_makes_concurrent_writers_queue(), cycle() (+3 more)

### Community 109 - "compute_and_persist_agent_fitness"
Cohesion: 0.21
Nodes (14): compute_and_persist_agent_fitness(), _daily_consistency(), FitnessSummary, _latest_by_version(), _overlaps(), Any, AsyncSession, UUID (+6 more)

### Community 110 - "Multi-Week Research Readiness Report"
Cohesion: 0.14
Nodes (13): 10. FINAL READINESS CHECK, 1.2 Three genuine gaps found and fixed, 1. `as_of` BOUNDARY AUDIT, 3. CONTROLLED IMPROVEMENT ON THE 24H DATA — Development vs. Validated Result, 4. STANDARD EXPERIMENT COMPARISON FORMAT, 5. EXIT RESEARCH, 6. POSTGRESQL RE-VERIFICATION, 7. RESEARCH DASHBOARD (+5 more)

### Community 111 - "constraints.py"
Cohesion: 0.50
Nodes (3): attach_constraints(), Database-level invariants (spec phase 26). Python validation alone is not…, Idempotently attaches every CHECK and the extra partial unique indexes to…

### Community 112 - "analysts.py"
Cohesion: 0.23
Nodes (12): AnalystRunResult, build_prompt(), AI council analyst prompts (spec section 8). Each analyst receives the same…, Carries this analyst's own timing/stats directly, rather than reading…, Never raises — one bad or unreachable Ollama call must never block the rest of…, run_analyst(), _failed_result(), _gather_analysts_with_deadline() (+4 more)

### Community 113 - "helpers_shadow.py"
Cohesion: 0.23
Nodes (10): ShadowAgentInput, current_fitness(), _fake_backtest(), Population, ndarray, Synthetic ground-truth generator for the shadow-fitness tests. The TRUE net…, (production compute_fitness, max drawdown) fed the way fitness_service feeds…, Agents plus the ground truth. `truth_edge[i]` is the true net edge (R/trade) of… (+2 more)

### Community 114 - "evaluate_generation.py"
Cohesion: 0.31
Nodes (9): _build_advisory_criteria(), _latest_adversarial_report(), latest_challenger_evaluation(), _latest_regime_validation_report(), AsyncSession, UUID, Tightens `min_fitness_improvement` for FRAGILE/UNSTABLE regime classification —…, evaluate_generation() (+1 more)

### Community 115 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 116 - "report_trade_quality.py"
Cohesion: 0.33
Nodes (9): _flat(), getattr_r(), main(), _mean(), _median(), _pct(), READ-ONLY trade-quality report (Reports B, C, D): entry quality, exit quality,…, Group value as a plain string ('SIDE.SHORT' enum repr -> 'SHORT', None -> '-'). (+1 more)

### Community 118 - "exit_analytics.py"
Cohesion: 0.36
Nodes (7): exit_analytics(), _histogram(), AsyncSession, datetime, get, UUID, Exit-research dashboard data: MFE/MAE, realized R, post-exit movement, reversal…

### Community 119 - "ImmutableRecordError"
Cohesion: 0.38
Nodes (7): _dna_is_immutable(), ImmutableRecordError, listens_for, RuntimeError, _snapshot_is_undeletable(), _snapshot_is_write_once(), test_strategy_version_dna_cannot_be_edited()

### Community 120 - "test_min_notional_decision_time.py"
Cohesion: 0.48
Nodes (6): _decisions(), _orders(), Minimum order notional is enforced at DECISION time, not discovered a bar later…, test_entry_at_the_minimum_still_creates_a_pending_order(), test_sub_minimum_entry_is_rejected_at_decision_time_with_an_explicit_reason(), test_the_minimum_can_be_disabled_like_at_the_adapter()

### Community 121 - "get_reality_gap_chain"
Cohesion: 0.47
Nodes (6): get_reality_gap_chain(), get_reality_gap_history(), AsyncSession, get, UUID, Computed live from current StageMetrics — read-only, not persisted. Empty…

### Community 123 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.47
Nodes (5): main(), migrate(), One-off: copy every row from a SQLite trading_lab.db into a Postgres database,…, Idempotent: alembic upgrade to a revision it's already at is a no-op., upgrade_schema()

### Community 124 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 125 - "1.1 Confirmed already-safe (no change)"
Cohesion: 0.67
Nodes (4): _corr_upto(), _latest_upto(), _stage_evidence_upto(), 1.1 Confirmed already-safe (no change)

### Community 135 - "env.py"
Cohesion: 0.50
Nodes (3): do_run_migrations(), run_migrations_online(), logging_config

### Community 137 - "migrate_postgres_to_sqlite.py"
Cohesion: 0.67
Nodes (3): main(), migrate(), One-off: copy every row from the live Postgres database into a fresh SQLite…

### Community 138 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 139 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 164 - "_bar_ms"
Cohesion: 0.67
Nodes (3): _bar_ms(), Bar, Interval of the candle grid (median diff), 60_000 fallback.

## Knowledge Gaps
- **117 isolated node(s):** `purge_secrets_from_history.sh script`, `graphify`, `Usage`, `What graphify is for`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)` (+112 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1215 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **38 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `make_agents`, `sqlalchemy`, `test_promotion_service.py`, `service.py`, `config.py`, `env.py`, `runtime_status.py`, `decision_loop.py`, `migrate_postgres_to_sqlite.py`, `MarketCandle`, `run_backtest`, `Side`, `RiskDecision`, `cycle.py`, `test_champion_challenger_service.py`, `test_worker_cycle.py`, `test_postgres_concurrency.py`, `test_council_failclosed.py`, `helpers_agents.py`, `Agent`, `pipeline.py`, `test_position_protection.py`, `StrategyStage`, `test_evolution_pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_adversarial.py`, `test_evolution_gate_and_champions.py`, `compute_fitness`, `test_shadow_mode.py`, `MarketDataService`, `Post-Refactoring Architecture Review`, `test_worker_fencing.py`, `HyperliquidClient`, `test_regime_validation_engine.py`, `PaperExecutionAdapter`, `database.py`, `OllamaClient`, `below_min_order_notional`, `test_gap_cycle.py`, `pytest`, `test_decision_volume.py`, `test_adversarial_service.py`, `test_funding.py`, `test_untestable_agents.py`, `WorkerCycle`, `fitness_forward.py`, `conftest.py`, `test_council_integration.py`, `analytics.py`, `test_promotion_evidence.py`, `test_cooldown_limits.py`, `Position`, `FitnessInputs`, `test_min_notional_decision_time.py`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `Side` connect `Side` to `make_agents`, `sqlalchemy`, `config.py`, `decision_loop.py`, `BacktestResult`, `run_backtest`, `RiskDecision`, `cycle.py`, `test_reality_gap_engine.py`, `test_postgres_concurrency.py`, `helpers_agents.py`, `RuleSet`, `Agent`, `pipeline.py`, `test_experiment_runner.py`, `test_position_protection.py`, `StrategyStage`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_correlation.py`, `test_shadow_mode.py`, `Post-Refactoring Architecture Review`, `test_regime_validation_engine.py`, `PaperExecutionAdapter`, `test_db_constraints.py`, `database.py`, `test_fitness_edge_cases.py`, `below_min_order_notional`, `test_check_constraints_are_enforced_by_postgres_itself`, `test_as_of_boundaries.py`, `margin_state`, `Position`, `compute_and_persist_agent_fitness`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `Agent` connect `Agent` to `make_agents`, `sqlalchemy`, `test_promotion_service.py`, `runtime_status.py`, `decision_loop.py`, `RiskDecision`, `test_champion_challenger_service.py`, `test_reality_gap_engine.py`, `helpers_agents.py`, `pipeline.py`, `test_position_protection.py`, `StrategyStage`, `test_evolution_pipeline.py`, `test_frozen_oos_epoch.py`, `test_shadow_fitness.py`, `test_evolution_gate_and_champions.py`, `test_correlation.py`, `Post-Refactoring Architecture Review`, `test_worker_fencing.py`, `test_regime_validation_engine.py`, `test_db_constraints.py`, `shadow_fitness.py`, `database.py`, `test_fitness_edge_cases.py`, `below_min_order_notional`, `refresh_trade_analytics`, `test_untestable_agents.py`, `StrategyVersion`, `test_decision_loop_characterization.py`, `test_as_of_boundaries.py`, `shadow_rows_for_generation`, `analytics.py`, `test_promotion_evidence.py`, `test_breeding.py`, `Position`, `compute_and_persist_agent_fitness`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `get_settings()` (e.g. with `2. Current high-degree nodes` and `Intentional coupling (do not "fix")`) actually correct?**
  _`get_settings()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PaperExecutionAdapter` (e.g. with `1. Current Graphify statistics` and `2. Current high-degree nodes`) actually correct?**
  _`PaperExecutionAdapter` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 95 inferred relationships involving `Agent` (e.g. with `2. Current high-degree nodes` and `7. Agent/strategy boundaries`) actually correct?**
  _`Agent` has 95 INFERRED edges - model-reasoned connections that need verification._
- **Are the 81 inferred relationships involving `StrategyDNA` (e.g. with `2. Current high-degree nodes` and `3. Current cross-community bridge nodes`) actually correct?**
  _`StrategyDNA` has 81 INFERRED edges - model-reasoned connections that need verification._