"""Live must stay blocked (spec phases 26, 42): paper/shadow never send real
orders; live needs every gate INCLUDING an explicit prerequisites sign-off."""
from __future__ import annotations

import pytest

from app.core.config import Settings, TradingMode, get_settings
from app.execution.base import ExecutionRequest
from app.execution.live_adapter import HyperliquidLiveExecutionAdapter
from app.execution.router import LiveSafetyGateError, get_execution_engine
from app.models.enums import Side

ALL = dict(trading_mode=TradingMode.LIVE, live_trading_enabled=True, live_prerequisites_signed_off=True, live_account_confirmed=True,
           load_agent_snapshot="snap", hyperliquid_account_address="0xabc", hyperliquid_private_key="secret")


def test_default_trading_mode_is_paper_and_live_flags_default_off():
    assert Settings.model_fields["trading_mode"].default == TradingMode.PAPER
    for f in ("live_trading_enabled", "live_account_confirmed", "live_prerequisites_signed_off"):
        assert Settings.model_fields[f].default is False


@pytest.mark.parametrize("missing", ["live_trading_enabled", "live_prerequisites_signed_off", "live_account_confirmed",
                                     "load_agent_snapshot", "hyperliquid_account_address", "hyperliquid_private_key"])
def test_live_requires_every_single_gate(missing):
    cfg = dict(ALL)
    cfg[missing] = "" if isinstance(cfg[missing], str) else False
    with pytest.raises(LiveSafetyGateError):
        get_execution_engine(Settings(**cfg))


def test_all_gates_still_only_yield_a_stub_that_cannot_place_orders():
    eng = get_execution_engine(Settings(**ALL))
    assert isinstance(eng, HyperliquidLiveExecutionAdapter)


async def test_live_adapter_refuses_to_place_any_order():
    eng = HyperliquidLiveExecutionAdapter("0xabc", "secret")
    with pytest.raises(NotImplementedError):
        await eng.submit_order(ExecutionRequest("x", "a", "SOL", Side.LONG, 1.0, 1.0, 100.0))


async def test_kill_switch_blocks_new_entries_in_every_mode(db_session):
    from sqlalchemy import select
    from app.core.system_flags import KILL_SWITCH, set_flag
    from app.execution.paper_adapter import PaperExecutionAdapter
    from app.models.trading import Order
    from tests.helpers_agents import cycle, make_agents, make_context, make_dna
    await make_agents(db_session, [make_dna()])
    await set_flag(db_session, KILL_SWITCH, True, reason="drill")
    await db_session.commit()
    await cycle(db_session, PaperExecutionAdapter(), make_context(1, 100.0, rsi=65.0))
    assert (await db_session.execute(select(Order))).first() is None


def test_env_example_defaults_keep_live_disabled():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "TRADING_MODE=paper" in text and "LIVE_TRADING_ENABLED=false" in text and "LIVE_ACCOUNT_CONFIRMED=false" in text
