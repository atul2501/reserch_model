"""Centralized application configuration.

Every environment-dependent value in the system must be read through this
module. Nothing here may hardcode a URL, API key, or credential — those come
exclusively from the environment (see `.env.example` at the repo root).
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


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

    # --- Hyperliquid ------------------------------------------------------
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz"
    hyperliquid_ws_url: str = "wss://api.hyperliquid.xyz/ws"
    hyperliquid_account_address: str = ""
    hyperliquid_private_key: str = ""
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
    funding_history_lookback_hours: int = 48

    # --- Ollama -------------------------------------------------------------
    ollama_base_url: str = ""
    ollama_api_key: str = ""
    # Optional: multiple keys (e.g. several free-tier accounts), comma-separated.
    # OllamaClient round-robins across these — every retry attempt picks the
    # next key, so a 429 on one key is transparently retried on the next
    # instead of just backing off on the same rate-limited key. Falls back
    # to the single `ollama_api_key` above when unset.
    ollama_api_keys: str = ""
    ollama_model: str = ""
    ollama_timeout_seconds: int = 120
    ollama_max_retries: int = 3
    ollama_concurrency: int = 10

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
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    database_statement_timeout_ms: int = 30_000

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
    paper_latency_drift_bps_per_sec: float = 0.0
    paper_partial_fill_probability: float = 0.0
    paper_partial_fill_min_fraction: float = 0.5
    paper_reject_probability: float = 0.0
    # Hyperliquid's real minimum order value is $10; 0 disables the check.
    paper_min_order_notional: float = 0.0
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
    evolution_interval_hours: int = 24
    # --- Research pipeline (scheduled evolution; only runs when enough data exists) ---
    research_window_candles: int = 20_160      # ~14 days of 1m bars per research epoch
    research_min_candles: int = 3_000          # below this the pipeline SKIPS (never guesses)
    research_train_fraction: float = 0.6
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

    # --- Professional classification ----------------------------------------
    pro_min_trades: int = 200
    pro_min_profit_factor: float = 1.5
    pro_max_drawdown: float = 0.20
    pro_min_oos_score: float = 0.70

    # --- Regime validation ----------------------------------------------------
    regime_validation_min_trades_per_regime: int = 10
    regime_validation_robust_min_positive_regimes_pct: float = 0.7
    regime_validation_specialist_min_pnl_share: float = 0.6

    # --- Strategy correlation ---------------------------------------------------
    max_strategy_correlation: float = 0.80
    max_return_correlation: float = 0.80
    min_strategy_diversity: float = 0.60
    correlation_lookback_days: int = 30
    correlation_time_bucket: str = "1h"
    max_family_survivor_fraction: float = 0.35
    correlation_diversity_pressure_enabled: bool = True

    # --- Reality gap ------------------------------------------------------------
    # Soft flag/report annotation only — champion/challenger evaluates the raw
    # per-metric numbers itself rather than a single pass/fail threshold here.
    reality_gap_max_acceptable_degradation_pct: float = 0.35

    # --- Champion/Challenger ------------------------------------------------
    champion_min_trade_count: int = 100
    champion_min_oos_score: float = 0.65
    champion_min_walk_forward_consistency: float = 0.6
    champion_max_drawdown: float = 0.25
    champion_min_profit_factor: float = 1.3
    champion_min_fitness_improvement: float = 0.05
    champion_min_stage_days: int = 14
    champion_min_observation_days: int = 14
    champion_min_adversarial_robustness: float = 0.5
    champion_min_paper_trade_count: int = 30

    # --- Adversarial testing ------------------------------------------------
    adversarial_max_acceptable_drawdown: float = 0.40
    adversarial_min_acceptable_worst_case_return: float = -0.20
    adversarial_n_dna_variants: int = 5
    adversarial_fee_stress_multiplier: float = 2.0
    adversarial_slippage_stress_multiplier: float = 3.0
    adversarial_partial_fill_min_pct: float = 0.3
    adversarial_execution_delay_jitter_ms: int = 500

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
    api_keys: str = ""

    @model_validator(mode="after")
    def _anchor_sqlite_paths(self) -> "Settings":
        """Relative SQLite paths resolve against backend/ (not the CWD) and their folder is created,
        so the app, alembic, scripts and tests all use the SAME file no matter where they are launched."""
        self.database_url = resolve_sqlite_url(self.database_url)
        self.database_url_sync = resolve_sqlite_url(self.database_url_sync)
        return self

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
        keys = [k.strip() for k in self.ollama_api_keys.split(",") if k.strip()]
        if not keys and self.ollama_api_key:
            keys = [self.ollama_api_key]
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
            and self.hyperliquid_private_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
