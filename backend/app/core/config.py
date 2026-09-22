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
    evolution_interval_hours: int = 24

    # --- Professional classification ----------------------------------------
    pro_min_trades: int = 200
    pro_min_profit_factor: float = 1.5
    pro_max_drawdown: float = 0.20
    pro_min_oos_score: float = 0.70

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
