"""The dashboard's script must not introduce XSS from API text and must shout
when the worker is down (spec phases 35-36). Runs the real page script in a
stubbed DOM under Node (skipped if Node is unavailable)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
SCRIPT = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HARNESS = r"""
const vm = require('vm'); const fs = require('fs');
const els = {};
const mk = (id) => els[id] || (els[id] = {id, innerHTML: '', textContent: '', style: {}, className: '', dataset: {}, value: '',
  addEventListener(){}, querySelector(){ return mk(id + '>q'); }, getBoundingClientRect(){ return {width: 300, height: 100}; }, setAttribute(){}, });
const document = { getElementById: mk, querySelector: (s) => mk('q:' + s), querySelectorAll: () => [], addEventListener(){},
                   createElement: () => mk('created') };
const ctx = { document, window: {}, sessionStorage: {getItem(){return 'k'}, setItem(){}, removeItem(){}}, console: {log(){}, warn(){}, error(){}},
              fetch: () => Promise.reject(new Error('offline')), setInterval(){}, setTimeout(){}, Date, Math, JSON, Promise, TextDecoder, encodeURIComponent, Number, String, Object, Array, isNaN };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
out.esc = ctx.esc(input.evil);
ctx.renderHealth(input.status);
out.banner = els['alert-banner'];
out.health = els['health-panel'].innerHTML;
process.stdout.write(JSON.stringify(out));
"""


def run(payload: dict, tmp_path: Path) -> dict:
    js = tmp_path / "page.js"
    js.write_text(SCRIPT)
    h = tmp_path / "h.js"
    h.write_text(HARNESS)
    r = subprocess.run(["node", str(h), str(js)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def status(worker="ok", db="ok", market="ok", ollama="ok", flags=None, key_status="healthy"):
    return {"database": {"status": db, "dialect": "postgresql"}, "trading_mode": "paper", "flags": flags or {},
            "worker": {"status": worker, "heartbeat_age_seconds": 12 if worker == "ok" else 400,
                       "last_cycle": {"status": "COMPLETED", "completed_age_seconds": 3, "latency_seconds": 4.2, "agents_processed": 500}},
            "market_data": {"status": market, "symbol": "SOL", "timeframe": "1m", "freshness_seconds": 5,
                            "last_confirmed_candle_open_time": 1_700_000_040_000},
            "hyperliquid": {"status": "ok", "websocket": {"connected": True, "stale": False, "reconnects": 0, "duplicates": 0}, "rest_fallback": True},
            "ollama": {"status": ollama, "keys": [{"key_index": 0, "status": key_status, "last_error_status": 401 if key_status != "healthy" else None}]},
            "council": {"status": "COMPLETE"}}


def test_esc_neutralises_markup_from_api_text(tmp_path):
    out = run({"evil": "<img src=x onerror=alert(1)>\"'&", "status": status()}, tmp_path)
    assert "<" not in out["esc"] and "&lt;img" in out["esc"] and "&quot;" in out["esc"] and "&amp;" in out["esc"]


def test_healthy_system_shows_all_components_and_no_banner(tmp_path):
    out = run({"evil": "", "status": status()}, tmp_path)
    for label in ("Worker", "Database", "Market data", "Hyperliquid stream", "Ollama", "Council"):
        assert label in out["health"]
    assert out["banner"]["style"]["display"] == "none"
    assert "4.20s" in out["health"] and "500" in out["health"]      # cycle latency + agents processed are visible


def test_worker_down_raises_a_loud_banner(tmp_path):
    out = run({"evil": "", "status": status(worker="down")}, tmp_path)
    assert out["banner"]["style"]["display"] == "block"
    assert "TRADING WORKER IS NOT RUNNING" in out["banner"]["innerHTML"] and out["banner"]["className"] == ""   # red, not the warn style


def test_stale_market_data_ollama_down_and_kill_switch_are_called_out(tmp_path):
    out = run({"evil": "", "status": status(market="down", ollama="down", key_status="unhealthy", flags={"kill_switch": "drill"})}, tmp_path)
    b = out["banner"]["innerHTML"]
    assert "MARKET DATA IS STALE" in b and "OLLAMA CREDENTIALS UNHEALTHY" in b and "KILL SWITCH ACTIVE" in b
    assert "key#0: unhealthy (401)" in out["health"]


def test_injected_html_in_status_text_is_escaped_in_the_health_panel(tmp_path):
    st = status(flags={"<script>alert(1)</script>": "x"})
    out = run({"evil": "", "status": st}, tmp_path)
    assert "<script>alert" not in out["health"]


API_TEXT_FIELDS = ("pipeline_stage", "event_type", "rejection_reason", "blocking_reasons", "trading_mode",
                   "agent_id_a", "agent_id_b", "strategy_version_id", "parent_strategy_version_id",
                   "child_strategy_version_id", "death_reason", "halt_reason")


def test_api_text_fields_are_never_interpolated_unescaped():
    """Static guard: a template `${...}` that touches an API-supplied string field must be inside esc(...)."""
    offenders = []
    for expr in re.findall(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}", SCRIPT):
        stripped = re.sub(r"esc\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)", "", expr)   # calls to esc(...) are safe
        stripped = re.sub(r"[\w.]+\s*[!=]==?\s*(['\"])[^'\"]*\1", "", stripped)         # pure comparisons emit no API text
        stripped = re.sub(r"[\w.]+\s*\?(?!\?)", "", stripped)                                 # ternary condition only tests truthiness
        if any(f in stripped for f in API_TEXT_FIELDS):
            offenders.append(expr)
    assert not offenders, offenders
