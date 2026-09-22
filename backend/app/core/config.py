"""Centralized application configuration.

Every environment-dependent value in the system must be read through this
module. Nothing here may hardcode a URL, API key, or credential — those come
exclusively from the environment (see `.env.example` at the repo root).
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Population -----------------------------------------------------
    agent_count: int = 500
    agent_starting_balance: float = 100.0

    # --- Risk -------------------------------------------------------------
    max_leverage: float = 5.0
    max_position_size: float = 0.5
    max_drawdown: float = 0.30
    max_daily_loss: float = 0.10

    # --- Database -----------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./trading_lab.db"
    database_url_sync: str = "sqlite:///./trading_lab.db"

    # --- Paper execution simulation ---------------------------------------
    paper_fee_rate: float = 0.00045
    paper_slippage_bps: float = 2.0
    paper_latency_ms: int = 150

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
    evolution_interval_hours: int = 24

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

    # --- Adversarial testing ------------------------------------------------
    adversarial_max_acceptable_drawdown: float = 0.40
    adversarial_min_acceptable_worst_case_return: float = -0.20
    adversarial_n_dna_variants: int = 5
    adversarial_fee_stress_multiplier: float = 2.0
    adversarial_slippage_stress_multiplier: float = 3.0
    adversarial_partial_fill_min_pct: float = 0.3
    adversarial_execution_delay_jitter_ms: int = 500

    # --- Live trading safety gates -------------------------------------------
    live_trading_enabled: bool = False
    live_account_confirmed: bool = False
    load_agent_snapshot: str = ""

    # --- Logging --------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    # --- API --------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

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
            and self.live_account_confirmed
            and self.load_agent_snapshot
            and self.hyperliquid_account_address
            and self.hyperliquid_private_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
