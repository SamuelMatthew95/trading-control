"""
Canonical TradeDecision object - single truth model for all agent outputs.

DATA CONTRACT:
- All trade decisions MUST originate from this canonical model
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

CANONICAL MODEL:
- Single source of truth for all decision phases
- Eliminates multiple "truth versions" across layers
- Enforces strict schema and relationships
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, validator

from api.observability import log_structured


class BiasType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RiskDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"


class TradeAction(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class AnalysisPhase(BaseModel):
    """Analyst agent output phase."""
    bias: BiasType = Field(..., description="Market bias direction")
    confidence: float = Field(..., ge=0, le=100, description="Confidence score 0-100")
    reasoning: str = Field(..., max_length=500, description="Analysis reasoning")
    indicators: dict[str, float] = Field(default_factory=dict, description="Technical indicators")

    @validator('confidence')
    def validate_confidence(self, v):
        if not 0 <= v <= 100:
            raise ValueError("Confidence must be 0-100")
        return v


class RiskPhase(BaseModel):
    """Risk agent output phase."""
    score: float = Field(..., ge=0, le=100, description="Risk score 0-100")
    decision: RiskDecision = Field(..., description="Risk decision")
    max_position_size: Decimal | None = Field(None, gt=0, description="Max position size")
    adjusted_confidence: float | None = Field(None, ge=0, le=100, description="Risk-adjusted confidence")
    reasoning: str = Field(..., max_length=500, description="Risk reasoning")

    @validator('score')
    def validate_score(self, v):
        if not 0 <= v <= 100:
            raise ValueError("Risk score must be 0-100")
        return v


class ExecutionPhase(BaseModel):
    """Executor agent output phase."""
    action: TradeAction = Field(..., description="Final trade action")
    price: Decimal = Field(..., gt=0, description="Execution price")
    quantity: Decimal = Field(..., gt=0, description="Trade quantity")
    position_id: str | None = Field(None, description="Target position ID for closing")
    execution_reason: str = Field(..., max_length=500, description="Execution reasoning")

    @validator('price')
    def validate_price(self, v):
        if v <= 0:
            raise ValueError("Price must be positive")
        return v

    @validator('quantity')
    def validate_quantity(self, v):
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class TradeDecision(BaseModel):
    """Canonical trade decision object - single source of truth."""

    # Core identifiers
    signal_id: str = Field(..., description="Signal identifier for idempotency")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    timestamp: datetime = Field(..., description="Decision timestamp")

    # Agent phases
    analysis: AnalysisPhase = Field(..., description="Analyst phase output")
    risk: RiskPhase = Field(..., description="Risk phase output")
    execution: ExecutionPhase = Field(..., description="Executor phase output")

    # Metadata
    agent_chain: list[str] = Field(..., description="Agent processing chain")
    processing_duration_ms: int | None = Field(None, ge=0, description="Processing duration")
    final_status: str = Field(..., description="Final decision status")

    @validator('symbol')
    def validate_symbol(self, v):
        if not v or not v.isalpha():
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()

    @validator('agent_chain')
    def validate_agent_chain(self, v):
        if len(v) < 3:
            raise ValueError("Agent chain must include analyst, risk, executor")
        if v[0] != "analyst" or v[1] != "risk" or v[2] != "executor":
            raise ValueError("Agent chain must be: analyst -> risk -> executor")
        return v

    @property
    def is_trade_decision(self) -> bool:
        """Check if this results in a trade."""
        return self.execution.action in [TradeAction.BUY, TradeAction.SELL]

    @property
    def is_buy_decision(self) -> bool:
        """Check if this is a BUY decision."""
        return self.execution.action == TradeAction.BUY

    @property
    def is_sell_decision(self) -> bool:
        """Check if this is a SELL decision."""
        return self.execution.action == TradeAction.SELL

    @property
    def final_confidence(self) -> float:
        """Get final confidence after risk adjustment."""
        return self.risk.adjusted_confidence or self.analysis.confidence

    @property
    def is_risk_approved(self) -> bool:
        """Check if risk approved this decision."""
        return self.risk.decision in [RiskDecision.ALLOW, RiskDecision.MODIFY]

    def to_execution_payload(self) -> dict[str, Any]:
        """Convert to execution payload for pipeline."""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "action": self.execution.action.value.upper(),
            "price": float(self.execution.price),
            "quantity": float(self.execution.quantity),
            "confidence": self.final_confidence,
            "position_id": self.execution.position_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_chain": self.agent_chain,
            "risk_approved": self.is_risk_approved,
            "final_status": self.final_status,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database record format."""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "trade_type": self.execution.action.value.upper(),
            "quantity": self.execution.quantity,
            "entry_price": self.execution.price if self.is_buy_decision else None,
            "exit_price": self.execution.price if self.is_sell_decision else None,
            "confidence_score": Decimal(str(self.final_confidence)),
            "position_id": self.execution.position_id,
            "analysis_bias": self.analysis.bias.value,
            "analysis_confidence": self.analysis.confidence,
            "risk_score": self.risk.score,
            "risk_decision": self.risk.decision.value,
            "risk_adjusted_confidence": self.risk.adjusted_confidence,
            "agent_chain": self.agent_chain,
            "processing_duration_ms": self.processing_duration_ms,
            "final_status": self.final_status,
            "created_at": self.timestamp,
        }


class CanonicalDecisionStore:
    """Manages canonical trade decisions."""

    def __init__(self):
        self._decisions: dict[str, TradeDecision] = {}

    def add_decision(self, decision: TradeDecision) -> None:
        """Add canonical decision."""
        self._decisions[decision.signal_id] = decision

        log_structured(
            "info",
            "canonical_decision_added",
            signal_id=decision.signal_id,
            symbol=decision.symbol,
            action=decision.execution.action.value,
            final_confidence=decision.final_confidence,
        )

    def get_decision(self, signal_id: str) -> TradeDecision | None:
        """Get canonical decision by signal_id."""
        return self._decisions.get(signal_id)

    def get_decisions_by_symbol(self, symbol: str) -> list[TradeDecision]:
        """Get all decisions for a symbol."""
        return [decision for decision in self._decisions.values() if decision.symbol == symbol]

    def get_pending_decisions(self) -> list[TradeDecision]:
        """Get decisions pending execution."""
        return [decision for decision in self._decisions.values() if decision.final_status == "pending"]

    def mark_executed(self, signal_id: str, execution_id: str) -> None:
        """Mark decision as executed."""
        if signal_id in self._decisions:
            self._decisions[signal_id].final_status = "executed"

            log_structured(
                "info",
                "canonical_decision_executed",
                signal_id=signal_id,
                execution_id=execution_id,
            )

    def validate_decision_chain(self, decision: TradeDecision) -> bool:
        """Validate decision follows proper chain."""
        expected_chain = ["analyst", "risk", "executor"]
        return decision.agent_chain == expected_chain
