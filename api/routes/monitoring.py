"""
Monitoring API Routes
Simple REST API for system monitoring and health
"""

try:
    from typing import Any, Dict

    import structlog
    from fastapi import APIRouter, HTTPException

    logger = structlog.get_logger()
    router = APIRouter()

except ImportError as e:
    print(f"Warning: Missing dependencies for monitoring.py: {e}")

    # Create dummy router for import compatibility
    class DummyRouter:
        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    router = DummyRouter()

    def HTTPException(*args, **kwargs):
        pass

    logger = None


@router.get("/dashboard")
async def get_dashboard():
    """Get comprehensive monitoring dashboard data"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Collect all metrics
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        return {"success": True, "dashboard": dashboard_data}

    except Exception as e:
        logger.error(f"Error getting dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health-score")
async def get_health_score():
    """Get system health score"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract health score
        health_score = dashboard_data.get("system_health", {})

        return {"success": True, "health_score": health_score}

    except Exception as e:
        logger.error(f"Error getting health score: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts")
async def get_alerts():
    """Get current system alerts"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract alerts
        alerts = dashboard_data.get("alerts", [])

        return {"success": True, "alerts": alerts, "count": len(alerts)}

    except Exception as e:
        logger.error(f"Error getting alerts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system-metrics")
async def get_system_metrics():
    """Get detailed system metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract system metrics
        system_metrics = dashboard_data.get("metrics", {}).get("system", {})

        return {"success": True, "system_metrics": system_metrics}

    except Exception as e:
        logger.error(f"Error getting system metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance-metrics")
async def get_performance_metrics():
    """Get performance metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract performance metrics
        performance_metrics = dashboard_data.get("metrics", {}).get("performance", {})

        return {"success": True, "performance_metrics": performance_metrics}

    except Exception as e:
        logger.error(f"Error getting performance metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent-metrics")
async def get_agent_metrics():
    """Get agent-related metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract agent metrics
        agent_metrics = dashboard_data.get("metrics", {}).get("agents", {})

        return {"success": True, "agent_metrics": agent_metrics}

    except Exception as e:
        logger.error(f"Error getting agent metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-metrics")
async def get_data_metrics():
    """Get data-related metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract data metrics
        data_metrics = dashboard_data.get("metrics", {}).get("data", {})

        return {"success": True, "data_metrics": data_metrics}

    except Exception as e:
        logger.error(f"Error getting data metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task-metrics")
async def get_task_metrics():
    """Get task-related metrics"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Extract task metrics
        task_metrics = dashboard_data.get("metrics", {}).get("tasks", {})

        return {"success": True, "task_metrics": task_metrics}

    except Exception as e:
        logger.error(f"Error getting task metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_monitoring_summary():
    """Get monitoring summary"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Create summary
        health_score = dashboard_data.get("system_health", {})
        alerts = dashboard_data.get("alerts", [])
        metrics = dashboard_data.get("metrics", {})

        summary = {
            "overall_status": health_score.get("status", "unknown"),
            "health_score": health_score.get("score", 0),
            "active_alerts": len(alerts),
            "critical_alerts": len(
                [a for a in alerts if a.get("severity") == "critical"]
            ),
            "system_load": metrics.get("performance", {}).get("system_load", 0),
            "success_rate": metrics.get("tasks", {}).get("success_rate", 0),
            "agents_active": metrics.get("agents", {}).get("agents_active", 0),
            "data_freshness_ms": metrics.get("data", {}).get("data_freshness_ms", 0),
            "last_update": dashboard_data.get("last_update"),
        }

        return {"success": True, "summary": summary}

    except Exception as e:
        logger.error(f"Error getting monitoring summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def monitoring_health_check():
    """Simple health check for monitoring system"""
    try:
        from main import app

        orchestrator = app.state.orchestrator

        # Import monitoring system
        from monitoring.dashboard import system_monitor

        # Get dashboard data
        dashboard_data = await system_monitor.collect_metrics(orchestrator)

        # Check if monitoring is working
        if dashboard_data and "metrics" in dashboard_data:
            return {
                "status": "healthy",
                "monitoring_active": True,
                "last_update": dashboard_data.get("last_update"),
            }
        else:
            return {
                "status": "unhealthy",
                "monitoring_active": False,
                "error": "Monitoring data not available",
            }

    except Exception as e:
        logger.error(f"Error in monitoring health check: {str(e)}")
        return {"status": "unhealthy", "monitoring_active": False, "error": str(e)}
