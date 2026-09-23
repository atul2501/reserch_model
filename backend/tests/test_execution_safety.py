"""Paper mode must NEVER send real orders; live mode must require explicit
activation (spec section 45 "Safety")."""
from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings, TradingMode
from app.execution.base import ExecutionRequest
from app.execution.live_adapter import HyperliquidLiveExecutionAdapter
from app.execution.paper_adapter import PaperExecutionAdapter, new_client_order_id
from app.execution.router import LiveSafetyGateError, get_execution_engine
from app.models.enums import OrderStatus, Side


@pytest.mark.asyncio
async def test_paper_adapter_never_makes_network_calls(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("PaperExecutionAdapter must never perform a real network request")

    monkeypatch.setattr(httpx.AsyncClient, "request", _fail_if_called)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fail_if_called)
    monkeypatch.setattr(httpx.AsyncClient, "get", _fail_if_called)

    adapter = PaperExecutionAdapter()
    request = ExecutionRequest(
        client_order_id=new_client_order_id("agent-1", "decision-1"),
        agent_id="agent-1",
        symbol="SOL",
        side=Side.LONG,
        quantity=1.0,
        leverage=1.0,
        reference_price=150.0,
    )
    result = await adapter.submit_order(request)
    assert result.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_paper_adapter_applies_fees_and_slippage():
    adapter = PaperExecutionAdapter()
    request = ExecutionRequest(
        client_order_id=new_client_order_id("agent-2", "decision-1"),
        agent_id="agent-2",
        symbol="SOL",
        side=Side.LONG,
        quantity=2.0,
        leverage=1.0,
        reference_price=100.0,
    )
    result = await adapter.submit_order(request)
    assert result.fee > 0
    assert result.filled_price != 100.0  # slippage was applied
    assert result.slippage_cost > 0


@pytest.mark.asyncio
async def test_duplicate_client_order_id_is_rejected_not_double_filled():
    adapter = PaperExecutionAdapter()
    request = ExecutionRequest(
        client_order_id=new_client_order_id("agent-3", "decision-dup"),
        agent_id="agent-3",
        symbol="SOL",
        side=Side.LONG,
        quantity=1.0,
        leverage=1.0,
        reference_price=100.0,
    )
    first = await adapter.submit_order(request)
    second = await adapter.submit_order(request)
    assert first.status == OrderStatus.FILLED
    assert second.status == OrderStatus.FAILED
    assert second.rejection_reason == "duplicate_client_order_id"


def test_router_returns_paper_adapter_in_paper_mode():
    settings = Settings(trading_mode=TradingMode.PAPER)
    engine = get_execution_engine(settings)
    assert isinstance(engine, PaperExecutionAdapter)


def test_router_refuses_live_mode_without_safety_gates():
    settings = Settings(
        trading_mode=TradingMode.LIVE,
        live_trading_enabled=False,
        live_account_confirmed=False,
    )
    with pytest.raises(LiveSafetyGateError):
        get_execution_engine(settings)


def test_router_refuses_live_mode_missing_snapshot():
    settings = Settings(
        trading_mode=TradingMode.LIVE,
        live_trading_enabled=True,
        live_account_confirmed=True,
        load_agent_snapshot="",
        hyperliquid_account_address="0xabc",
        hyperliquid_private_key="secret",
    )
    with pytest.raises(LiveSafetyGateError):
        get_execution_engine(settings)


def test_router_allows_live_mode_only_when_every_gate_passes():
    settings = Settings(
        trading_mode=TradingMode.LIVE,
        live_trading_enabled=True,
        live_prerequisites_signed_off=True,
        live_account_confirmed=True,
        load_agent_snapshot="snap-1",
        hyperliquid_account_address="0xabc",
        hyperliquid_private_key="secret",
    )
    engine = get_execution_engine(settings)
    assert isinstance(engine, HyperliquidLiveExecutionAdapter)


@pytest.mark.asyncio
async def test_live_adapter_refuses_to_place_orders_when_not_implemented():
    adapter = HyperliquidLiveExecutionAdapter("0xabc", "secret")
    request = ExecutionRequest(
        client_order_id="x",
        agent_id="agent-1",
        symbol="SOL",
        side=Side.LONG,
        quantity=1.0,
        leverage=1.0,
        reference_price=100.0,
    )
    with pytest.raises(NotImplementedError):
        await adapter.submit_order(request)
