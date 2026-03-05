"""
Orchestrator API Routes
Simple REST API for controlling the trading orchestrator
"""

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter()


class TaskRequest(BaseModel):
    """Request to submit a new task"""

    task_type: str
    symbol: str
    priority: str = "medium"
    data: Dict[str, Any] = {}


class TaskResponse(BaseModel):
    """Response for task submission"""

    success: bool
    task_id: Optional[str] = None
    message: str = ""


class SystemStatus(BaseModel):
    """System status response"""

    is_running: bool
    config: Dict[str, Any]
    metrics: Dict[str, Any]
    queue_status: Dict[str, Any]
    agent_status: Dict[str, Any]


@router.post("/submit-task", response_model=TaskResponse)
async def submit_task(task_request: TaskRequest, background_tasks: BackgroundTasks):
    """Submit a new task to the orchestrator"""
    try:
        # Get orchestrator from app state
        from main import app

        orchestrator = app.state.orchestrator

        if not orchestrator.is_running:
            raise HTTPException(status_code=503, detail="Orchestrator is not running")

        # Convert priority string to enum
        from core.task_queue import TaskPriority

        priority_map = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }

        priority = priority_map.get(task_request.priority.lower(), TaskPriority.MEDIUM)

        # Add task to queue
        task_id = orchestrator.task_queue.add_task(
            task_type=task_request.task_type,
            symbol=task_request.symbol,
            priority=priority,
            data=task_request.data,
        )

        logger.info(
            f"Task submitted: {task_id} ({task_request.task_type} for {task_request.symbol})"
        )

        return TaskResponse(
            success=True,
            task_id=task_id,
            message=f"Task {task_id} submitted successfully",
        )

    except Exception as e:
        logger.error(f"Error submitting task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_orchestrator():
    """Start the orchestrator"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        if orchestrator.is_running:
            return {"success": True, "message": "Orchestrator is already running"}

        await orchestrator.start()

        logger.info("Orchestrator started via API")

        return {"success": True, "message": "Orchestrator started successfully"}

    except Exception as e:
        logger.error(f"Error starting orchestrator: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_orchestrator():
    """Stop the orchestrator"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        if not orchestrator.is_running:
            return {"success": True, "message": "Orchestrator is already stopped"}

        await orchestrator.stop()

        logger.info("Orchestrator stopped via API")

        return {"success": True, "message": "Orchestrator stopped successfully"}

    except Exception as e:
        logger.error(f"Error stopping orchestrator: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    """Get comprehensive system status"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        status = await orchestrator.get_system_status()

        return SystemStatus(**status)

    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_metrics():
    """Get system metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        metrics = orchestrator.metrics.get_all_metrics()

        return {
            "success": True,
            "metrics": metrics,
            "timestamp": orchestrator.metrics.last_updated,
        }

    except Exception as e:
        logger.error(f"Error getting metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
async def get_queue_status():
    """Get task queue status"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        queue_status = orchestrator.task_queue.get_queue_status()

        return {"success": True, "queue_status": queue_status}

    except Exception as e:
        logger.error(f"Error getting queue status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def get_recent_tasks(limit: int = 20):
    """Get recent completed tasks"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        tasks = orchestrator.task_queue.get_completed_tasks(limit)

        # Convert to dict for JSON serialization
        task_list = []
        for task in tasks:
            task_dict = {
                "id": task.id,
                "task_type": task.task_type,
                "symbol": task.symbol,
                "priority": task.priority.value,
                "status": task.status.value,
                "assigned_agent": task.assigned_agent,
                "created_at": task.created_at.isoformat(),
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": (
                    task.completed_at.isoformat() if task.completed_at else None
                ),
                "duration_ms": task.duration_ms,
                "success": task.success,
                "error": task.error,
            }
            task_list.append(task_dict)

        return {"success": True, "tasks": task_list, "total": len(task_list)}

    except Exception as e:
        logger.error(f"Error getting recent tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}")
async def get_task_details(task_id: str):
    """Get details for a specific task"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        task = orchestrator.task_queue.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        task_dict = {
            "id": task.id,
            "task_type": task.task_type,
            "symbol": task.symbol,
            "priority": task.priority.value,
            "status": task.status.value,
            "assigned_agent": task.assigned_agent,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": (
                task.completed_at.isoformat() if task.completed_at else None
            ),
            "duration_ms": task.duration_ms,
            "success": task.success,
            "error": task.error,
            "data": task.data,
        }

        return {"success": True, "task": task_dict}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scale-up")
async def scale_up():
    """Manually trigger scale up"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        await orchestrator.scale_up()

        return {"success": True, "message": "Scale up initiated"}

    except Exception as e:
        logger.error(f"Error scaling up: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scale-down")
async def scale_down():
    """Manually trigger scale down"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        await orchestrator.scale_down()

        return {"success": True, "message": "Scale down initiated"}

    except Exception as e:
        logger.error(f"Error scaling down: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Simple health check"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        return {
            "status": "healthy" if orchestrator.is_running else "unhealthy",
            "orchestrator_running": orchestrator.is_running,
            "active_tasks": orchestrator.task_queue.get_processing_tasks_count(),
            "pending_tasks": orchestrator.task_queue.get_pending_tasks_count(),
            "total_completed": orchestrator.task_queue.get_total_completed(),
        }

    except Exception as e:
        logger.error(f"Error in health check: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}
