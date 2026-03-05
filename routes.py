"""
API Routes - Clean OpenClaw Trading Control Platform
Clean API structure aligned with OpenClaw orchestration architecture
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from logger import get_logger
from memory import get_memory_manager

# Import OpenClaw components
from orchestrator import OpenClawOrchestrator
from tools import get_tool_registry

# Import API models from proper location
from .models import (
    AgentInfo,
    APIResponse,
    CycleResult,
    ErrorResponse,
    HealthStatus,
    OrchestratorStatus,
    PlatformActionRequest,
    PlatformActionResponse,
    PlatformStatus,
    SignalInfo,
    TaskSubmissionRequest,
    ToolExecutionRequest,
    ToolExecutionResponse,
    ToolInfo,
)

logger = get_logger(__name__)


# ============================================================================
# Dependency Injection Functions
# ============================================================================


def get_platform() -> "TradingControlPlatform":
    """Get platform instance from app state"""
    from main import app

    if not hasattr(app.state, "platform") or not app.state.platform:
        logger.error("Platform not initialized")
        raise HTTPException(status_code=503, detail="Platform not initialized")

    return app.state.platform


def get_orchestrator(
    platform: "TradingControlPlatform" = Depends(get_platform),
) -> OpenClawOrchestrator:
    """Get orchestrator instance"""
    return platform.orchestrator


def get_memory(platform: "TradingControlPlatform" = Depends(get_platform)):
    """Get memory instance"""
    return platform.memory_manager


def get_tools(platform: "TradingControlPlatform" = Depends(get_platform)):
    """Get tool registry instance"""
    return platform.tool_registry


# ============================================================================
# API Router
# ============================================================================

api_router = APIRouter(prefix="/api/v1", tags=["OpenClaw API"])

# ============================================================================
# Platform Management Endpoints
# ============================================================================


@api_router.get("/platform/status", response_model=PlatformStatus)
async def get_platform_status(
    platform: "TradingControlPlatform" = Depends(get_platform),
):
    """Get complete platform status"""
    logger.debug("Getting platform status")

    try:
        status = platform.get_platform_status()
        return PlatformStatus(**status)
    except Exception as e:
        logger.error(f"Failed to get platform status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/platform/start", response_model=PlatformActionResponse)
async def start_platform(platform: "TradingControlPlatform" = Depends(get_platform)):
    """Start the platform"""
    logger.info("Starting platform via API")

    try:
        if platform.is_running:
            return PlatformActionResponse(
                message="Platform is already running",
                action="start",
                success=True,
                timestamp=datetime.now().isoformat(),
            )

        await platform.start()
        return PlatformActionResponse(
            message="Platform started successfully",
            action="start",
            success=True,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to start platform: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/platform/stop", response_model=PlatformActionResponse)
async def stop_platform(platform: "TradingControlPlatform" = Depends(get_platform)):
    """Stop the platform"""
    logger.info("Stopping platform via API")

    try:
        if not platform.is_running:
            return PlatformActionResponse(
                message="Platform is already stopped",
                action="stop",
                success=True,
                timestamp=datetime.now().isoformat(),
            )

        await platform.stop()
        return PlatformActionResponse(
            message="Platform stopped successfully",
            action="stop",
            success=True,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to stop platform: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Orchestrator Management Endpoints
# ============================================================================


@api_router.get("/orchestrator/status", response_model=OrchestratorStatus)
async def get_orchestrator_status(
    orchestrator: OpenClawOrchestrator = Depends(get_orchestrator),
):
    """Get orchestrator status"""
    logger.debug("Getting orchestrator status")

    try:
        status = orchestrator.get_status()
        return OrchestratorStatus(**status)
    except Exception as e:
        logger.error(f"Failed to get orchestrator status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/orchestrator/cycles")
async def get_cycle_results(
    limit: int = Query(default=50, ge=1, le=1000),
    orchestrator: OpenClawOrchestrator = Depends(get_orchestrator),
):
    """Get recent orchestration cycle results"""
    logger.debug(f"Getting {limit} recent cycle results")

    try:
        cycles = await orchestrator.get_cycle_results(limit)
        return {"cycles": cycles, "total_count": len(cycles), "limit": limit}
    except Exception as e:
        logger.error(f"Failed to get cycle results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/orchestrator/trigger-cycle")
async def trigger_manual_cycle(
    orchestrator: OpenClawOrchestrator = Depends(get_orchestrator),
):
    """Trigger a manual orchestration cycle"""
    logger.info("Triggering manual orchestration cycle")

    try:
        # Create a manual cycle task
        asyncio.create_task(orchestrator._run_cycle())
        return {"message": "Manual cycle triggered successfully"}
    except Exception as e:
        logger.error(f"Failed to trigger manual cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Agent Management Endpoints
# ============================================================================


@api_router.get("/agents", response_model=List[AgentInfo])
async def get_agents(orchestrator: OpenClawOrchestrator = Depends(get_orchestrator)):
    """Get all registered agents"""
    logger.debug("Getting registered agents")

    try:
        agents = []
        for agent_id, agent in orchestrator.agents.items():
            agents.append(
                AgentInfo(
                    agent_id=agent_id,
                    agent_type=getattr(agent, "agent_type", "unknown"),
                    name=getattr(agent, "name", agent_id),
                    status=getattr(agent, "status", "active"),
                    tasks_completed=getattr(agent, "tasks_completed", 0),
                    tasks_failed=getattr(agent, "tasks_failed", 0),
                    current_load=getattr(agent, "current_load", 0),
                    max_concurrent_tasks=getattr(agent, "max_concurrent_tasks", 1),
                    last_activity=getattr(agent, "last_activity", None),
                )
            )

        return agents
    except Exception as e:
        logger.error(f"Failed to get agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/agents/{agent_id}", response_model=AgentInfo)
async def get_agent(
    agent_id: str, orchestrator: OpenClawOrchestrator = Depends(get_orchestrator)
):
    """Get specific agent information"""
    logger.debug(f"Getting agent {agent_id}")

    try:
        agent = orchestrator.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        return AgentInfo(
            agent_id=agent_id,
            agent_type=getattr(agent, "agent_type", "unknown"),
            name=getattr(agent, "name", agent_id),
            status=getattr(agent, "status", "active"),
            tasks_completed=getattr(agent, "tasks_completed", 0),
            tasks_failed=getattr(agent, "tasks_failed", 0),
            current_load=getattr(agent, "current_load", 0),
            max_concurrent_tasks=getattr(agent, "max_concurrent_tasks", 1),
            last_activity=getattr(agent, "last_activity", None),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Tool Management Endpoints
# ============================================================================


@api_router.get("/tools", response_model=List[ToolInfo])
async def get_tools(tools: "ToolRegistry" = Depends(get_tools)):
    """Get all available tools"""
    logger.debug("Getting available tools")

    try:
        tool_list = tools.get_all_tools()
        return [
            ToolInfo(
                tool_id=tool_id,
                name=metadata.name,
                description=metadata.description,
                tool_type=metadata.category.value,
                version=metadata.version,
                parameters=metadata.parameters,
            )
            for tool_id, metadata in tool_list.items()
        ]
    except Exception as e:
        logger.error(f"Failed to get tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/tools/{tool_id}", response_model=ToolInfo)
async def get_tool(tool_id: str, tools: "ToolRegistry" = Depends(get_tools)):
    """Get specific tool information"""
    logger.debug(f"Getting tool {tool_id}")

    try:
        tool_info = tools.get_tool_metadata(tool_id)
        if not tool_info:
            raise HTTPException(status_code=404, detail="Tool not found")

        return ToolInfo(
            tool_id=tool_info.tool_id,
            name=tool_info.name,
            description=tool_info.description,
            tool_type=tool_info.category.value,
            version=tool_info.version,
            parameters=tool_info.parameters,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tool {tool_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/tools/{tool_id}/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    tool_id: str,
    request: ToolExecutionRequest = Body(...),
    tools: "ToolRegistry" = Depends(get_tools),
):
    """Execute a tool with parameters"""
    logger.debug(f"Executing tool {tool_id}")

    try:
        # Validate tool_id matches request
        if request.tool_id != tool_id:
            raise HTTPException(
                status_code=400,
                detail=f"Tool ID mismatch: URL={tool_id}, request={request.tool_id}",
            )

        result = await tools.execute_tool(tool_id, **request.parameters)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return ToolExecutionResponse(
            tool_id=tool_id, result=result, timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to execute tool {tool_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check Endpoint
# ============================================================================


@api_router.get("/health", response_model=HealthStatus)
async def health_check(platform: "TradingControlPlatform" = Depends(get_platform)):
    """Simple health check endpoint"""
    logger.debug("Health check requested")

    try:
        # Basic health checks
        health_status = HealthStatus(
            status="healthy",
            timestamp=datetime.now().isoformat(),
            platform_running=platform.is_running,
            orchestrator_running=(
                platform.orchestrator.is_running if platform.orchestrator else False
            ),
            agents_registered=(
                len(platform.orchestrator.agents) if platform.orchestrator else 0
            ),
            active_cycles=(
                len(platform.orchestrator.active_cycles) if platform.orchestrator else 0
            ),
        )

        # Check if platform is running
        if not platform.is_running:
            health_status.status = "degraded"
            health_status.reason = "Platform not running"

        # Check orchestrator
        if not platform.orchestrator.is_running:
            health_status.status = "degraded"
            health_status.reason = "Orchestrator not running"

        # Check agents
        if len(platform.orchestrator.agents) == 0:
            health_status.status = "degraded"
            health_status.reason = "No agents registered"

        return health_status

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthStatus(
            status="unhealthy",
            timestamp=datetime.now().isoformat(),
            platform_running=False,
            orchestrator_running=False,
            agents_registered=0,
            active_cycles=0,
            reason=str(e),
        )
