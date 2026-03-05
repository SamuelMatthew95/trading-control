"""
Gateway API Endpoints - FastAPI Routes for Agent Management
REST API interface for external systems to interact with agents
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from agent.interface import AgentTask, AgentTaskStatus, AgentType
from gateway.openclaw_gateway import OpenClawConfig, OpenClawGateway
from observability.langfuse_client import ObservabilityManager


# Pydantic models for API requests/responses
class TaskRequest(BaseModel):
    """Request model for task submission"""

    task_type: str = Field(..., description="Type of task to execute")
    input_data: Dict[str, Any] = Field(..., description="Input data for the task")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    priority: int = Field(default=1, ge=1, le=5, description="Task priority (1-5)")
    timeout_seconds: int = Field(
        default=300, gt=0, description="Task timeout in seconds"
    )
    scheduled_at: Optional[datetime] = Field(
        None, description="Optional scheduled execution time"
    )

    @validator("task_type")
    def validate_task_type(cls, v):
        if not v or not v.strip():
            raise ValueError("task_type cannot be empty")
        return v.strip()


class TaskResponse(BaseModel):
    """Response model for task results"""

    task_id: str
    status: str
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    metrics: Dict[str, Any]
    trace_id: Optional[str]
    tokens_used: int
    cost_usd: float
    execution_time_ms: float
    started_at: datetime
    completed_at: Optional[datetime]


class AgentRegistrationRequest(BaseModel):
    """Request model for agent registration"""

    agent_id: str = Field(..., description="Unique agent identifier")
    agent_type: AgentType = Field(..., description="Type of agent")
    name: str = Field(..., description="Human-readable agent name")
    description: str = Field(..., description="Agent description")
    version: str = Field(default="1.0.0", description="Agent version")
    capabilities: List[str] = Field(
        default_factory=list, description="Agent capabilities"
    )
    max_concurrent_tasks: int = Field(
        default=5, ge=1, le=20, description="Max concurrent tasks"
    )
    timeout_seconds: int = Field(default=300, gt=0, description="Default timeout")


class AgentStatusResponse(BaseModel):
    """Response model for agent status"""

    agent_id: str
    status: str
    registered_at: datetime
    active_tasks: int
    max_concurrent_tasks: int
    tasks_completed: int
    tasks_failed: int
    last_activity: datetime
    gateway_host: str
    gateway_port: int


class SystemStatusResponse(BaseModel):
    """Response model for system status"""

    gateway_id: str
    status: str
    registered_agents: int
    active_tasks: int
    uptime_seconds: float
    last_heartbeat: datetime
    metrics: Dict[str, Any]


# Dependency injection
async def get_gateway() -> OpenClawGateway:
    """Get OpenClaw gateway instance"""
    # In a real implementation, this would be injected from the application
    # For now, we'll create a mock instance
    config = OpenClawConfig(
        host="localhost", port=8080, api_key="mock_api_key", max_concurrent_tasks=10
    )

    # Mock observability manager
    class MockObservabilityManager:
        async def track_agent_execution(self, agent_id, task, execution_func):
            return await execution_func(task)

        async def register_agent_with_mission_control(self, agent_info):
            return agent_info.get("agent_id")

    observability = MockObservabilityManager()
    return OpenClawGateway(config, observability)


# Create router
gateway_router = APIRouter(prefix="/gateway/v1", tags=["gateway"])


@gateway_router.post("/agents/{agent_id}/tasks", response_model=TaskResponse)
async def submit_task(
    agent_id: str,
    task_request: TaskRequest,
    gateway: OpenClawGateway = Depends(get_gateway),
):
    """Submit a task to a specific agent"""
    try:
        # Create task object
        task = AgentTask(
            task_id=f"task_{datetime.now().timestamp()}",
            task_type=task_request.task_type,
            input_data=task_request.input_data,
            metadata=task_request.metadata,
            priority=task_request.priority,
            timeout_seconds=task_request.timeout_seconds,
            scheduled_at=task_request.scheduled_at,
        )

        # Execute task
        result = await gateway.execute_task(agent_id, task)

        # Convert to response model
        response = TaskResponse(
            task_id=result.task_id,
            status=result.status.value,
            output_data=result.output_data,
            error_message=result.error_message,
            metrics=result.metrics,
            trace_id=result.trace_id,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            execution_time_ms=result.execution_time_ms,
            started_at=result.started_at,
            completed_at=result.completed_at,
        )

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/agents/{agent_id}/status", response_model=AgentStatusResponse)
async def get_agent_status(
    agent_id: str, gateway: OpenClawGateway = Depends(get_gateway)
):
    """Get status of a specific agent"""
    try:
        status_data = await gateway.get_agent_status(agent_id)

        if "error" in status_data:
            raise HTTPException(status_code=404, detail=status_data["error"])

        response = AgentStatusResponse(
            agent_id=status_data["agent_id"],
            status=status_data["status"],
            registered_at=status_data["registered_at"],
            active_tasks=status_data["active_tasks"],
            max_concurrent_tasks=status_data["max_concurrent_tasks"],
            tasks_completed=status_data["tasks_completed"],
            tasks_failed=status_data["tasks_failed"],
            last_activity=status_data["last_activity"],
            gateway_host=status_data["gateway_host"],
            gateway_port=status_data["gateway_port"],
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/agents", response_model=List[AgentStatusResponse])
async def list_agents(gateway: OpenClawGateway = Depends(get_gateway)):
    """List all registered agents"""
    try:
        agents_data = await gateway.get_all_agents()

        responses = []
        for agent_data in agents_data:
            response = AgentStatusResponse(
                agent_id=agent_data["agent_id"],
                status=agent_data["status"],
                registered_at=agent_data["registered_at"],
                active_tasks=agent_data["active_tasks"],
                max_concurrent_tasks=agent_data["max_concurrent_tasks"],
                tasks_completed=agent_data["tasks_completed"],
                tasks_failed=agent_data["tasks_failed"],
                last_activity=agent_data["last_activity"],
                gateway_host=agent_data["gateway_host"],
                gateway_port=agent_data["gateway_port"],
            )
            responses.append(response)

        return responses

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.post("/agents/{agent_id}/register", response_model=Dict[str, str])
async def register_agent(
    agent_id: str,
    registration: AgentRegistrationRequest,
    gateway: OpenClawGateway = Depends(get_gateway),
):
    """Register a new agent"""
    try:
        # Create mock agent for registration
        from agent.interface import AgentInfo, BaseAgent

        class MockAgent(BaseAgent):
            def __init__(
                self, agent_id: str, registration_data: AgentRegistrationRequest
            ):
                super().__init__(agent_id)
                self.registration_data = registration_data

            async def execute_task(self, task):
                return AgentResult(
                    task_id=task.task_id,
                    status=AgentTaskStatus.FAILED,
                    output_data=None,
                    error_message="Mock agent - not implemented",
                    metrics={},
                    trace_id=None,
                    tokens_used=0,
                    cost_usd=0.0,
                    execution_time_ms=0.0,
                    started_at=datetime.now(),
                    completed_at=datetime.now(),
                )

            def get_agent_info(self):
                return AgentInfo(
                    agent_id=self.agent_id,
                    agent_type=self.registration_data.agent_type,
                    name=self.registration_data.name,
                    description=self.registration_data.description,
                    version=self.registration_data.version,
                    capabilities=self.registration_data.capabilities,
                    supported_task_types=[self.registration_data.agent_type.value],
                    max_concurrent_tasks=self.registration_data.max_concurrent_tasks,
                    timeout_seconds=self.registration_data.timeout_seconds,
                )

            def get_supported_task_types(self):
                return [self.registration_data.agent_type.value]

        # Create and register agent
        agent = MockAgent(agent_id, registration)
        registered_id = await gateway.register_agent(agent)

        return {"agent_id": registered_id, "status": "registered"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.delete("/agents/{agent_id}", response_model=Dict[str, str])
async def unregister_agent(
    agent_id: str, gateway: OpenClawGateway = Depends(get_gateway)
):
    """Unregister an agent"""
    try:
        success = await gateway.unregister_agent(agent_id)

        if success:
            return {"agent_id": agent_id, "status": "unregistered"}
        else:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.delete("/tasks/{task_id}", response_model=Dict[str, str])
async def cancel_task(task_id: str, gateway: OpenClawGateway = Depends(get_gateway)):
    """Cancel a running task"""
    try:
        success = await gateway.cancel_task(task_id)

        if success:
            return {"task_id": task_id, "status": "cancelled"}
        else:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(gateway: OpenClawGateway = Depends(get_gateway)):
    """Get gateway system status"""
    try:
        agents_data = await gateway.get_all_agents()

        total_completed = sum(agent.get("tasks_completed", 0) for agent in agents_data)
        total_failed = sum(agent.get("tasks_failed", 0) for agent in agents_data)
        active_tasks = sum(agent.get("active_tasks", 0) for agent in agents_data)

        response = SystemStatusResponse(
            gateway_id="python_gateway",
            status="active",
            registered_agents=len(agents_data),
            active_tasks=active_tasks,
            uptime_seconds=0.0,  # Would be calculated from start time
            last_heartbeat=datetime.now(),
            metrics={
                "total_tasks_completed": total_completed,
                "total_tasks_failed": total_failed,
                "success_rate": (
                    total_completed / (total_completed + total_failed)
                    if (total_completed + total_failed) > 0
                    else 0.0
                ),
            },
        )

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def get_task_status(
    task_id: str, gateway: OpenClawGateway = Depends(get_gateway)
):
    """Get status of a specific task"""
    try:
        # Check if task is active
        if task_id in gateway.active_tasks:
            task = gateway.active_tasks[task_id]
            if task.done():
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "result": task.result(),
                }
            else:
                return {"task_id": task_id, "status": "running"}
        else:
            return {"task_id": task_id, "status": "not_found"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@gateway_router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
    }


# WebSocket endpoint for real-time updates
@gateway_router.websocket("/ws")
async def websocket_endpoint(websocket):
    """WebSocket endpoint for real-time task updates"""
    await websocket.accept()

    try:
        while True:
            # In a real implementation, this would push real-time updates
            # For now, we'll just echo messages
            message = await websocket.receive_text()
            await websocket.send_text(f"Echo: {message}")

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# Background task management
class TaskManager:
    """Manager for background tasks"""

    def __init__(self):
        self.background_tasks: Dict[str, asyncio.Task] = {}

    async def start_background_task(self, task_id: str, coro):
        """Start a background task"""
        if task_id in self.background_tasks:
            # Cancel existing task
            self.background_tasks[task_id].cancel()

        task = asyncio.create_task(coro)
        self.background_tasks[task_id] = task

        # Add cleanup callback
        task.add_done_callback(lambda t: self.background_tasks.pop(task_id, None))

    async def cancel_background_task(self, task_id: str) -> bool:
        """Cancel a background task"""
        if task_id not in self.background_tasks:
            return False

        task = self.background_tasks[task_id]
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        return True


# Global task manager instance
task_manager = TaskManager()
