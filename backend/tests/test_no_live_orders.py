"""FINAL SAFETY PROOF (spec phase 32): TRADING_MODE=paper cannot send a real order, and the live path stays blocked.

Two independent kinds of evidence: (1) static - no module contains order-sending, request-signing or wallet code; (2)
dynamic - every outbound HTTP request made while running real paper cycles, a council and a shadow fill is recorded and
must hit an allow-listed READ-ONLY endpoint."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings, TradingMode, get_settings
from app.execution.base import ExecutionRequest
from app.execution.live_adapter import HyperliquidLiveExecutionAdapter
from app.execution.paper_adapter import PaperExecutionAdapter
from app.execution.router import LiveSafetyGateError, get_execution_engine
from app.execution.shadow_adapter import ShadowExecutionAdapter
from app.models.enums import Side

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

# The ONLY outbound endpoints the system may call. Hyperliquid /info is a read-only query endpoint; /api/chat is Ollama.
ALLOWED_PATHS = {"/info", "/api/chat"}

FORBIDDEN_MARKERS = [
    r"/exchange\b",                    # Hyperliquid's order/cancel/transfer endpoint
    r"sign_l1_action", r"sign_user_signed_action", r"eth_account", r"\bweb3\b", r"from eth_", r"import eth_",
    r"Account\.from_key", r"\.sign_message", r"encode_typed_data", r"keccak", r"secp256k1", r"\bcloid\b",
    r"\"type\"\s*:\s*\"(order|cancel|cancelByCloid|modify|updateLeverage|withdraw3|usdSend|spotSend)\"",
]


def code_only(text: str) -> str:
    """Executable code only: docstrings (AST) and comments (tokenize) are blanked, so prose that DOCUMENTS the
    prohibition ("EIP-712 signing is intentionally not implemented") cannot trip the scan, while a real string such as
    "/exchange" passed to a call still would."""
    import ast
    import io
    import tokenize

    lines = text.splitlines()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                for i in range(first.lineno - 1, first.end_lineno):
                    lines[i] = ""
    out = "\n".join(lines)
    for tok in tokenize.generate_tokens(io.StringIO(out).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            ls = out.split("\n")
            ls[row - 1] = ls[row - 1][:col]
            out = "\n".join(ls)
    return out


def _sources():
    for base in ("app", "scripts"):
        for p in (BACKEND / base).rglob("*.py"):
            yield p, code_only(p.read_text())


def test_no_module_contains_order_sending_signing_or_wallet_code():
    offenders = []
    for path, text in _sources():
        for pat in FORBIDDEN_MARKERS:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                snippet = text.splitlines()[line - 1].strip()
                offenders.append(f"{path.relative_to(BACKEND)}:{line}: {snippet[:100]}")
    assert not offenders, offenders


def test_no_signing_or_web3_dependency_exists():
    reqs = (BACKEND / "requirements.txt").read_text().lower()
    for lib in ("eth-account", "eth_account", "web3", "hyperliquid-python-sdk", "hyperliquid", "coincurve", "eth-keys", "pycryptodome"):
        assert lib not in reqs, lib


def test_every_http_post_in_the_codebase_targets_an_allowlisted_endpoint_or_is_internal():
    """`.post(` call sites outside tests: exactly the two known clients (plus FastAPI's own route decorators)."""
    posts = {}
    for path, text in _sources():
        rel = str(path.relative_to(BACKEND))
        for line in text.splitlines():
            if re.search(r"\.post\(", line) and "@router.post" not in line and "@app.post" not in line:
                posts.setdefault(rel, []).append(line.strip())
    assert set(posts) <= {"app/market/hyperliquid_client.py", "app/services/ollama_client.py"}, posts
    hl = " ".join(posts.get("app/market/hyperliquid_client.py", []))
    assert "/info" in hl and "/exchange" not in hl
    assert all('"/api/chat"' in l for l in posts.get("app/services/ollama_client.py", []))


def test_the_default_and_every_deployment_artifact_is_paper():
    assert Settings.model_fields["trading_mode"].default == TradingMode.PAPER
    env = (ROOT / ".env.example").read_text()
    assert re.search(r"^TRADING_MODE=paper\s*$", env, re.M)
    for unit in (ROOT / "docs" / "systemd").glob("*.service"):
        assert "TRADING_MODE=live" not in unit.read_text().replace(" ", ""), unit.name
    for gate in ("LIVE_TRADING_ENABLED", "LIVE_ACCOUNT_CONFIRMED", "LIVE_PREREQUISITES_SIGNED_OFF"):
        assert re.search(rf"^{gate}=false\s*$", env, re.M), gate


# --- dynamic evidence: record every outbound request ---------------------------------------------------------------------------------


@pytest.fixture
def recorded_requests(monkeypatch):
    seen: list[tuple[str, str]] = []
    real_send = httpx.AsyncClient.send

    async def spy(self, request, **kw):
        seen.append((request.method, request.url.path))
        return await real_send(self, request, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "send", spy)
    return seen


@pytest.mark.usefixtures("immediate_fills")
async def test_paper_cycles_with_a_council_only_ever_touch_read_endpoints(db_session, recorded_requests, monkeypatch):
    from app.market.market_data_service import MarketDataService
    from app.models.trading import Order
    from app.services.ollama_client import OllamaClient, OllamaKeyHealth
    from app.worker import cycle as cycle_mod
    from sqlalchemy import select
    from tests.helpers_market import FakeHyperliquid, clock_after_bar
    from tests.test_council_failclosed import _seed_always_long_population

    s = get_settings()
    assert s.trading_mode == TradingMode.PAPER
    monkeypatch.setattr(s, "council_enabled", True)
    monkeypatch.setattr(s, "council_interval_candles", 1)
    monkeypatch.setattr(s, "paper_latency_ms", 0)

    def ollama(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = next((n for n in ("trend", "momentum", "structure", "order_flow", "volatility", "regime", "risk", "contrarian")
                     if f"{n} analyst" in body["messages"][0]["content"]), "trend")
        return httpx.Response(200, json={"message": {"content": json.dumps({"analyst": name, "bias": "LONG", "confidence": 0.8,
                                                                            "reasoning": "ok", "key_factors": [], "invalidators": []})}})

    client = OllamaClient()
    client._api_keys, client._key_health = ["k"], [OllamaKeyHealth()]
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(ollama), base_url="http://ollama.invalid")

    fake = FakeHyperliquid(n_candles=400)                         # stands in for HyperliquidClient (no network at all)
    market = MarketDataService(fake, clock_ms=lambda: clock_after_bar(399))
    await _seed_always_long_population(db_session, n=3)
    await market.sync_recent_candles(db_session, lookback_candles=400)
    out = await cycle_mod.run_pending_cycles(db_session, market, client, execution_engine=PaperExecutionAdapter())
    assert out[0].status == "COMPLETED"
    assert len((await db_session.execute(select(Order))).scalars().all()) == 3          # orders were placed - on PAPER

    assert recorded_requests, "the council should have called the (mock) Ollama endpoint"
    assert {p for _, p in recorded_requests} <= ALLOWED_PATHS, recorded_requests
    assert all(m == "POST" and p == "/api/chat" for m, p in recorded_requests)          # and NOTHING else, no /exchange
    await client.aclose()


async def test_the_real_hyperliquid_client_only_posts_to_info(monkeypatch):
    from app.market.hyperliquid_client import HyperliquidClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content).get("type")))
        return httpx.Response(200, json=[])

    c = HyperliquidClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.hyperliquid.xyz")
    for call in (lambda: c.get_candles("SOL", "1m", 0, 60_000), lambda: c.get_funding_history("SOL", 0), lambda: c.get_l2_book("SOL")):
        try:
            await call()
        except Exception:
            pass          # the response shape does not matter; the destination does
    assert seen and all(m == "POST" and p == "/info" for m, p, _ in seen), seen
    assert {t for _, _, t in seen} <= {"candleSnapshot", "fundingHistory", "l2Book", "metaAndAssetCtxs"}
    await c.aclose()


