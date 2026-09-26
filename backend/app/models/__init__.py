"""Import every ORM model so `Base.metadata` is complete for Alembic
autogenerate and for `Base.metadata.create_all` in tests."""
from app.models.adversarial import AdversarialTestReport
from app.models.agent import Agent
from app.models.analytics import FitnessForwardPerformance, StrategyRegimeMatrix, TradeAnalytics
from app.models.champion_challenger import ChallengerEvaluation
from app.models.correlation import AgentCorrelation, CorrelationConvergenceSnapshot, StrategyFamilyCorrelation
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.decision import Decision
from app.models.evolution import EvolutionEvent, PopulationEvent
from app.models.market import FundingRate, MarketCandle, MarketFeatureSet, MarketRegimeRecord
from app.models.metrics import FitnessScore, PerformanceMetric
from app.models.reality_gap import RealityGapReport
from app.models.research import Experiment, OosEvaluation, ResearchEpoch
from app.models.regime_validation import RegimeValidationReport
from app.models.stage_metrics import StageMetrics
from app.models.strategy import AgentSnapshot, Generation, Strategy, StrategyVersion
from app.models.system import SystemEvent, SystemFlag, SystemStatus, WorkerCycle, WorkerLease
from app.models.trading import FundingPayment, Order, Position, Trade

__all__ = [
    "AdversarialTestReport",
    "Agent",
    "ChallengerEvaluation",
    "AgentCorrelation",
    "CorrelationConvergenceSnapshot",
    "StrategyFamilyCorrelation",
    "TradeAnalytics",
    "StrategyRegimeMatrix",
    "FitnessForwardPerformance",
    "CouncilAnalysis",
    "CouncilDecision",
    "Decision",
    "EvolutionEvent",
    "PopulationEvent",
    "FundingRate",
    "MarketCandle",
    "MarketFeatureSet",
    "MarketRegimeRecord",
    "FitnessScore",
    "PerformanceMetric",
    "RealityGapReport",
    "Experiment",
    "OosEvaluation",
    "ResearchEpoch",
    "RegimeValidationReport",
    "StageMetrics",
    "AgentSnapshot",
    "Generation",
    "Strategy",
    "StrategyVersion",
    "SystemEvent",
    "SystemFlag",
    "SystemStatus",
    "WorkerCycle",
    "WorkerLease",
    "FundingPayment",
    "Order",
    "Position",
    "Trade",
]


# Database-level invariants (CHECK constraints + the one-pending-entry-per-agent index). Attached once every model is
# imported so `Base.metadata.create_all` (tests, fresh installs) enforces exactly what the migration installs.
from app.core.database import Base as _Base  # noqa: E402
from app.models.constraints import attach_constraints as _attach_constraints  # noqa: E402

_attach_constraints(_Base.metadata)
