"""Typed models for every stage of the hybrid decision pipeline.

These are the contracts that flow between deterministic stages and the LLM
agents. LLM-output models use ``extra="forbid"`` + range validation so a
malformed or hallucinated response fails validation and is converted to a safe
HOLD by the caller — the model can never smuggle an out-of-schema key through.

All field access in the pipeline is attribute access on these models, never raw
dict-key lookups, which keeps the FieldName guardrail satisfied.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.constants import (
    BlockReason,
    LifecycleStage,
    MarketDirection,
    PositionSide,
    ReviewResult,
    SizeHint,
)

# The only actions the system ever acts on. "reject"/"flat" are not model
# actions — deterministic code expresses blocks via BlockReason instead.
TradeAction = Literal["buy", "sell", "hold"]
CandidateDirection = Literal["long", "short", "exit", "none"]
OrderSideLiteral = Literal["buy", "sell"]


# ---------------------------------------------------------------------------
# Inputs — built by the caller/adapter from market data, portfolio, ledger.
# Lenient (no extra="forbid"): real-world inputs carry incidental extra fields.
# ---------------------------------------------------------------------------


class MarketSnapshot(BaseModel):
    """Point-in-time market state for one symbol, as seen by the validator."""

    symbol: str
    market_open: bool = False
    tradable: bool = False
    broker_available: bool = True
    last_price: float | None = None
    price_age_seconds: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    relative_volume: float | None = None
    data_error: str | None = None

    @property
    def spread_bps(self) -> float | None:
        """Bid/ask spread in basis points, or None when a quote is unavailable."""
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2.0
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid * 10_000.0


class PortfolioState(BaseModel):
    """Account-level state the risk engine and sizing engine read."""

    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    open_positions_count: int = 0
    daily_pnl: float = 0.0
    daily_drawdown_pct: float = 0.0
    complete: bool = True
    ledger_complete: bool = True
    kill_switch_active: bool = False


class PositionState(BaseModel):
    """Current open position for the symbol under evaluation."""

    symbol: str
    side: PositionSide = PositionSide.FLAT
    qty: float = 0.0
    entry_price: float | None = None

    @property
    def exists(self) -> bool:
        return self.qty > 0 and self.side is not PositionSide.FLAT


class BrokerState(BaseModel):
    """Broker/feed liveness as seen at decision time."""

    available: bool = True
    open_order_exists: bool = False


# ---------------------------------------------------------------------------
# Deterministic stage outputs
# ---------------------------------------------------------------------------


class MarketValidation(BaseModel):
    """Result of deterministic pre-LLM market validation."""

    passed: bool
    block_reason: BlockReason | None = None
    missing_fields: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class SignalSummary(BaseModel):
    """Deterministic signal summary computed from market/candle data.

    Indicators that cannot be computed are left ``None`` and named in
    ``missing_indicators``; ``indicators_complete`` is then False so the
    pipeline defaults to HOLD rather than trading on partial data.
    """

    symbol: str
    setup_type: str = "none"
    raw_direction: MarketDirection = MarketDirection.NEUTRAL
    confidence_seed: float = 0.0

    trend_score: float = 0.0
    momentum_score: float = 0.0
    liquidity_score: float = 0.0
    volatility_risk: float = 0.0

    # Raw indicator values (None when unavailable)
    ema_9: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    vwap: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    atr_14: float | None = None
    atr_pct: float | None = None
    relative_volume: float | None = None

    # Derived booleans / distances
    price_above_vwap: bool | None = None
    ema_9_above_ema_20: bool | None = None
    ema_20_above_ema_50: bool | None = None
    macd_bias: MarketDirection | None = None
    near_resistance: bool = False
    near_support: bool = False
    distance_to_vwap_pct: float | None = None
    distance_to_support_pct: float | None = None
    distance_to_resistance_pct: float | None = None
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)

    # Data-quality flags
    indicators_complete: bool = False
    price_fresh: bool = False
    volume_valid: bool = False
    missing_indicators: list[str] = Field(default_factory=list)


class SignalCandidate(BaseModel):
    """Deterministic candidate gate — decides whether the LLM is called at all."""

    symbol: str
    candidate: bool
    candidate_type: str
    direction: CandidateDirection
    strength: float = Field(ge=0.0, le=1.0)
    why: list[str] = Field(default_factory=list)
    why_not: list[str] = Field(default_factory=list)
    send_to_model: bool = False
    block_reason: BlockReason | None = None


# ---------------------------------------------------------------------------
# LLM-output models — strict: extra keys, bad enums, or out-of-range numbers
# raise ValidationError → caller converts to a safe HOLD/model_output_invalid.
# ---------------------------------------------------------------------------


class DataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_fresh: bool
    volume_valid: bool
    indicators_complete: bool
    portfolio_state_complete: bool
    ledger_state_complete: bool


class InstructDecision(BaseModel):
    """Strict-JSON output of the fast instruct decision agent."""

    model_config = ConfigDict(extra="forbid")

    action: TradeAction
    symbol: str
    confidence: float = Field(ge=0.0, le=1.0)
    setup_type: str
    thesis: str
    supporting_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_entry: float | None = None
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    reward_risk_ratio: float | None = None
    position_size_hint: SizeHint
    needs_reasoning_review: bool
    data_quality: DataQuality
    should_execute: bool = False

    @field_validator("should_execute")
    @classmethod
    def _never_execute(cls, _v: bool) -> bool:
        # Hard invariant: an LLM can never set should_execute=True. Even if the
        # model returns true, deterministic code is the only executor.
        return False


class ReasoningReview(BaseModel):
    """Strict-JSON output of the skeptical reasoning-review agent.

    It may only recommend; it can never approve execution directly.
    """

    model_config = ConfigDict(extra="forbid")

    review_result: ReviewResult
    final_model_action: TradeAction
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str
    main_concern: str | None = None
    model_disagreements: list[str] = Field(default_factory=list)
    additional_risk_flags: list[str] = Field(default_factory=list)
    recommended_size_multiplier: float = Field(default=1.0, ge=0.0, le=2.0)
    required_risk_checks: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic risk + sizing outputs (final authority before execution)
# ---------------------------------------------------------------------------


class RiskDecision(BaseModel):
    """Output of the deterministic risk engine — the final authority."""

    approved: bool
    decision: TradeAction
    symbol: str
    block_reason: BlockReason | None = None
    approved_entry: float | None = None
    approved_stop_loss: float | None = None
    approved_take_profit: float | None = None
    size_multiplier: float = 1.0
    required_execution_checks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SizedOrder(BaseModel):
    """Deterministic position-sizing output."""

    symbol: str
    side: OrderSideLiteral
    qty: float
    entry: float
    stop_loss: float | None = None
    take_profit: float | None = None
    notional: float = 0.0
    risk_dollars: float = 0.0
    reject_reason: BlockReason | None = None


class PipelineResult(BaseModel):
    """Full outcome of one decision run. ``decision_id`` ties together every
    lifecycle event emitted for this run."""

    decision_id: str
    trace_id: str
    symbol: str
    final_action: TradeAction
    approved: bool
    block_reason: BlockReason | None = None
    reason: str = ""
    stages: list[LifecycleStage] = Field(default_factory=list)
    llm_called: bool = False
    reasoning_called: bool = False
    market: MarketValidation | None = None
    candidate: SignalCandidate | None = None
    instruct: InstructDecision | None = None
    review: ReasoningReview | None = None
    risk: RiskDecision | None = None
    order: SizedOrder | None = None
