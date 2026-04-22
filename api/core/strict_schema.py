"""
Strict schema validation - no drift allowed.

DATA CONTRACT:
- All trade records MUST originate from a SignalEvent
- signal_id is required for idempotency
- DB is a projection layer, not source of truth

STRICT VALIDATION:
- No extra fields allowed
- Reject invalid outputs (no auto-correction)
- Enforce strict JSON schema validation
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError, validator

from api.observability import log_structured


class StrictSignalSchema(BaseModel):
    """Strict signal schema - no extra fields allowed."""
    signal_id: str = Field(..., description="Signal identifier for idempotency")
    agent_id: str = Field(..., description="Agent identifier")
    symbol: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    action: str = Field(..., regex="^(BUY|SELL|HOLD)$", description="Trading action")
    price: Decimal = Field(..., gt=0, description="Trade price must be positive")
    confidence: float | None = Field(None, ge=0, le=100, description="Confidence score 0-100")
    timestamp: datetime = Field(..., description="Signal timestamp")

    class Config:
        extra = "forbid"  # No extra fields allowed
        str_strip_whitespace = True
        validate_assignment = True

    @validator('symbol')
    def validate_symbol(self, v):
        if not v or not v.isalpha():
            raise ValueError(f"Invalid symbol: {v}")
        return v.upper()

    @validator('action')
    def validate_action(self, v):
        if v not in ["BUY", "SELL", "HOLD"]:
            raise ValueError(f"Invalid action: {v}")
        return v


class StrictAnalysisSchema(BaseModel):
    """Strict analysis schema - no drift allowed."""
    signal_id: str = Field(..., description="Signal identifier")
    agent_id: str = Field(..., description="Analyst agent ID")
    bias: str = Field(..., regex="^(BULLISH|BEARISH|NEUTRAL)$", description="Market bias")
    confidence: float = Field(..., ge=0, le=100, description="Confidence score 0-100")
    reasoning: str = Field(..., max_length=500, description="Analysis reasoning")
    indicators: dict[str, float] = Field(default_factory=dict, description="Technical indicators")
    timestamp: datetime = Field(..., description="Analysis timestamp")

    class Config:
        extra = "forbid"
        str_strip_whitespace = True
        validate_assignment = True


class StrictRiskSchema(BaseModel):
    """Strict risk schema - no drift allowed."""
    signal_id: str = Field(..., description="Signal identifier")
    agent_id: str = Field(..., description="Risk agent ID")
    risk_score: float = Field(..., ge=0, le=100, description="Risk score 0-100")
    decision: str = Field(..., regex="^(ALLOW|DENY|MODIFY)$", description="Risk decision")
    max_position_size: Decimal | None = Field(None, gt=0, description="Max position size")
    adjusted_confidence: float | None = Field(None, ge=0, le=100, description="Risk-adjusted confidence")
    reasoning: str = Field(..., max_length=500, description="Risk reasoning")
    timestamp: datetime = Field(..., description="Risk assessment timestamp")

    class Config:
        extra = "forbid"
        str_strip_whitespace = True
        validate_assignment = True


class StrictExecutionSchema(BaseModel):
    """Strict execution schema - no drift allowed."""
    signal_id: str = Field(..., description="Signal identifier")
    agent_id: str = Field(..., description="Executor agent ID")
    action: str = Field(..., regex="^(BUY|SELL|HOLD)$", description="Final trade action")
    price: Decimal = Field(..., gt=0, description="Execution price")
    quantity: Decimal = Field(..., gt=0, description="Trade quantity")
    position_id: str | None = Field(None, description="Target position ID for closing")
    execution_reason: str = Field(..., max_length=500, description="Execution reasoning")
    timestamp: datetime = Field(..., description="Execution timestamp")

    class Config:
        extra = "forbid"
        str_strip_whitespace = True
        validate_assignment = True


class StrictSchemaValidator:
    """Strict schema validation - no drift allowed."""

    def __init__(self):
        self.validation_errors = []
        self.rejected_count = 0
        self.accepted_count = 0

    def validate_signal(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate signal with strict schema."""
        try:
            # Remove any extra fields first
            cleaned_data = self._remove_extra_fields(data, StrictSignalSchema)

            # Validate against strict schema
            validated_signal = StrictSignalSchema(**cleaned_data)

            self.accepted_count += 1

            log_structured(
                "info",
                "signal_strict_validated",
                signal_id=validated_signal.signal_id,
                agent_id=validated_signal.agent_id,
            )

            return {
                "valid": True,
                "signal": validated_signal.dict(),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except ValidationError as e:
            self.rejected_count += 1
            self.validation_errors.append({
                "type": "signal_validation",
                "error": str(e),
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            log_structured(
                "warning",
                "signal_strict_rejected",
                signal_id=data.get("signal_id", "unknown"),
                error=str(e),
            )

            return {
                "valid": False,
                "error": str(e),
                "validation_type": "signal_schema",
                "rejected_data": data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def validate_analysis(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate analysis with strict schema."""
        try:
            # Remove any extra fields
            cleaned_data = self._remove_extra_fields(data, StrictAnalysisSchema)

            # Validate against strict schema
            validated_analysis = StrictAnalysisSchema(**cleaned_data)

            self.accepted_count += 1

            log_structured(
                "info",
                "analysis_strict_validated",
                signal_id=validated_analysis.signal_id,
                agent_id=validated_analysis.agent_id,
                bias=validated_analysis.bias,
            )

            return {
                "valid": True,
                "analysis": validated_analysis.dict(),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except ValidationError as e:
            self.rejected_count += 1
            self.validation_errors.append({
                "type": "analysis_validation",
                "error": str(e),
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            log_structured(
                "warning",
                "analysis_strict_rejected",
                signal_id=data.get("signal_id", "unknown"),
                error=str(e),
            )

            return {
                "valid": False,
                "error": str(e),
                "validation_type": "analysis_schema",
                "rejected_data": data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def validate_risk(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate risk assessment with strict schema."""
        try:
            # Remove any extra fields
            cleaned_data = self._remove_extra_fields(data, StrictRiskSchema)

            # Validate against strict schema
            validated_risk = StrictRiskSchema(**cleaned_data)

            self.accepted_count += 1

            log_structured(
                "info",
                "risk_strict_validated",
                signal_id=validated_risk.signal_id,
                agent_id=validated_risk.agent_id,
                decision=validated_risk.decision,
            )

            return {
                "valid": True,
                "risk": validated_risk.dict(),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except ValidationError as e:
            self.rejected_count += 1
            self.validation_errors.append({
                "type": "risk_validation",
                "error": str(e),
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            log_structured(
                "warning",
                "risk_strict_rejected",
                signal_id=data.get("signal_id", "unknown"),
                error=str(e),
            )

            return {
                "valid": False,
                "error": str(e),
                "validation_type": "risk_schema",
                "rejected_data": data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def validate_execution(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate execution with strict schema."""
        try:
            # Remove any extra fields
            cleaned_data = self._remove_extra_fields(data, StrictExecutionSchema)

            # Validate against strict schema
            validated_execution = StrictExecutionSchema(**cleaned_data)

            self.accepted_count += 1

            log_structured(
                "info",
                "execution_strict_validated",
                signal_id=validated_execution.signal_id,
                agent_id=validated_execution.agent_id,
                action=validated_execution.action,
            )

            return {
                "valid": True,
                "execution": validated_execution.dict(),
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except ValidationError as e:
            self.rejected_count += 1
            self.validation_errors.append({
                "type": "execution_validation",
                "error": str(e),
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            log_structured(
                "warning",
                "execution_strict_rejected",
                signal_id=data.get("signal_id", "unknown"),
                error=str(e),
            )

            return {
                "valid": False,
                "error": str(e),
                "validation_type": "execution_schema",
                "rejected_data": data,
                "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def _remove_extra_fields(self, data: dict[str, Any], schema_class: type) -> dict[str, Any]:
        """Remove extra fields not allowed by schema."""
        # Get allowed fields from schema
        allowed_fields = set(schema_class.__fields__.keys())

        # Filter data to only allowed fields
        cleaned_data = {k: v for k, v in data.items() if k in allowed_fields}

        # Log removed fields
        removed_fields = set(data.keys()) - allowed_fields
        if removed_fields:
            log_structured(
                "warning",
                "extra_fields_removed",
                removed_fields=list(removed_fields),
                allowed_fields=list(allowed_fields),
                signal_id=data.get("signal_id", "unknown"),
            )

        return cleaned_data

    def get_validation_stats(self) -> dict[str, Any]:
        """Get validation statistics."""
        total_validations = self.accepted_count + self.rejected_count

        return {
            "total_validations": total_validations,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "acceptance_rate": (self.accepted_count / total_validations * 100) if total_validations > 0 else 0,
            "recent_errors": self.validation_errors[-10:],  # Last 10 errors
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def clear_validation_errors(self) -> None:
        """Clear validation errors."""
        self.validation_errors = []

    def detect_schema_drift(self, recent_validations: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect schema drift in recent validations."""
        # Analyze field frequency
        field_frequency = {}
        for validation in recent_validations:
            if validation.get("valid"):
                data = validation.get("data", {})
                for field in data.keys():
                    field_frequency[field] = field_frequency.get(field, 0) + 1

        # Detect anomalies
        expected_fields = set(StrictSignalSchema.__fields__.keys())
        actual_fields = set(field_frequency.keys())

        extra_fields = actual_fields - expected_fields
        missing_fields = expected_fields - actual_fields

        drift_detected = len(extra_fields) > 0 or len(missing_fields) > 0

        return {
            "drift_detected": drift_detected,
            "extra_fields": list(extra_fields),
            "missing_fields": list(missing_fields),
            "field_frequency": field_frequency,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }
