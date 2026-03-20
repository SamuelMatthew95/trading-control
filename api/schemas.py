"""
Pydantic schemas for API request/response models.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class KillSwitchRequest(BaseModel):
    """Request to toggle kill switch."""
    active: bool = Field(..., description="Kill switch state")


class KillSwitchResponse(BaseModel):
    """Response from kill switch operation."""
    active: bool = Field(..., description="Current kill switch state")
    timestamp: str = Field(..., description="Operation timestamp")


class DLQReplayResponse(BaseModel):
    """Response from DLQ replay operation."""
    replayed: bool = Field(..., description="Whether replay was successful")
    event_id: str = Field(..., description="ID of replayed event")


class PositionResponse(BaseModel):
    """Position information response."""
    symbol: str = Field(..., description="Trading symbol")
    qty: float = Field(..., description="Position quantity")
    side: str = Field(..., description="Position side (long/short)")
    entry_price: float = Field(..., description="Average entry price")
    unrealized_pnl: float = Field(..., description="Unrealized P&L")
    market_value: float = Field(..., description="Current market value")


class OrderResponse(BaseModel):
    """Order information response."""
    order_id: str = Field(..., description="Unique order identifier")
    symbol: str = Field(..., description="Trading symbol")
    side: str = Field(..., description="Order side (buy/sell)")
    qty: float = Field(..., description="Order quantity")
    price: float = Field(..., description="Order price")
    status: str = Field(..., description="Order status")
    filled_qty: Optional[float] = Field(None, description="Filled quantity")
    fill_price: Optional[float] = Field(None, description="Fill price")
    created_at: str = Field(..., description="Order creation timestamp")
    filled_at: Optional[str] = Field(None, description="Fill timestamp")


class DLQEntryResponse(BaseModel):
    """DLQ entry information."""
    event_id: str = Field(..., description="Event ID")
    stream: str = Field(..., description="Original stream")
    error: str = Field(..., description="Error message")
    retries: int = Field(..., description="Number of retries")
    timestamp: str = Field(..., description="DLQ entry timestamp")


class SystemMetricResponse(BaseModel):
    """System metric information."""
    metric_name: str = Field(..., description="Metric name")
    value: float = Field(..., description="Metric value")
    unit: Optional[str] = Field(None, description="Value unit")
    timestamp: str = Field(..., description="Metric timestamp")
    tags: Optional[Dict[str, str]] = Field(None, description="Metric tags")


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    timestamp: str = Field(..., description="Error timestamp")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    timestamp: str = Field(..., description="Health check timestamp")
    services: Dict[str, str] = Field(..., description="Individual service statuses")