# --- the execution router --------------------------------------------------------------------------------------------------------------


def test_paper_and_shadow_modes_get_non_live_engines():
    assert isinstance(get_execution_engine(Settings(trading_mode="paper")), PaperExecutionAdapter)
    shadow = get_execution_engine(Settings(trading_mode="shadow"))
    assert isinstance(shadow, ShadowExecutionAdapter) and not isinstance(shadow, HyperliquidLiveExecutionAdapter)


ALL_GATES = dict(trading_mode="live", live_trading_enabled=True, live_prerequisites_signed_off=True, live_account_confirmed=True,
                 load_agent_snapshot="snap", hyperliquid_account_address="0xabc", hyperliquid_private_key="secret")


def test_live_mode_is_refused_unless_every_gate_is_set():
    for missing in ("live_trading_enabled", "live_prerequisites_signed_off", "live_account_confirmed", "load_agent_snapshot",
                    "hyperliquid_account_address", "hyperliquid_private_key"):
        cfg = dict(ALL_GATES)
        cfg[missing] = "" if isinstance(cfg[missing], str) else False
        with pytest.raises(LiveSafetyGateError):
            get_execution_engine(Settings(**cfg))


async def test_even_with_every_gate_open_the_live_adapter_cannot_place_an_order(recorded_requests):
    engine = get_execution_engine(Settings(**ALL_GATES))
    assert isinstance(engine, HyperliquidLiveExecutionAdapter)
    req = ExecutionRequest(client_order_id="x", agent_id="a", symbol="SOL", side=Side.LONG, quantity=1.0, leverage=1.0, reference_price=100.0)
    with pytest.raises(NotImplementedError):
        await engine.submit_order(req)
    assert recorded_requests == []                                   # not a single byte left the process


def test_the_live_adapter_never_uses_the_private_key():
    import ast

    tree = ast.parse((BACKEND / "app/execution/live_adapter.py").read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"httpx", "requests", "aiohttp", "websockets", "eth_account", "web3", "hmac", "hashlib", "ecdsa"}, imported
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not [i for i in identifiers if "sign" in i.lower() and i.lower() != "assign"], identifiers
    # the only thing submit_order does is refuse
    submit = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "submit_order")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(submit)) and not any(isinstance(n, ast.Await) for n in ast.walk(submit))


def test_the_scanner_itself_catches_real_violations_but_ignores_documentation():
    assert "/exchange" not in code_only('''"""EIP-712 signing of the /exchange payload is not implemented."""\n# also /exchange in a comment\nx = 1\n''')
    assert "/exchange" in code_only('''def go(c):\n    return c.post("/exchange", json={})\n''')
    assert re.search(FORBIDDEN_MARKERS[0], code_only('''URL = "https://api.hyperliquid.xyz/exchange"\n'''))
