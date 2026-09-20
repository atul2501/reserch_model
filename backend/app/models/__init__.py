"""Import every ORM model so `Base.metadata` is complete for Alembic
autogenerate and for `Base.metadata.create_all` in tests."""
from app.models.agent import Agent
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.decision import Decision
from app.models.evolution import EvolutionEvent, PopulationEvent
from app.models.market import MarketCandle, MarketFeatureSet, MarketRegimeRecord
from app.models.metrics import FitnessScore, PerformanceMetric
from app.models.strategy import AgentSnapshot, Generation, Strategy, StrategyVersion
from app.models.system import SystemEvent
from app.models.trading import Order, Position, Trade

__all__ = [
    "Agent",
    "CouncilAnalysis",
    "CouncilDecision",
    "Decision",
    "EvolutionEvent",
    "PopulationEvent",
    "MarketCandle",
    "MarketFeatureSet",
    "MarketRegimeRecord",
    "FitnessScore",
    "PerformanceMetric",
    "AgentSnapshot",
    "Generation",
    "Strategy",
    "StrategyVersion",
    "SystemEvent",
    "Order",
    "Position",
    "Trade",
]
