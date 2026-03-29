"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.services.metrics_aggregator import MetricsAggregator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


@router.get("/snapshot")
async def get_dashboard_snapshot() -> dict[str, Any]:
    """
    Get complete dashboard snapshot with all metrics.

    This is the primary endpoint for the UI dashboard.
    Returns sanitized data with no NaN values.
    """
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_dashboard_snapshot()

    except Exception as e:
        log_structured("error", "dashboard snapshot failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/stream-lag")
async def get_stream_lag() -> dict[str, Any]:
    """Get stream lag metrics per stream."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            lag_metrics = await aggregator.get_stream_lag_metrics()
            return {
                "stream_lag": lag_metrics,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except Exception as e:
        log_structured("error", "stream lag failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/system-health")
async def get_system_health() -> dict[str, Any]:
    """Get system health metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_system_health()

    except Exception as e:
        log_structured("error", "system health failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/pnl")
async def get_pnl_metrics() -> dict[str, Any]:
    """Get PnL metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_pnl_metrics()

    except Exception as e:
        log_structured("error", "pnl metrics failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/agents")
async def get_agent_metrics() -> dict[str, Any]:
    """Get agent activity metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_agent_metrics()

    except Exception as e:
        log_structured("error", "agent metrics failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/orders")
async def get_order_metrics() -> dict[str, Any]:
    """Get order flow metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_order_metrics()

    except Exception as e:
        log_structured("error", "order metrics failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/prices")
async def get_prices() -> dict[str, Any]:
    """
    Get current market prices from Redis cache.

    This provides instant price data for dashboard initial load,
    without requiring WebSocket connection.
    """
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        redis_client = await get_redis()

        # Get all price keys from Redis
        keys = [f"prices:{symbol}" for symbol in symbols]
        cached_values = await redis_client.mget(keys)

        prices = {}
        for symbol, cached_value in zip(symbols, cached_values, strict=False):
            if cached_value:
                try:
                    prices[symbol] = json.loads(cached_value)
                except json.JSONDecodeError:
                    log_structured("warning", "invalid price json", symbol=symbol)
                    prices[symbol] = None
            else:
                prices[symbol] = None

        return {
            "prices": prices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache",
        }

    except Exception as e:
        log_structured("error", "price cache failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/health/worker")
async def get_worker_health() -> dict[str, Any]:
    """
    Check background worker health by examining price timestamps and heartbeat in Redis.

    Returns worker status based on how recently prices were updated and worker heartbeat.
    Uses HTTP status codes for Render health check integration:
    - 200: Healthy
    - 200: Degraded (still running but slow)
    - 200: Starting (within 60s grace period)
    - 503: Unhealthy (worker stopped/failing)
    """
    now = datetime.now(timezone.utc)

    # Check startup grace period (60 seconds)
    uptime_seconds = (now - PROCESS_START_TIME).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Worker is warming up",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }

    # After grace period, perform actual health checks
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]

        # Try to get Redis client with timeout
        try:
            redis_client = await asyncio.wait_for(get_redis(), timeout=2.0)
        except asyncio.TimeoutError:
            log_structured("warning", "redis timeout during health check")
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": "Redis connection timeout",
                "check_time": now.isoformat(),
            }
        except Exception as e:
            log_structured(
                "warning", "redis connection failed during health check", error=str(e)
            )
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                "check_time": now.isoformat(),
            }

        # Get all price keys and heartbeat from Redis with timeout
        keys = [f"prices:{symbol}" for symbol in symbols] + ["worker:heartbeat"]
        try:
            cached_values = await asyncio.wait_for(redis_client.mget(keys), timeout=2.0)
        except asyncio.TimeoutError:
            log_structured("warning", "redis mget timeout during health check")
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": "Redis read timeout",
                "check_time": now.isoformat(),
            }
        except Exception as e:
            log_structured(
                "warning", "redis read failed during health check", error=str(e)
            )
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                "check_time": now.isoformat(),
            }

        # Extract heartbeat (last item)
        heartbeat_value = cached_values[-1]
        price_values = cached_values[:-1]

        timestamps = []
        stale_symbols = []

        # Check price timestamps
        for symbol, cached_value in zip(symbols, price_values, strict=False):
            if cached_value:
                try:
                    price_data = json.loads(cached_value)
                    timestamp_str = price_data.get("timestamp")
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                        timestamps.append(timestamp)

                        # Check if price is stale (older than 90 seconds)
                        if (now - timestamp).total_seconds() > 90:
                            stale_symbols.append(symbol)
                except (json.JSONDecodeError, ValueError):
                    stale_symbols.append(symbol)
            else:
                stale_symbols.append(symbol)

        # Check heartbeat
        heartbeat_age = None
        heartbeat_status = "missing"
        if heartbeat_value:
            try:
                heartbeat_time = datetime.fromisoformat(
                    heartbeat_value.replace("Z", "+00:00")
                )
                heartbeat_age = (now - heartbeat_time).total_seconds()

                if heartbeat_age <= 10:
                    heartbeat_status = "healthy"
                elif heartbeat_age <= 30:
                    heartbeat_status = "degraded"
                else:
                    heartbeat_status = "stale"
            except ValueError:
                heartbeat_status = "invalid"

        if not timestamps:
            health_data = {
                "status": "unhealthy",
                "message": "No price data found in Redis",
                "last_update": None,
                "heartbeat_status": heartbeat_status,
                "heartbeat_age": int(heartbeat_age) if heartbeat_age else None,
                "stale_symbols": symbols,
                "total_symbols": len(symbols),
                "fresh_symbols": 0,
                "uptime_seconds": uptime_seconds,
                "check_time": now.isoformat(),
            }
            # Return 503 for unhealthy status
            raise HTTPException(status_code=503, detail=health_data)

        # Get the most recent timestamp
        last_update = max(timestamps)
        age_seconds = (now - last_update).total_seconds()

        # Determine overall health status
        if age_seconds <= 30 and heartbeat_status == "healthy":
            status = "healthy"
            message = "Worker is actively updating prices"
            http_status = 200
        elif age_seconds <= 90 and heartbeat_status in ["healthy", "degraded"]:
            status = "degraded"
            message = "Worker may be slow or experiencing issues"
            http_status = 200  # Still return 200 for degraded - worker is running
        else:
            status = "unhealthy"
            message = "Worker appears to be stopped or failing"
            http_status = 503

        health_data = {
            "status": status,
            "message": message,
            "last_update": last_update.isoformat(),
            "age_seconds": int(age_seconds),
            "heartbeat_status": heartbeat_status,
            "heartbeat_age": int(heartbeat_age) if heartbeat_age else None,
            "stale_symbols": stale_symbols if stale_symbols else None,
            "total_symbols": len(symbols),
            "fresh_symbols": len(symbols) - len(stale_symbols),
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }

        # Return proper HTTP status for Render
        if http_status != 200:
            raise HTTPException(status_code=http_status, detail=health_data)

        return health_data

    except HTTPException:
        # Re-raise HTTP exceptions (our health check failures)
        raise
    except Exception as e:
        log_structured("error", "worker health check failed", error=str(e))
        error_data = {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }
        raise HTTPException(status_code=503, detail=error_data) from None
