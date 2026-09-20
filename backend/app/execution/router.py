"""Selects the correct ExecutionEngine for the configured TRADING_MODE and
enforces the live safety gates (spec section 40) before a live adapter is
ever constructed.
"""
from __future__ import annotations

from app.core.config import Settings, TradingMode, get_settings
from app.execution.base import ExecutionEngine
from app.execution.live_adapter import HyperliquidLiveExecutionAdapter
from app.execution.paper_adapter import PaperExecutionAdapter
from app.execution.shadow_adapter import ShadowExecutionAdapter


class LiveSafetyGateError(RuntimeError):
    pass


def get_execution_engine(settings: Settings | None = None) -> ExecutionEngine:
    settings = settings or get_settings()

    if settings.trading_mode == TradingMode.PAPER:
        return PaperExecutionAdapter()

    if settings.trading_mode == TradingMode.SHADOW:
        return ShadowExecutionAdapter()

    if settings.trading_mode == TradingMode.LIVE:
        if not settings.live_safety_ok():
            raise LiveSafetyGateError(
                "TRADING_MODE=live but one or more safety gates are not satisfied: "
                "LIVE_TRADING_ENABLED, LIVE_ACCOUNT_CONFIRMED, LOAD_AGENT_SNAPSHOT, "
                "HYPERLIQUID_ACCOUNT_ADDRESS, HYPERLIQUID_PRIVATE_KEY must all be set. "
                "No new trades will be placed until every gate passes."
            )
        return HyperliquidLiveExecutionAdapter(
            settings.hyperliquid_account_address, settings.hyperliquid_private_key
        )

    raise ValueError(f"unknown trading mode: {settings.trading_mode}")
