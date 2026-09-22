"""Import every ORM model so `Base.metadata` is complete for Alembic
autogenerate and for `Base.metadata.create_all` in tests."""
from app.models.adversarial import AdversarialTestReport
from app.models.agent import Agent
from app.models.champion_challenger import ChallengerEvaluation
from app.models.correlation import AgentCorrelation, CorrelationConvergenceSnapshot, StrategyFamilyCorrelation
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.decision import Decision
from app.models.evolution import EvolutionEvent, PopulationEvent
from app.models.market import MarketCandle, MarketFeatureSet, MarketRegimeRecord
from app.models.metrics import FitnessScore, PerformanceMetric
from app.models.reality_gap import RealityGapReport
from app.models.regime_validation import RegimeValidationReport
from app.models.stage_metrics import StageMetrics
from app.models.strategy import AgentSnapshot, Generation, Strategy, StrategyVersion
from app.models.system import SystemEvent, WorkerCycle, WorkerLease
from app.models.trading import Order, Position, Trade

__all__ = [
    "AdversarialTestReport",
    "Agent",
    "ChallengerEvaluation",
    "AgentCorrelation",
    "CorrelationConvergenceSnapshot",
    "StrategyFamilyCorrelation",
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
    "RealityGapReport",
    "RegimeValidationReport",
    "StageMetrics",
    "AgentSnapshot",
    "Generation",
    "Strategy",
    "StrategyVersion",
    "SystemEvent",
    "WorkerCycle",
    "WorkerLease",
    "Order",
    "Position",
    "Trade",
]
