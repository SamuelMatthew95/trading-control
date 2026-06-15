"""
Pydantic schemas for API request/response models.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProcessResult(BaseModel):
    """Result of message processing."""

    success: bool = Field(..., description="Whether processing succeeded")
    retryable: bool = Field(..., description="Whether the error is retryable")
    message: str | None = Field(None, description="Processing message or error")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    timestamp: str = Field(..., description="Error timestamp")


class TradeRequest(BaseModel):
    """Trade analysis request."""

    symbol: str = Field(..., description="Trading symbol")
    price: float = Field(..., gt=0, description="Current price")
    signals: dict[str, Any] | None = Field(default_factory=list, description="Trading signals")


class TradeDecision(BaseModel):
    """Trade analysis decision."""

    symbol: str = Field(..., description="Trading symbol")
    decision: str = Field(..., pattern="^(LONG|SHORT|FLAT)$", description="Trading decision")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score")
    reasoning: str = Field(..., description="Decision reasoning")
    timestamp: datetime = Field(..., description="Decision timestamp")
    position_size: float | None = Field(None, ge=0, le=1, description="Position size")
    risk_assessment: dict[str, Any] | None = Field(None, description="Risk assessment")


class StandardResponse(BaseModel):
    """Standard API response format."""

    success: bool = Field(..., description="Whether the operation was successful")
    data: Any = Field(None, description="Response data")
    error: str | None = Field(None, description="Error message if any")


class AnnotationCreate(BaseModel):
    """Human annotation staged against an agent run for reinforcement."""

    run_id: str | None = Field(None, description="Agent run id being annotated")
    label: str | None = Field(None, description="Annotation label (e.g. good/bad)")
    note: str | None = Field(None, description="Free-text reviewer note")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra annotation context")


class ReinforceRequest(BaseModel):
    """Request to run the reinforcement / feedback pipeline for a run."""

    run_id: str = Field(..., description="Agent run id to reinforce")
    reward: float | None = Field(None, description="Optional scalar reward signal")
    notes: str | None = Field(None, description="Optional reviewer notes")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service health status")
    timestamp: str = Field(..., description="Health check timestamp")
    services: dict[str, str] = Field(..., description="Individual service statuses")


class NotificationDisplay(BaseModel):
    """UI-ready notification contract emitted by the notification pipeline."""

    id: str
    severity: str
    title: str
    body: str
    icon: str
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
