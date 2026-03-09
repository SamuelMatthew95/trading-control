"""
API Models - Clean Pydantic Models for OpenClaw Trading Control Platform
Separated from routes for proper architecture organization
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# ============================================================================
# Agent Models
# ============================================================================


class AgentInfo(BaseModel):
    """Agent information model"""

    agent_id: str
    agent_type: str
    name: str
    status: str
    tasks_completed: int
    tasks_failed: int
    current_load: int
    max_concurrent_tasks: int
    last_activity: Optional[Union[datetime, str]] = None


# ============================================================================
# Signal Models
# ============================================================================


class SignalInfo(BaseModel):
    """Trading signal information"""

    ticker: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasoning: str
    timestamp: str
    agent_id: str
    trace_id: str


# ============================================================================
# Orchestrator Models
# ============================================================================


class OrchestratorStatus(BaseModel):
    """Orchestrator status information"""

    is_running: bool
    current_cycle_id: Optional[str]
    active_cycles: int
    total_cycles: int
    successful_cycles: int
    failed_cycles: int
    success_rate: float
    last_cycle_time: Optional[str]
    registered_agents: int
    symbols_monitored: List[str]


# ============================================================================
# Tool Models
# ============================================================================


class ToolInfo(BaseModel):
    """Tool information model"""

    tool_id: str
    name: str
    description: str
    tool_type: str
    version: str
    parameters: Dict[str, Any]


# ============================================================================
# Platform Models
# ============================================================================


class PlatformStatus(BaseModel):
    """Complete platform status"""

    status: str
    environment: str
    registered_agents: int
    active_tasks: int
    background_tasks: int
    orchestrator: OrchestratorStatus
    observability: Dict[str, Any]
    memory: Dict[str, Any]
    tools: Dict[str, Any]


# ============================================================================
# Task Models
# ============================================================================


class CycleResult(BaseModel):
    """Orchestration cycle result"""

    cycle_id: str
    trace_id: str
    success: bool
    signals_generated: int
    tasks_executed: int
    steps_completed: List[str]
    errors: List[str]
    started_at: str
    completed_at: str


class TaskSubmissionRequest(BaseModel):
    """Task submission request"""

    task_type: str
    input_data: Dict[str, Any]
    priority: int = Field(default=1, ge=1, le=5)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)


# ============================================================================
# Health Models
# ============================================================================


class HealthStatus(BaseModel):
    """Health check response"""

    status: str
    timestamp: str
    platform_running: bool
    orchestrator_running: bool
    agents_registered: int
    active_cycles: int
    reason: Optional[str] = None


# ============================================================================
# Response Models
# ============================================================================


class APIResponse(BaseModel):
    """Standard API response"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ErrorResponse(BaseModel):
    """Error response model"""

    error: str
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# Request/Response Models for Tools
# ============================================================================


class ToolExecutionRequest(BaseModel):
    """Tool execution request"""

    tool_id: str
    parameters: Dict[str, Any]


class ToolExecutionResponse(BaseModel):
    """Tool execution response"""

    tool_id: str
    result: Dict[str, Any]
    timestamp: str


# ============================================================================
# Platform Management Models
# ============================================================================


class PlatformActionRequest(BaseModel):
    """Platform action request (start/stop)"""

    action: str = Field(..., pattern="^(start|stop)$")
    force: bool = Field(default=False)


class PlatformActionResponse(BaseModel):
    """Platform action response"""

    message: str
    action: str
    success: bool
    timestamp: str
