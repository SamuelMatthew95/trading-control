"""Monitoring system endpoints for production dashboard."""

from typing import Any

from fastapi import APIRouter, HTTPException

from api.constants import FieldName
from api.observability import log_structured
from api.utils import get_nested, now_iso

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/alerts")
async def get_alerts() -> dict[str, Any]:
    """Get system alerts"""
    try:
        # Mock implementation for now
        alerts = []
        return {FieldName.SUCCESS: True, FieldName.ALERTS: alerts, FieldName.COUNT: len(alerts)}
    except Exception as e:
        log_structured("error", "alerts failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/system-metrics")
async def get_system_metrics() -> dict[str, Any]:
    """Get detailed system metrics"""
    try:
        # Mock implementation for now
        system_metrics = {}
        return {FieldName.SUCCESS: True, FieldName.SYSTEM_METRICS: system_metrics}
    except Exception as e:
        log_structured("error", "system metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/performance-metrics")
async def get_performance_metrics() -> dict[str, Any]:
    """Get performance metrics"""
    try:
        # Mock implementation for now
        performance_metrics = {}
        return {FieldName.SUCCESS: True, FieldName.PERFORMANCE_METRICS: performance_metrics}
    except Exception as e:
        log_structured("error", "performance metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/agent-metrics")
async def get_agent_metrics() -> dict[str, Any]:
    """Get agent-related metrics"""
    try:
        # Mock implementation for now
        agent_metrics = {}
        return {FieldName.SUCCESS: True, FieldName.AGENT_METRICS: agent_metrics}
    except Exception as e:
        log_structured("error", "agent metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/data-metrics")
async def get_data_metrics() -> dict[str, Any]:
    """Get data-related metrics"""
    try:
        # Mock implementation for now
        data_metrics = {}
        return {FieldName.SUCCESS: True, FieldName.DATA_METRICS: data_metrics}
    except Exception as e:
        log_structured("error", "data metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/task-metrics")
async def get_task_metrics() -> dict[str, Any]:
    """Get task-related metrics"""
    try:
        # Mock implementation for now
        task_metrics = {}
        return {FieldName.SUCCESS: True, FieldName.TASK_METRICS: task_metrics}
    except Exception as e:
        log_structured("error", "task metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/summary")
async def get_monitoring_summary() -> dict[str, Any]:
    """Get monitoring summary"""
    try:
        # Mock implementation for now
        health_score = {FieldName.STATUS: "unknown", FieldName.SCORE: 0}
        alerts = []
        metrics = {
            FieldName.PERFORMANCE: {},
            FieldName.SYSTEM: {},
            FieldName.AGENTS: {},
            FieldName.DATA: {},
        }
        summary = {
            FieldName.OVERALL_STATUS: health_score.get(FieldName.STATUS, "unknown"),
            FieldName.HEALTH_SCORE: health_score.get(FieldName.SCORE, 0),
            FieldName.ACTIVE_ALERTS: len(alerts),
            FieldName.CRITICAL_ALERTS: len(
                [a for a in alerts if a.get(FieldName.SEVERITY) == "critical"]
            ),
            FieldName.SYSTEM_LOAD: get_nested(metrics, "performance", "system_load", default=0),
            FieldName.SUCCESS_RATE: get_nested(metrics, "tasks", "success_rate", default=0),
            FieldName.AGENTS_ACTIVE: get_nested(metrics, "agents", "agents_active", default=0),
            FieldName.DATA_FRESHNESS_MS: get_nested(
                metrics, FieldName.DATA, "data_freshness_ms", default=0
            ),
            FieldName.LAST_UPDATE: now_iso(),
        }
        return {FieldName.SUCCESS: True, FieldName.SUMMARY: summary}
    except Exception as e:
        log_structured("error", "monitoring summary failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/health")
async def monitoring_health_check() -> dict[str, Any]:
    """Simple health check for monitoring system"""
    try:
        return {
            FieldName.STATUS: "healthy",
            FieldName.MONITORING_ACTIVE: True,
            FieldName.LAST_UPDATE: now_iso(),
        }
    except Exception as e:
        log_structured("error", "monitoring health check failed", exc_info=True)
        return {
            FieldName.STATUS: "unhealthy",
            FieldName.MONITORING_ACTIVE: False,
            FieldName.ERROR: str(e),
        }
