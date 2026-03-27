"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import SystemMetrics, TradePerformance, Order, AgentLog
from api.database import AsyncSessionFactory
from api.services.metrics_aggregator import MetricsAggregator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/snapshot")
async def get_dashboard_snapshot() -> Dict[str, Any]:
    """
    Get complete dashboard snapshot with all metrics.
    
    This is the primary endpoint for the UI dashboard.
    Returns sanitized data with no NaN values.
    """
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            snapshot = await aggregator.get_dashboard_snapshot()
            return snapshot
            
    except Exception as e:
        logger.error(f"Error getting dashboard snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream-lag")
async def get_stream_lag() -> Dict[str, Any]:
    """Get stream lag metrics per stream."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            lag_metrics = await aggregator.get_stream_lag_metrics()
            return {
                "stream_lag": lag_metrics,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error getting stream lag: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system-health")
async def get_system_health() -> Dict[str, Any]:
    """Get system health metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            health = await aggregator.get_system_health()
            return health
            
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pnl")
async def get_pnl_metrics() -> Dict[str, Any]:
    """Get PnL metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            pnl = await aggregator.get_pnl_metrics()
            return pnl
            
    except Exception as e:
        logger.error(f"Error getting PnL metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents")
async def get_agent_metrics() -> Dict[str, Any]:
    """Get agent activity metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            agents = await aggregator.get_agent_metrics()
            return agents
            
    except Exception as e:
        logger.error(f"Error getting agent metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders")
async def get_order_metrics() -> Dict[str, Any]:
    """Get order flow metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            orders = await aggregator.get_order_metrics()
            return orders
            
    except Exception as e:
        logger.error(f"Error getting order metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
