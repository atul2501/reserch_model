"""The pre-trade decision record.

Every field is either produced by the current system or explicitly None. Fields the current strategies/models do NOT
produce are never filled with invented values:

  * expected_move_bps — no current component predicts a move size. It must come from a model that is trained and
    validated to predict E[signed move over horizon] (see the report, "Generating expected_move_bps"). Until then it
    is None and the gate's cost check reports `cost_check_unavailable` instead of passing on a made-up number.
  * horizon_seconds   — strategy DNA has no holding horizon (exits are rule/TP/SL driven), so None.
  * model_version / prompt_version — None unless an LLM/model actually contributed to the decision.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

BAR_MS_1M = 60_000


@dataclass(frozen=True)
class PreTradeDecision:
    decision_id: str
    agent_id: str
    symbol: str
    direction: str                         # "LONG" | "SHORT"
    signal_bar_open_time_ms: int           # the CONFIRMED bar the decision was computed from
    information_cutoff_ms: int             # latest instant any input may describe (= signal bar close)
    features_as_of_ms: int                 # max timestamp of any feature input (must be <= information_cutoff_ms)
    signal_timestamp_ms: int               # wall clock: strategy signal produced
    decision_timestamp_ms: int             # wall clock: decision record created
    reference_price: float                 # price the decision was made against (signal-bar close)
    strategy: str                          # strategy family
    strategy_version_id: str | None
    regime: str | None
    confidence: float | None               # the strategy's own confidence (NOT a calibrated probability)
    feature_version: str
    expected_move_bps: float | None = None
    horizon_seconds: int | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    council_bias: str | None = None        # informational only; never authorises execution by itself
    council_confidence: float | None = None
    council_cutoff_ms: int | None = None   # information cutoff of the council output that was attached
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG or SHORT, got {self.direction!r}")
        if self.features_as_of_ms > self.information_cutoff_ms:
            raise ValueError("look-ahead: features_as_of_ms is later than information_cutoff_ms")
        if self.council_cutoff_ms is not None and self.council_cutoff_ms > self.information_cutoff_ms:
            raise ValueError("look-ahead: council output describes information after the decision's cutoff")
        if self.reference_price <= 0:
            raise ValueError("reference_price must be positive")

    @property
    def sign(self) -> int:
        return 1 if self.direction == "LONG" else -1

    def age_ms(self, now_ms: int) -> int:
        """Age measured from the information cutoff — what matters is how old the INFORMATION is, not when the
        record was written."""
        return now_ms - self.information_cutoff_ms


def new_decision(
    *, agent_id: str, symbol: str, direction: str, signal_bar_open_time_ms: int, reference_price: float,
    strategy: str, feature_version: str, now_ms: int, signal_timestamp_ms: int | None = None,
    bar_ms: int = BAR_MS_1M, features_as_of_ms: int | None = None, **kw,
) -> PreTradeDecision:
    """Builds a decision for a CLOSED bar: its information cutoff is the bar's close (open + bar_ms - 1)."""
    cutoff = signal_bar_open_time_ms + bar_ms - 1
    return PreTradeDecision(
        decision_id=str(uuid.uuid4()), agent_id=agent_id, symbol=symbol, direction=direction,
        signal_bar_open_time_ms=signal_bar_open_time_ms, information_cutoff_ms=cutoff,
        features_as_of_ms=cutoff if features_as_of_ms is None else features_as_of_ms,
        signal_timestamp_ms=now_ms if signal_timestamp_ms is None else signal_timestamp_ms,
        decision_timestamp_ms=now_ms, reference_price=reference_price, strategy=strategy,
        feature_version=feature_version, **{"strategy_version_id": None, "regime": None, "confidence": None, **kw},
    )
