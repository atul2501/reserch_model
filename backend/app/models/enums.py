"""Shared enums for persisted state. Kept as plain str Enums so Postgres
stores them as native VARCHAR-backed enums via SQLAlchemy's Enum type,
and so Pydantic schemas can reuse them directly.
"""
from __future__ import annotations

import enum


class AgentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEAD = "DEAD"


class TradingMode(str, enum.Enum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class PopulationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXTINCT = "EXTINCT"
    REBUILDING = "REBUILDING"


class StrategyFamily(str, enum.Enum):
    MOMENTUM = "momentum"
    TREND_FOLLOWING = "trend_following"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY = "volatility"
    MARKET_STRUCTURE = "market_structure"
    VWAP = "vwap"
    SCALPING = "scalping"
    ORDER_FLOW = "order_flow"
    HYBRID = "hybrid"


class MarketRegime(str, enum.Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    UNCERTAIN = "UNCERTAIN"


class Bias(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class Side(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RiskDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"


class ExecutionVenue(str, enum.Enum):
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class StrategyStage(str, enum.Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    WALK_FORWARD = "WALK_FORWARD"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    SMALL_LIVE = "SMALL_LIVE"
    APPROVED_LIVE = "APPROVED_LIVE"
    REJECTED = "REJECTED"


class ChampionStatus(str, enum.Enum):
    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class EvolutionEventType(str, enum.Enum):
    MUTATION = "MUTATION"
    CROSSOVER = "CROSSOVER"
    NOVEL_GENERATION = "NOVEL_GENERATION"
    PROMOTION = "PROMOTION"
    REJECTION = "REJECTION"
    DIVERSITY_INJECTION = "DIVERSITY_INJECTION"


class PopulationEventType(str, enum.Enum):
    GENERATION_CREATED = "GENERATION_CREATED"
    POPULATION_EXTINCT = "POPULATION_EXTINCT"
    POPULATION_REBUILT = "POPULATION_REBUILT"
    MILESTONE_REACHED = "MILESTONE_REACHED"


class SystemEventSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
