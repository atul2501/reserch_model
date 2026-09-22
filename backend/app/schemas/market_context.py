"""The shared market context computed once per candle and fanned out to the
AI council and all 500 agents (spec section 4/7). This is the single
feature-engine output contract."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import MarketRegime


class TrendFeatures(BaseModel):
    ema_fast: float
    ema_slow: float
    sma_fast: float
    sma_slow: float
    ema_slope: float
    trend_strength: float


class MomentumFeatures(BaseModel):
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    roc_10: float


class VolatilityFeatures(BaseModel):
    atr_14: float
    realized_vol: float
    volatility_percentile: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float


class StructureFeatures(BaseModel):
    swing_high: float | None = None
    swing_low: float | None = None
    break_of_structure: bool = False
    higher_high: bool = False
    lower_high: bool = False
    higher_low: bool = False
    lower_low: bool = False
    nearest_support: float | None = None
    nearest_resistance: float | None = None


class VolumeFeatures(BaseModel):
    volume_sma_20: float
    volume_ratio: float
    volume_spike: bool
    vwap: float


class PriceActionFeatures(BaseModel):
    body: float
    wick_ratio: float
    candle_range: float
    gap: float
    is_momentum_candle: bool


class RegimeState(BaseModel):
    regime: MarketRegime
    confidence: float = Field(ge=0.0, le=1.0)
    detector_version: str = "v1"


class MarketContext(BaseModel):
    """Everything downstream consumers (council analysts, strategy engine)
    receive for one candle close. Immutable once constructed — the same
    instance is fanned out to all 500 agents plus every council analyst."""

    symbol: str
    timeframe: str
    candle_open_time: int
    close_price: float
    candle_high: float | None = None
    candle_low: float | None = None

    trend: TrendFeatures
    momentum: MomentumFeatures
    volatility: VolatilityFeatures
    structure: StructureFeatures
    volume: VolumeFeatures
    price_action: PriceActionFeatures
    regime: RegimeState

    funding_rate: float | None = None
    open_interest: float | None = None

    model_config = {"extra": "forbid"}

    def flat_features(self) -> dict[str, float | int | bool | str | None]:
        """Flattened {feature_name: value} view used by the deterministic
        rule engine (StrategyDNA conditions reference these keys)."""
        flat: dict[str, float | int | bool | str | None] = {"close": self.close_price}
        for section in (self.trend, self.momentum, self.volatility, self.structure, self.volume, self.price_action):
            flat.update(section.model_dump(by_alias=False))
        flat["regime"] = self.regime.regime.value
        flat["regime_confidence"] = self.regime.confidence
        return flat
