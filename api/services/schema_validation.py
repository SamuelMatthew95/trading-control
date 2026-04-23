"""
Schema validation layer for strict signal enforcement.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

VALIDATION:
- Enforces strict schema compliance
- Prevents malformed agent output
- Blocks invalid trading signals
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, validator

from api.core.events import SignalAction


class ValidationError(Exception):
    """Schema validation error."""

    pass


class SignalSchema(BaseModel):
    """Canonical signal schema for validation."""

    signal_id: str = Field(..., description="Unique signal identifier for idempotency")
    agent_id: str = Field(..., description="Agent identifier")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    action: SignalAction = Field(..., description="Trading action")
    price: Decimal = Field(..., gt=0, description="Trade price must be positive")
    confidence: float | None = Field(None, ge=0, le=100, description="Confidence score 0-100")
    timestamp: datetime = Field(..., description="Signal timestamp")
    metadata: dict[str, Any] | None = Field(default_factory=dict, description="Optional metadata")

    @validator("symbol")
    def validate_symbol(self, v):
        """Validate trading symbol format."""
        if not v or not v.isalpha() or len(v) > 10:
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()

    @validator("action")
    def validate_action(self, v):
        """Validate trading action."""
        if v not in [SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD]:
            raise ValueError(f"Invalid action: {v}")
        return v


class AgentOutputValidator:
    """Validates agent output against schema."""

    def __init__(self):
        self.validation_errors = []

    def validate_signal(self, signal_data: dict[str, Any]) -> SignalSchema:
        """Validate signal data against canonical schema."""
        try:
            return SignalSchema(**signal_data)
        except Exception as e:
            raise ValidationError(f"Signal validation failed: {str(e)}") from e

    def enforce_signal_contract(self, signal_data: dict[str, Any]) -> dict[str, Any]:
        """Enforce signal contract and return normalized data."""
        try:
            # Validate schema
            validated_signal = self.validate_signal(signal_data)

            # Enforce required fields
            if not validated_signal.signal_id:
                raise ValidationError("signal_id is required")

            if not validated_signal.agent_id:
                raise ValidationError("agent_id is required")

            if not validated_signal.symbol:
                raise ValidationError("symbol is required")

            if validated_signal.price <= 0:
                raise ValidationError("price must be positive")

            # Normalize confidence to valid range
            if validated_signal.confidence is not None:
                validated_signal.confidence = max(0, min(100, validated_signal.confidence))

            return validated_signal.dict()

        except ValidationError as e:
            # Return error details for logging
            return {
                "error": str(e),
                "original_data": signal_data,
                "validation_failed": True,
            }
        except Exception as e:
            return {
                "error": f"Unexpected validation error: {str(e)}",
                "original_data": signal_data,
                "validation_failed": True,
            }

    def validate_agent_permissions(self, agent_id: str, action: SignalAction) -> bool:
        """Validate if agent is allowed to perform action."""
        # In production, this would check against agent permissions
        # For now, allow all actions
        return True

    def check_rate_limits(self, agent_id: str, symbol: str) -> bool:
        """Check if agent exceeds rate limits."""
        # In production, this would check against rate limit store
        # For now, allow all requests
        return True
