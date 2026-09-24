"""No fake configuration (spec phase 29) and no dead code (phase 30).

Every Settings field must have a runtime reader; every .env.example key must be a real setting."""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

# Deliberately not read by Python (each with the reason).
INTENTIONALLY_UNREAD = {
    "api_host": "read by run.sh (uvicorn's CLI does not load backend/.env); systemd hard-codes 127.0.0.1",
    "api_port": "read by run.sh; systemd hard-codes the port",
}


def _python_sources() -> dict[str, str]:
    out = {}
    for base in ("app", "scripts"):
        for p in (BACKEND / base).rglob("*.py"):
            out[str(p.relative_to(BACKEND))] = p.read_text()
    return out


def _readers(name: str, sources: dict[str, str]) -> list[str]:
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    hits = []
    for f, text in sources.items():
        for line in text.splitlines():
            if not pat.search(line):
                continue
            if f == "app/core/config.py" and re.match(r"\s*" + re.escape(name) + r"\s*:", line):
                continue   # the declaration itself is not a reader
            hits.append(f)
            break
    return hits


def test_every_setting_has_a_runtime_reader_or_a_documented_reason():
    sources = _python_sources()
    run_sh = (ROOT / "run.sh").read_text()
    unread = [n for n in Settings.model_fields if not _readers(n, sources) and n not in INTENTIONALLY_UNREAD]
    assert not unread, f"settings nothing reads (implement, remove, or document them): {unread}"
    for name in INTENTIONALLY_UNREAD:
        assert name.upper() in run_sh, f"{name}: claimed to be read by run.sh but is not"


def test_every_env_example_key_is_a_real_setting():
    keys = set()
    for line in (ROOT / ".env.example").read_text().splitlines():
        m = re.match(r"\s*#?\s*([A-Z][A-Z0-9_]+)=", line)
        if m:
            keys.add(m.group(1).lower())
    unknown = {k for k in keys if k not in Settings.model_fields}
    assert not unknown, f".env.example documents keys no code reads: {sorted(unknown)}"


def test_no_module_reads_the_environment_directly():
    """Everything goes through Settings (one validated, documented surface)."""
    found = {}
    for f, text in _python_sources().items():
        hits = re.findall(r"os\.(?:environ\.get|getenv)\(\s*[\"']([A-Z_]+)[\"']|os\.environ\[[\"']([A-Z_]+)[\"']\]", text)
        if hits:
            found[f] = hits
    assert not found, f"direct environment reads outside Settings: {found}"


def test_the_stale_data_threshold_has_one_source():
    """risk_engine, market_data_service and the setting used to carry three copies of '180'."""
    risk = (BACKEND / "app/risk/risk_engine.py").read_text()
    market = (BACKEND / "app/market/market_data_service.py").read_text()
    assert "MAX_STALE_DATA_SECONDS" not in risk and "STALE_DATA_THRESHOLD_SECONDS" not in market
    assert "data_stale_threshold_seconds" in risk


def test_removed_dead_code_stays_removed():
    for gone in ("app/strategies/rule_engine.py", "app/analytics/professional_classifier.py"):
        assert not (BACKEND / gone).exists(), gone
    text = "\n".join(_python_sources().values())
    for symbol in ("latest_performance_metric", "compute_liquidation_price_isolated", "StrategyIdentity", "referenced_features(",
                   "set_gauge", "gauge_value", "pro_min_trades", "max_return_correlation"):
        assert symbol not in text, f"dead symbol reintroduced: {symbol}"


def test_the_stale_threshold_setting_drives_the_risk_engine(monkeypatch):
    from app.core.config import get_settings
    from tests.test_risk_engine import _base_input, _check
    from app.models.enums import RiskDecision

    monkeypatch.setattr(get_settings(), "data_stale_threshold_seconds", 30)
    assert _check(_base_input(market_data_age_seconds=45.0)) == RiskDecision.REJECTED
    monkeypatch.setattr(get_settings(), "data_stale_threshold_seconds", 300)
    assert _check(_base_input(market_data_age_seconds=45.0)) != RiskDecision.REJECTED
