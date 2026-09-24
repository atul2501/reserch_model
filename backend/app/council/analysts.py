"""AI council analyst prompts (spec section 8). Each analyst receives the
same MarketContext and must return a validated AnalystResponse — no
unstructured text is allowed to reach the trading engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.schemas.council import ANALYST_NAMES, AnalystResponse
from app.schemas.market_context import MarketContext
from app.services.ollama_client import OllamaClient

logger = get_logger(__name__)


@dataclass
class AnalystRunResult:
    """Carries this analyst's own timing/stats directly, rather than
    reading OllamaClient.last_stats — that attribute is a single shared
    field on the client instance, overwritten by whichever concurrent call
    finishes last, so under asyncio.gather() every CouncilAnalysis row
    would silently get the wrong (most-recently-finished) analyst's
    latency/request_id. Each result here is self-contained instead."""

    analyst: str
    response: AnalystResponse | None
    error: str | None
    started_at: datetime
    completed_at: datetime
    request_id: str
    latency_ms: int
    model: str
    normalization: dict | None = None      # boundary-normalisation audit (truncations, dropped keys); None = untouched

ANALYST_FOCUS = {
    "trend": "Assess directional trend strength using EMA/SMA alignment and slope. Ignore short-term noise.",
    "momentum": "Assess momentum using RSI, MACD, and rate of change. Flag overbought/oversold extremes.",
    "structure": "Assess market structure: swing highs/lows, breaks of structure, support/resistance proximity.",
    "order_flow": "Assess volume and participation: volume spikes, VWAP relationship, and what they imply about conviction.",
    "volatility": "Assess volatility regime using ATR, realized volatility, and Bollinger Band width. Flag abnormal conditions.",
    "regime": "Assess the current market regime classification and whether price action confirms or contradicts it.",
    "risk": "Assess downside risk: what could invalidate a position right now, and how far away is invalidation.",
    "contrarian": "Actively look for reasons the obvious read is wrong. Argue the counter-case even if unpopular.",
}

_SYSTEM_PROMPT_TEMPLATE = """You are the {analyst} analyst on a professional crypto trading research council.
Your job: {focus}

You will be given a structured market feature snapshot for a single SOL perpetual
futures candle. Respond with ONLY a JSON object matching this schema:
{{
  "analyst": "{analyst}",
  "bias": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<concise reasoning, 1-3 sentences>",
  "key_factors": ["<factor1>", "..."],
  "invalidators": ["<what would prove this wrong>", "..."]
}}
key_factors and invalidators: AT MOST 10 items each, ordered MOST IMPORTANT FIRST.
Do not include any text outside the JSON object. Be honest about uncertainty —
low confidence and NEUTRAL are valid, useful answers."""


def build_prompt(analyst: str, context: MarketContext) -> tuple[str, str]:
    if analyst not in ANALYST_NAMES:
        raise ValueError(f"unknown analyst: {analyst}")
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(analyst=analyst, focus=ANALYST_FOCUS[analyst])
    user_prompt = (
        f"Market: {context.symbol} {context.timeframe}\n"
        f"Candle open time: {context.candle_open_time}\n"
        f"Close price: {context.close_price}\n"
        f"Regime: {context.regime.regime.value} (confidence {context.regime.confidence:.2f})\n"
        f"Features: {context.flat_features()}"
    )
    return system_prompt, user_prompt


async def run_analyst(
    client: OllamaClient, analyst: str, context: MarketContext, *, deadline_seconds: float | None = None
) -> AnalystRunResult:
    """Never raises — one bad or unreachable Ollama call must never block
    the rest of the council or crash the whole trading cycle (spec section
    41: on failure, fall back toward HOLD rather than propagate). Catches
    OllamaError (timeout/rate-limit/auth/malformed-response, after
    OllamaClient's internal retries are exhausted) and any raw httpx
    transport error (e.g. connection refused) that isn't otherwise wrapped
    by OllamaClient. Every analyst goes through the exact same `client`
    instance passed in — this function never constructs its own client or
    auth logic."""
    started_at = datetime.now(timezone.utc)
    system_prompt, user_prompt = build_prompt(analyst, context)
    try:
        response, stats = await client.generate_structured(
            system_prompt=system_prompt, user_prompt=user_prompt, response_model=AnalystResponse,
            deadline_seconds=deadline_seconds,
        )
        if response.analyst != analyst:
            raise ValueError(f"schema validation: response is for analyst {response.analyst!r}, expected {analyst!r}")
        completed_at = datetime.now(timezone.utc)
        return AnalystRunResult(
            analyst=analyst, response=response, error=None,
            started_at=started_at, completed_at=completed_at,
            request_id=stats.request_id, latency_ms=stats.latency_ms, model=stats.model,
            normalization=getattr(stats, "normalization", None),
        )
    except Exception as exc:  # noqa: BLE001 - any failure (incl. malformed envelopes) is one abstaining analyst
        completed_at = datetime.now(timezone.utc)
        logger.error("council.analyst_failed", analyst=analyst, error=str(exc))
        return AnalystRunResult(
            analyst=analyst, response=None, error=str(exc),
            started_at=started_at, completed_at=completed_at,
            request_id="", latency_ms=int((completed_at - started_at).total_seconds() * 1000), model="",
        )
