"""Centralized application configuration.

Every environment-dependent value in the system must be read through this
module. Nothing here may hardcode a URL, API key, or credential — those come
exclusively from the environment (see `.env.example` at the repo root).
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
# Mirrors len(app.schemas.council.ANALYST_NAMES); importing that here would be circular
# (models -> database -> settings). tests/test_council_failclosed.py pins the two together.
COUNCIL_ANALYST_COUNT = 8


def resolve_sqlite_url(url: str) -> str:
    """Rewrite a RELATIVE sqlite file URL to an absolute one under BACKEND_DIR and create its folder.
    Absolute paths, in-memory databases and non-SQLite URLs are returned unchanged."""
    from sqlalchemy.engine import make_url

    if not url.startswith("sqlite"):
        return url
    parsed = make_url(url)
    db = parsed.database
    if not db or db == ":memory:" or db.startswith("file:"):
        return url
    path = Path(db)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return parsed.set(database=str(path)).render_as_string(hide_password=False)


class TradingMode(str, Enum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Trading mode ---------------------------------------------------
    trading_mode: TradingMode = TradingMode.PAPER
    # Provenance: overrides the git commit recorded on every experiment (containers without a .git directory).
    code_version: str = ""

    # --- Hyperliquid ------------------------------------------------------
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz"
    hyperliquid_ws_url: str = "wss://api.hyperliquid.xyz/ws"
    hyperliquid_account_address: str = ""
    hyperliquid_private_key: SecretStr = SecretStr("")
    market_symbol: str = "SOL"
    market_timeframe: str = "1m"
    # A candle is only "final" once its close time is at least this far in the
    # past — guards against a snapshot taken a few ms after the boundary that
    # still misses the last trades of the bar.
    candle_finality_grace_ms: int = 1500
    # After a candle boundary, poll until the exchange has published the
    # closed bar (bounded) instead of skipping it forever.
    candle_wait_deadline_seconds: float = 20.0
    candle_poll_interval_seconds: float = 1.0
    # A cycle that overran may leave several confirmed bars unprocessed; they
    # are replayed in order (exits/stops only) up to this many bars.
    max_catchup_bars: int = 5
    # Continuity is verified over this many trailing confirmed bars. An
    # unrecoverable hole halts NEW entries (never trade through a data gap).
    gap_check_window_bars: int = 300
    data_stale_threshold_seconds: int = 180
    # WebSocket is the primary real-time candle stream; REST stays for warm-up,
    # backfill and reconciliation and is always active as the fallback.
    market_ws_enabled: bool = True
    ws_ping_interval_seconds: float = 30.0
    ws_stale_after_seconds: float = 90.0
    # A frame whose bar opens further than this in the future is dropped (never becomes 'latest').
    ws_future_tolerance_ms: int = 5_000
    funding_history_lookback_hours: int = 48

    # --- Ollama -------------------------------------------------------------
    ollama_base_url: str = ""
    ollama_api_key: SecretStr = SecretStr("")
    # Optional: multiple keys (e.g. several free-tier accounts), comma-separated.
    # OllamaClient round-robins across these — every retry attempt picks the
    # next key, so a 429 on one key is transparently retried on the next
    # instead of just backing off on the same rate-limited key. Falls back
    # to the single `ollama_api_key` above when unset.
    ollama_api_keys: SecretStr = SecretStr("")
    ollama_model: str = ""
    ollama_timeout_seconds: int = 120
    ollama_max_retries: int = 3
    ollama_concurrency: int = 10
    # How often the worker re-reads OLLAMA_API_KEY(S) (0 disables); SIGHUP forces an immediate full reload.
    ollama_key_refresh_seconds: int = 300

    # Housekeeping: no-op decision rows (legacy) older than this many days are pruned by
    # `python -m scripts.prune_decisions`. Rows linked to an order/trade are NEVER pruned.
    decision_retention_days: int = 7

    # --- Worker ---------------------------------------------------------------
    worker_lease_ttl_seconds: int = 90
    worker_lease_heartbeat_seconds: int = 30

    # --- Population -----------------------------------------------------
    agent_count: int = 500
    agent_starting_balance: float = 100.0

    # --- Risk -------------------------------------------------------------
    max_leverage: float = 5.0
    max_position_size: float = 0.5   # max fraction of equity committed as MARGIN per position
    # Hard cap on gross exposure (notional / equity) regardless of leverage x margin:
    # equity being positive is never a licence for unlimited notional.
    max_exposure_multiple: float = 2.0
    # Pre-trade risk limit: the loss if the protective stop is hit may not exceed
    # this fraction of equity (notional is reduced to fit). Independent of the
    # DNA, so a fragile wide-stop/high-leverage DNA cannot bleed an account.
    max_loss_per_trade_fraction: float = 0.05
    max_drawdown: float = 0.30
    max_daily_loss: float = 0.10

    # --- Database -----------------------------------------------------------
    # All database files live in ONE folder: backend/data/  (relative SQLite paths are resolved
    # against the backend directory, never the current working directory).
    database_url: str = "sqlite+aiosqlite:///./data/trading_lab.db"
    database_url_sync: str = "sqlite:///./data/trading_lab.db"
    # Production: DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/trading_lab
    # (SQLite stays the default for local development and the test-suite.)
    # Sized against PostgreSQL's max_connections (default 100) for THREE processes (api, worker, research):
    # 3 x (pool_size + max_overflow) must stay well below it. See the startup check in `_check_pool_budget`.
    database_pool_size: int = 10
    database_max_overflow: int = 5
    database_server_max_connections: int = 100   # what your PostgreSQL is configured with (`SHOW max_connections`)
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    database_statement_timeout_ms: int = 30_000
    database_lock_timeout_ms: int = 10_000              # a statement waits at most this long for a row/table lock
    database_idle_in_transaction_timeout_ms: int = 120_000   # a forgotten open transaction is killed (it would hold locks)

    # --- Paper execution simulation ---------------------------------------
    paper_fee_rate: float = 0.00045            # taker
    paper_maker_fee_rate: float = 0.00015      # resting take-profit limit exits
    paper_slippage_bps: float = 2.0            # base adverse slippage on market orders
    # Extra adverse bps per $10k of notional (size-aware impact; 0 disables).
    paper_slippage_impact_bps_per_10k: float = 0.5
    # Stops/liquidations execute into a moving market: slippage is multiplied.
    paper_stop_slippage_multiplier: float = 2.0
    paper_latency_ms: int = 150
    paper_latency_jitter_ms: int = 50
    # Simulated latency is REPORTED (and can drift the price) without sleeping;
    # 500 sequential real sleeps would blow the 1-minute cycle budget.
    paper_simulate_latency_sleep: bool = False
    # Random adverse/favourable price drift per second of (simulated) latency between decision and fill.
    paper_latency_drift_bps_per_sec: float = 2.0
    paper_partial_fill_probability: float = 0.02
    paper_partial_fill_min_fraction: float = 0.5
    # Entries can be rejected by the exchange (exits never are: an agent must always be able to close).
    paper_reject_probability: float = 0.005
    # Hyperliquid's real minimum order value is $10; 0 disables the check.
    paper_min_order_notional: float = 10.0
    # An agent whose entry attempts are (almost) all refused by that minimum cannot produce trading evidence at its
    # capital: it is reported UNTESTABLE and excluded from survivor ranking (never penalised, never rewarded). It needs
    # at least `untestable_min_blocked_entries` blocked attempts, of which at least `untestable_blocked_share` of all
    # its entry attempts (blocked + executed). Nothing about its DNA, sizing, risk or status changes.
    untestable_min_blocked_entries: int = 20
    untestable_blocked_share: float = 0.95
    # When a paper/backtest entry FILLS relative to the bar that produced the signal:
    #   next_open    - an entry/exit decided on the CLOSE of bar N is a persisted PENDING order filled at the OPEN
    #                  of bar N+1 (the backtest's model: no signal-bar look-ahead). The research default.
    #   signal_close - fill at the signal bar's own close (kept for engines that model live submission, e.g. tests).
    # SHADOW always fills immediately against the live order book (that is what it exists to measure).
    paper_fill_timing: str = "next_open"
    # Trailing stops count the CURRENT bar's own extreme (worst-case path: rally first, then fall). False = prior bars only
    # (optimistic). Shared by paper, shadow and the backtest so they can never disagree.
    trailing_stop_uses_same_bar_extreme: bool = True
    # An agent that is flat and whose equity fell below this can never open another order (the minimum notional
    # and lot size make it untradeable): it is retired as DEAD instead of lingering as a zombie ACTIVE agent.
    agent_min_viable_equity: float = 1.0
    # A position whose exit order keeps failing (e.g. no book liquidity in SHADOW) is settled deterministically at
    # the modelled price after this many consecutive failed attempts, so an agent can never be stuck in a position.
    exit_force_settle_after_attempts: int = 3
    paper_quantity_step: float = 0.01          # lot size (SOL: 2 size decimals)
    paper_random_seed: int = 1337
    # Margin model (cross margin, one position per agent).
    maintenance_margin_rate: float = 0.025
    liquidation_fee_rate: float = 0.005        # penalty charged on the liquidated notional
    # A liquidated account is wiped out (remaining collateral ~ maintenance
    # margin): the agent dies permanently instead of lingering as a zombie.
    liquidation_is_fatal: bool = True
    # Death threshold: equity <= starting_balance * this fraction => DEAD.
    agent_bankruptcy_equity_fraction: float = 0.0
    # Volatility-based sizing: target ATR% per bar; scale clamped to [min, max].
    sizing_vol_target_atr_pct: float = 0.0008
    sizing_vol_scale_min: float = 0.25
    sizing_vol_scale_max: float = 2.0

    # --- Council / evolution -----------------------------------------------
    council_enabled: bool = True
    judge_enabled: bool = True
    evolution_enabled: bool = True
    council_interval_candles: int = 5
    council_consensus_margin: int = 2
    # Below this many successfully-responding analysts (of 8), the council
    # cycle is INCOMPLETE: final_bias forced to NEUTRAL, trade_allowed=False,
    # and the Risk Engine rejects any new entry for this candle. A partial
    # response (e.g. 5/8 after some analysts fail) must never be treated as
    # an ordinary full-strength consensus.
    council_min_successful_analysts: int = 6
    # How the council shapes (never dictates) an agent's decision:
    #  - opposed with confidence >= veto threshold -> entry vetoed;
    #  - opposed below it -> size reduced by penalty*confidence;
    #  - aligned -> size raised by bonus*confidence (still clamped by the Risk Engine);
    #  - council NEUTRAL -> size multiplied by the neutral modifier.
    council_veto_confidence: float = 0.60
    council_opposed_size_penalty: float = 0.50
    council_aligned_size_bonus: float = 0.15
    council_neutral_size_modifier: float = 0.75
    # Hard wall-clock budget for a whole council cycle (must be < candle interval).
    council_deadline_seconds: float = 45.0
    council_analyst_timeout_seconds: float = 30.0
    # Failsafe margin for the OUTER guard around the whole council step
    # (deadline + grace must also stay below the candle interval).
    council_outer_grace_seconds: float = 5.0
    evolution_interval_hours: int = 24
    # --- Research pipeline (scheduled evolution; only runs when enough data exists) ---
    research_window_candles: int = 20_160      # ~14 days of 1m bars per research epoch
    research_min_candles: int = 3_000          # below this the pipeline SKIPS (never guesses)
    research_train_fraction: float = 0.6
    # A strategy LINEAGE (a family of mutated/crossed descendants) may be evaluated against a sealed OOS holdout at most
    # this many times; more is adaptive tuning against the final test. Renewing the epoch (operator action) resets it.
    research_oos_max_evaluations_per_lineage: int = 3
    # Only a WARNING threshold: the sealed holdout ages as the market moves on; the operator decides when to renew it.
    research_epoch_max_age_days: float = 30.0
    research_validation_fraction: float = 0.2  # remaining 20% is the protected final OOS slice
    research_min_generation_age_hours: float = 12.0
    research_min_closed_trades: int = 30       # need real paper history before selecting on it
    research_survivor_fraction: float = 0.2
    research_adversarial_top_k: int = 25
    research_adversarial_bars: int = 1200
    research_candidate_min_trades: int = 3
    research_candidate_max_drawdown: float = 0.60
    research_max_child_attempts: int = 3
    research_poll_seconds: int = 300
    research_seed: int = 20260101

    # --- Fitness weights (configurable; every component is bounded, see fitness_engine) ---
    fitness_w_return: float = 1.0
    fitness_w_risk: float = 1.0
    fitness_w_consistency: float = 1.0
    fitness_w_robustness: float = 1.0
    fitness_w_oos: float = 1.5            # VALIDATION-slice out-of-sample score (never the final OOS)
    fitness_w_drawdown: float = 2.0
    fitness_w_instability: float = 1.0
    fitness_w_correlation: float = 0.3    # soft diversity pressure: lowers rank, never kills
    fitness_w_expectancy: float = 0.5
    fitness_w_regime: float = 1.0
    fitness_w_adversarial: float = 1.0
    fitness_w_inactivity: float = 0.25    # penalty x (1 - trade-count confidence): idleness is not a strategy
    fitness_w_death: float = 1.0          # extra penalty for an agent that died

    # --- Regime validation ----------------------------------------------------
    regime_validation_min_trades_per_regime: int = 10
    regime_validation_robust_min_positive_regimes_pct: float = 0.7
    regime_validation_specialist_min_pnl_share: float = 0.6

    # --- Strategy correlation ---------------------------------------------------
    max_strategy_correlation: float = 0.80
    min_strategy_diversity: float = 0.60
    correlation_lookback_days: int = 30
    correlation_time_bucket: str = "1h"
    max_family_survivor_fraction: float = 0.35
    correlation_diversity_pressure_enabled: bool = True

    # --- Reality gap ------------------------------------------------------------
    # Soft flag/report annotation only — champion/challenger evaluates the raw
    # per-metric numbers itself rather than a single pass/fail threshold here.
    reality_gap_max_acceptable_degradation_pct: float = 0.35
    # Two stages are only COMPARABLE (usable as promotion evidence) when both cover at least this much observed time and
    # this many trades: a multi-day backtest vs one day of paper is not reliable evidence of anything.
    reality_gap_min_observation_days: float = 2.0
    reality_gap_min_trades: int = 20

    # --- Champion/Challenger ------------------------------------------------
    champion_min_trade_count: int = 100
    champion_min_oos_score: float = 0.65
    champion_min_walk_forward_consistency: float = 0.6
    champion_max_drawdown: float = 0.25
    champion_min_profit_factor: float = 1.3
    champion_min_fitness_improvement: float = 0.05
    champion_min_stage_days: int = 14
    # Champions and challengers under observation are carried into the next generation unchanged (same strategy version,
    # fresh capital) - up to this many slots - so their track record can accumulate to a promotion decision.
    champion_elite_slots: int = 10
    champion_min_observation_days: int = 14
    champion_min_adversarial_robustness: float = 0.5
    champion_min_paper_trade_count: int = 30

    # --- Adversarial testing ------------------------------------------------
    adversarial_max_acceptable_drawdown: float = 0.40
    adversarial_min_acceptable_worst_case_return: float = -0.20
    adversarial_n_dna_variants: int = 5
    adversarial_fee_stress_multiplier: float = 2.0
    adversarial_slippage_stress_multiplier: float = 3.0
    # Scenario parameters (every stress scenario is configuration, not a buried constant). They are persisted with each
    # report (`scenario_config`) so a run can be reproduced exactly.
    adversarial_volatility_spike_magnitude: float = 3.0       # one candle's range x this
    adversarial_gap_pct: float = -0.08                        # permanent gap (negative = down)
    adversarial_stale_bars: int = 20                          # flat, zero-volume feed outage
    adversarial_extreme_move_pct: float = 0.25                # permanent flash-crash size (down)
    adversarial_volume_spike_magnitude: float = 5.0
    adversarial_liquidity_reduction: float = 0.05             # volume collapses to this fraction
    adversarial_missing_candle_fraction: float = 0.02
    adversarial_duplicate_candle_fraction: float = 0.02
    adversarial_execution_delay_bars: int = 3
    adversarial_partial_fill_fraction: float = 0.5
    adversarial_reject_probability: float = 0.3

    # --- Live trading safety gates -------------------------------------------
    # Shadow mode: real order-book data, hypothetical fills, NO orders ever sent.
    shadow_assumed_latency_ms: int = 250      # order-to-book latency we would face live
    shadow_book_ttl_seconds: float = 2.0      # one book snapshot serves every agent in a cycle
    shadow_max_book_levels: int = 20
    # Live trading stays blocked until an operator explicitly signs off the launch
    # checklist (exchange integration tested on testnet, reconciliation, idempotency
    # test, emergency stop, auth, secrets) — on top of every gate below.
    live_prerequisites_signed_off: bool = False
    live_trading_enabled: bool = False
    live_account_confirmed: bool = False
    load_agent_snapshot: str = ""

    # --- Logging --------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    # --- API --------------------------------------------------------------
    # Loopback by default; exposing the API on a public interface must be a
    # deliberate deployment decision (set API_HOST explicitly behind TLS).
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    # Fail closed: with auth required and no API_KEYS configured, every
    # protected request is rejected. Format: name:role:sha256hex[,...]
    # (see `python -m scripts.hash_api_key`). Roles: viewer|researcher|operator|admin.
    api_auth_required: bool = True
    api_keys: SecretStr = SecretStr("")
    # Brute-force / abuse protection (in-process; behind a reverse proxy the client
    # address is the proxy's, so also rate-limit at the proxy).
    api_auth_max_failures: int = 10           # failed auths per client within the window => lockout
    api_auth_failure_window_seconds: int = 300
    api_auth_lockout_seconds: int = 300
    api_rate_limit_per_minute: int = 600      # authenticated requests per principal per minute; 0 disables
    api_max_sse_streams: int = 20             # concurrent /api/stream connections (all principals)
    api_max_sse_streams_per_principal: int = 5
    api_sse_max_age_seconds: int = 3600       # server closes a stream after this long; clients reconnect
    # OpenAPI/Swagger reveal the full API surface; off unless explicitly enabled.
    expose_api_docs: bool = False

    @model_validator(mode="after")
    def _anchor_sqlite_paths(self) -> "Settings":
        """Relative SQLite paths resolve against backend/ (not the CWD) and their folder is created,
        so the app, alembic, scripts and tests all use the SAME file no matter where they are launched."""
        self.database_url = resolve_sqlite_url(self.database_url)
        self.database_url_sync = resolve_sqlite_url(self.database_url_sync)
        return self

    @model_validator(mode="after")
    def _council_settings_are_coherent(self) -> "Settings":
        """A council that cannot possibly reach quorum, or that may outlive its own candle,
        is a misconfiguration that would silently turn trading off (or apply stale calls)."""
        if not 1 <= self.council_min_successful_analysts <= COUNCIL_ANALYST_COUNT:
            raise ValueError(f"council_min_successful_analysts must be within 1..{COUNCIL_ANALYST_COUNT}")
        if self.council_deadline_seconds <= 0 or self.council_analyst_timeout_seconds <= 0:
            raise ValueError("council deadlines must be positive")
        unit = {"s": 1, "m": 60, "h": 3600}.get(self.market_timeframe[-1:], None)
        digits = self.market_timeframe[:-1]
        if self.council_enabled and unit and digits.isdigit():
            interval = int(digits) * unit
            if self.council_deadline_seconds + self.council_outer_grace_seconds >= interval:
                raise ValueError(
                    "council_deadline_seconds + council_outer_grace_seconds must be below the candle interval "
                    f"({interval}s): a late council decision must never be applied to a newer candle"
                )
        return self

    @model_validator(mode="after")
    def _check_pool_budget(self) -> "Settings":
        """Three processes share the database. If their pools alone could exceed the server's connection limit, a busy
        moment turns into 'too many clients' errors (and the lease heartbeat is what dies first)."""
        if self.database_url.startswith("postgresql"):
            worst_case = 3 * (self.database_pool_size + self.database_max_overflow)
            if worst_case > 0.9 * self.database_server_max_connections:
                raise ValueError(
                    f"database pools can open up to {worst_case} connections across api+worker+research, which exceeds 90% of "
                    f"DATABASE_SERVER_MAX_CONNECTIONS={self.database_server_max_connections}; lower DATABASE_POOL_SIZE / "
                    "DATABASE_MAX_OVERFLOW or raise max_connections"
                )
        return self

    @field_validator("paper_fill_timing")
    @classmethod
    def _known_fill_timing(cls, v: str) -> str:
        if v not in ("next_open", "signal_close"):
            raise ValueError("paper_fill_timing must be 'next_open' or 'signal_close'")
        return v

    @field_validator("agent_count")
    @classmethod
    def _positive_agent_count(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("agent_count must be positive")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ollama_api_key_list(self) -> list[str]:
        keys = [k.strip() for k in self.ollama_api_keys.get_secret_value().split(",") if k.strip()]
        single = self.ollama_api_key.get_secret_value().strip()
        if not keys and single:
            keys = [single]
        return keys

    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    def live_safety_ok(self) -> bool:
        """All gates required by spec section 40 before ANY live order.

        This does not check market-data freshness or DB health — those are
        runtime conditions checked by the risk engine on every cycle, not at
        startup. This only checks the static configuration gates.
        """
        if not self.is_live():
            return True
        return bool(
            self.live_trading_enabled
            and self.live_prerequisites_signed_off
            and self.live_account_confirmed
            and self.load_agent_snapshot
            and self.hyperliquid_account_address
            and self.hyperliquid_private_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
