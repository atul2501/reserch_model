"""Strategy DNA schema (spec section 10).

This is the contract between the evolution engine (which mutates/crosses
DNA), Ollama (which proposes novel DNA), and the deterministic strategy
engine (which evaluates DNA against market features to produce a signal).
Every DNA payload — human-authored, mutated, or Ollama-proposed — MUST pass
this validation before it is allowed to back a StrategyVersion row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import MarketRegime, StrategyFamily


class ComparisonOperator(str, Enum):
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


class IndicatorConfig(BaseModel):
    """One named indicator instance the strategy depends on, e.g.
    {"name": "rsi", "period": 14} or {"name": "ema", "period": 50}."""

    name: str = Field(min_length=1, max_length=32)
    params: dict[str, float | int | str] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class Condition(BaseModel):
    """A single testable condition against a named feature/indicator output,
    e.g. {"feature": "rsi_14", "operator": "lt", "value": 30}."""

    feature: str = Field(min_length=1, max_length=64)
    operator: ComparisonOperator
    value: float | str

    model_config = {"extra": "forbid"}


class RuleSet(BaseModel):
    """A set of conditions combined with AND/OR logic. Kept deliberately
    simple (single-level, single-logic) so it stays deterministic and
    auditable rather than becoming an arbitrary expression language."""

    logic: str = Field(default="AND", pattern="^(AND|OR)$")
    conditions: list[Condition] = Field(min_length=1, max_length=12)

    model_config = {"extra": "forbid"}


class PositionSizing(BaseModel):
    # fixed_fraction == fraction_of_equity, volatility_scaled == volatility_based,
    # kelly_fraction == risk_based (stop-distance risk sizing). Both spellings
    # are accepted and normalised by app.execution.sizing.
    method: str = Field(
        default="fixed_fraction",
        pattern="^(fixed_fraction|fraction_of_equity|fixed_notional|volatility_scaled|volatility_based|kelly_fraction|risk_based)$",
    )
    fraction_of_equity: float = Field(default=0.05, ge=0.001, le=1.0)
    max_notional: float | None = Field(default=None, ge=0)

    model_config = {"extra": "forbid"}


class StopLossConfig(BaseModel):
    enabled: bool = True
    method: str = Field(default="atr_multiple", pattern="^(atr_multiple|fixed_pct|structure_based)$")
    value: float = Field(default=2.0, gt=0)

    model_config = {"extra": "forbid"}


class TakeProfitConfig(BaseModel):
    enabled: bool = True
    method: str = Field(default="risk_reward_multiple", pattern="^(risk_reward_multiple|fixed_pct|atr_multiple)$")
    value: float = Field(default=2.0, gt=0)

    model_config = {"extra": "forbid"}


class TrailingStopConfig(BaseModel):
    enabled: bool = False
    activation_pct: float = Field(default=0.0, ge=0)
    trail_pct: float = Field(default=0.0, ge=0)

    model_config = {"extra": "forbid"}


class CooldownConfig(BaseModel):
    bars_after_loss: int = Field(default=0, ge=0, le=1440)
    bars_after_win: int = Field(default=0, ge=0, le=1440)

    model_config = {"extra": "forbid"}


class RiskProfile(BaseModel):
    max_leverage: float = Field(default=1.0, ge=1.0, le=20.0)
    max_position_fraction: float = Field(default=0.2, ge=0.01, le=1.0)
    max_daily_loss_fraction: float = Field(default=0.1, ge=0.01, le=1.0)
    max_drawdown_fraction: float = Field(default=0.3, ge=0.05, le=1.0)

    model_config = {"extra": "forbid"}


class StrategyDNA(BaseModel):
    strategy_family: StrategyFamily

    indicators: list[IndicatorConfig] = Field(min_length=1, max_length=20)
    # METADATA ONLY (kept for backward compatibility and used solely by the
    # correlation engine's structural similarity). Indicator periods that drive
    # behaviour live in `indicators[].params` (e.g. {"name": "ema", "params": {"period": 20}}).
    lookback_periods: dict[str, int] = Field(default_factory=dict)

    entry_rules: RuleSet
    exit_rules: RuleSet
    # Direction semantics (see app.strategies.engine):
    #   auto       (legacy default) direction is resolved by the strategy FAMILY;
    #   long_only  entry_rules open LONG;   short_only entry_rules open SHORT;
    #   both       entry_rules open LONG and short_entry_rules open SHORT.
    direction_mode: str = Field(default="auto", pattern="^(auto|long_only|short_only|both)$")
    short_entry_rules: RuleSet | None = None
    # Side-aware exit for SHORT positions when direction_mode == "both"
    # (falls back to exit_rules when omitted).
    short_exit_rules: RuleSet | None = None

    regime_preferences: list[MarketRegime] = Field(default_factory=list, max_length=8)

    risk_profile: RiskProfile = Field(default_factory=RiskProfile)
    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    stop_loss: StopLossConfig = Field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = Field(default_factory=TakeProfitConfig)
    trailing_stop: TrailingStopConfig = Field(default_factory=TrailingStopConfig)
    cooldown: CooldownConfig = Field(default_factory=CooldownConfig)

    max_trades_per_day: int = Field(default=20, ge=1, le=1000)
    leverage_limit: float = Field(default=1.0, ge=1.0, le=20.0)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _leverage_consistency(self) -> "StrategyDNA":
        if self.leverage_limit > self.risk_profile.max_leverage:
            raise ValueError("leverage_limit cannot exceed risk_profile.max_leverage")
        return self

    @model_validator(mode="after")
    def _direction_consistency(self) -> "StrategyDNA":
        if self.direction_mode == "both" and self.short_entry_rules is None:
            raise ValueError("direction_mode='both' requires short_entry_rules")
        return self

    @field_validator("indicators")
    @classmethod
    def _unique_indicator_names(cls, v: list[IndicatorConfig]) -> list[IndicatorConfig]:
        names = [(i.name, tuple(sorted(i.params.items()))) for i in v]
        if len(names) != len(set(names)):
            raise ValueError("duplicate indicator configuration in DNA")
        return v


class StrategyIdentity(BaseModel):
    """Versioning/lineage metadata that travels alongside a StrategyDNA
    payload but is not itself part of the DNA (spec section 10)."""

    strategy_id: uuid.UUID
    strategy_version: int = Field(ge=1)
    parent_strategy_id: uuid.UUID | None = None
    generation: int = Field(ge=1)
    mutation_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "forbid"}


class StrategyCandidate(BaseModel):
    """What Ollama (or the mutation/crossover engine) must produce for a new
    candidate strategy before it enters the validation pipeline (section 26)."""

    strategy_family: StrategyFamily
    hypothesis: str = Field(min_length=1, max_length=4096)
    dna: StrategyDNA
    expected_behavior: str = Field(default="", max_length=2048)
    failure_conditions: list[str] = Field(default_factory=list, max_length=20)

    model_config = {"extra": "forbid"}
