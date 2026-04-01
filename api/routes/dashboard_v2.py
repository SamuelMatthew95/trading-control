"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.services.metrics_aggregator import MetricsAggregator

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

    except Exception:
        log_structured("error", "dashboard snapshot failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


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

    except Exception:
        log_structured("error", "stream lag failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/system-health")
async def get_system_health() -> dict[str, Any]:
    """Get system health metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_system_health()

    except Exception:
        log_structured("error", "system health failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/pnl")
async def get_pnl_metrics() -> dict[str, Any]:
    """Get PnL metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_pnl_metrics()

    except Exception:
        log_structured("error", "pnl metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/agents")
async def get_agent_metrics() -> dict[str, Any]:
    """Get agent activity metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_agent_metrics()

    except Exception:
        log_structured("error", "agent metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/orders")
async def get_order_metrics() -> dict[str, Any]:
    """Get order flow metrics."""
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_order_metrics()

    except Exception:
        log_structured("error", "order metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


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

    except Exception:
        log_structured("error", "price cache failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/agents/status")
async def get_agents_status() -> dict[str, Any]:
    """Get agent status from Redis heartbeats."""
    try:
        redis_client = await get_redis()
        agent_names = [
            "SIGNAL_AGENT",
            "REASONING_AGENT",
            "EXECUTION_ENGINE",
            "GRADE_AGENT",
            "IC_UPDATER",
            "REFLECTION_AGENT",
            "STRATEGY_PROPOSER",
            "NOTIFICATION_AGENT",
        ]
        now = int(datetime.now(timezone.utc).timestamp())
        agents = []
        for name in agent_names:
            raw = await redis_client.get(f"agent:status:{name}")
            if raw:
                data = json.loads(raw)
                last_seen = data.get("last_seen", 0)
                age = now - last_seen
                if age > 120:
                    status = "STALE"
                else:
                    status = data.get("status", "ACTIVE")
                agents.append(
                    {
                        "name": name,
                        "status": status,
                        "event_count": data.get("event_count", 0),
                        "last_event": data.get("last_event", ""),
                        "last_seen": last_seen,
                        "seconds_ago": age,
                    }
                )
            else:
                agents.append(
                    {
                        "name": name,
                        "status": "WAITING",
                        "event_count": 0,
                        "last_event": "",
                        "last_seen": 0,
                        "seconds_ago": 0,
                    }
                )

        return {
            "agents": agents,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "agents status failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/system/metrics")
async def get_system_stream_metrics() -> dict[str, Any]:
    """Get Redis stream lengths for pipeline health display."""
    try:
        redis_client = await get_redis()

        streams = {
            "market_events": "market_events",
            "signals": "signals",
            "decisions": "decisions",
            "graded_decisions": "graded_decisions",
        }

        result = {}
        for key, stream_name in streams.items():
            try:
                result[key] = await redis_client.xlen(stream_name)
            except Exception:
                result[key] = 0

        # agent_logs count from DB
        try:
            async with AsyncSessionFactory() as session:
                row = await session.execute(text("SELECT COUNT(*) FROM agent_logs"))
                result["agent_logs"] = row.scalar() or 0
        except Exception:
            result["agent_logs"] = 0

        # trade_alerts count from events table
        try:
            async with AsyncSessionFactory() as session:
                row = await session.execute(
                    text("SELECT COUNT(*) FROM events WHERE event_type = 'trade.alert'")
                )
                result["trade_alerts"] = row.scalar() or 0
        except Exception:
            result["trade_alerts"] = 0

        return {
            **result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "system metrics failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/events/recent")
async def get_recent_events() -> dict[str, Any]:
    """Get last 10 events from events table."""
    try:
        async with AsyncSessionFactory() as session:
            from sqlalchemy import text

            result = await session.execute(
                text("""
                    SELECT id, event_type, entity_type, source, created_at
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
            )
            rows = result.all()
            events = [
                {
                    "id": str(row[0]),
                    "event_type": row[1],
                    "entity_type": row[2],
                    "source": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]
        return {
            "events": events,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "recent events failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


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
            log_structured("warning", "redis connection failed during health check", exc_info=True)
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
            log_structured("warning", "redis read failed during health check", exc_info=True)
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
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
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
                heartbeat_time = datetime.fromisoformat(heartbeat_value.replace("Z", "+00:00"))
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
        log_structured("error", "worker health check failed", exc_info=True)
        error_data = {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "uptime_seconds": uptime_seconds,
            "check_time": now.isoformat(),
        }
        raise HTTPException(status_code=503, detail=error_data) from None


@router.get("/learning/proposals")
async def get_proposals(limit: int = 50) -> dict[str, Any]:
    """Get recent strategy proposals from agent_logs."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = 'proposal'
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            rows = result.all()
        proposals = [
            {
                "id": row[0],
                "proposal_type": row[1].get("proposal_type", "parameter_change"),
                "content": row[1].get("content", {}),
                "requires_approval": row[1].get("requires_approval", True),
                "confidence": row[1].get("confidence"),
                "reflection_trace_id": row[1].get("reflection_trace_id"),
                "status": row[1].get("status", "pending"),
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
        return {
            "proposals": proposals,
            "total": len(proposals),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/learning/grades")
async def get_grade_history(limit: int = 50) -> dict[str, Any]:
    """Get recent agent grade history from agent_grades table and agent_logs."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = 'grade'
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            rows = result.all()
        grades = [
            {
                "trace_id": row[0],
                "grade": row[1].get("grade"),
                "score": row[1].get("score"),
                "score_pct": row[1].get("score_pct"),
                "metrics": row[1].get("metrics", {}),
                "fills_graded": row[1].get("fills_graded"),
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
        return {
            "grades": grades,
            "total": len(grades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "grades fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/learning/ic-weights")
async def get_ic_weights() -> dict[str, Any]:
    """Get current IC factor weights from Redis."""
    try:
        redis_client = await get_redis()
        raw = await redis_client.get("alpha:ic_weights")
        weights = json.loads(raw) if raw else {}
        history_result: list[dict[str, Any]] = []
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT factor_name, ic_score, computed_at
                        FROM factor_ic_history
                        ORDER BY computed_at DESC
                        LIMIT 20
                    """)
                )
                rows = result.all()
                history_result = [
                    {
                        "factor": row[0],
                        "ic_score": float(row[1]),
                        "computed_at": row[2].isoformat() if row[2] else None,
                    }
                    for row in rows
                ]
        except Exception:
            pass
        return {
            "current_weights": weights,
            "history": history_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "ic weights fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/learning/reflections")
async def get_reflections(limit: int = 20) -> dict[str, Any]:
    """Get recent reflection outputs from agent_logs."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT trace_id, payload, created_at
                    FROM agent_logs
                    WHERE log_type = 'reflection'
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            rows = result.all()
        reflections = [
            {
                "trace_id": row[0],
                "summary": row[1].get("summary", ""),
                "hypotheses": row[1].get("hypotheses", []),
                "winning_factors": row[1].get("winning_factors", []),
                "losing_factors": row[1].get("losing_factors", []),
                "regime_edge": row[1].get("regime_edge", {}),
                "fills_analyzed": row[1].get("fills_analyzed"),
                "timestamp": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]
        return {
            "reflections": reflections,
            "total": len(reflections),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "reflections fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.patch("/learning/proposals/{trace_id}")
async def update_proposal_status(
    trace_id: str, status: str = Body(..., embed=True)
) -> dict[str, Any]:
    """Persist proposal approval or rejection back to agent_logs payload."""
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    UPDATE agent_logs
                    SET payload = payload || jsonb_build_object('status', :status::text)
                    WHERE trace_id = :trace_id AND log_type = 'proposal'
                    RETURNING trace_id
                """),
                {"trace_id": trace_id, "status": status},
            )
            updated = result.fetchone()
            await session.commit()
        if updated is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal_status_update_failed", trace_id=trace_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/trade-feed")
async def get_trade_feed() -> dict[str, Any]:
    """Get recent trade activity and agent logs for trade feed display."""
    try:
        async with AsyncSessionFactory() as session:
            # Get recent agent logs related to trading
            result = await session.execute(
                text("""
                    SELECT log_type, payload, created_at
                    FROM agent_logs
                    WHERE log_type IN ('signal', 'decision', 'execution', 'grade')
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
            )
            rows = result.all()

            trade_feed = []
            for row in rows:
                payload = row[1] or {}
                trade_feed.append({
                    "type": row[0],
                    "action": payload.get("action", "unknown"),
                    "symbol": payload.get("symbol", ""),
                    "message": payload.get("message", payload.get("primary_edge", "")),
                    "confidence": payload.get("confidence"),
                    "timestamp": row[2].isoformat() if row[2] else None,
                })

            return {
                "trade_feed": trade_feed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        log_structured("error", "trade feed failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/agent-instances")
async def get_agent_instances() -> dict[str, Any]:
    """Get current agent instances and their status."""
    try:
        redis_client = await get_redis()
        agent_names = [
            "SIGNAL_AGENT",
            "REASONING_AGENT",
            "EXECUTION_ENGINE",
            "GRADE_AGENT",
            "IC_UPDATER",
            "REFLECTION_AGENT",
            "STRATEGY_PROPOSER",
            "NOTIFICATION_AGENT",
        ]
        now = int(datetime.now(timezone.utc).timestamp())
        agents = []

        for name in agent_names:
            raw = await redis_client.get(f"agent:status:{name}")
            if raw:
                data = json.loads(raw)
                last_seen = data.get("last_seen", 0)
                age = now - last_seen
                if age > 120:
                    status = "STALE"
                else:
                    status = data.get("status", "ACTIVE")
                agents.append({
                    "name": name,
                    "status": status,
                    "event_count": data.get("event_count", 0),
                    "last_event": data.get("last_event", ""),
                    "last_seen": last_seen,
                    "seconds_ago": age,
                    "type": data.get("type", "agent"),
                })
            else:
                agents.append({
                    "name": name,
                    "status": "WAITING",
                    "event_count": 0,
                    "last_event": "",
                    "last_seen": 0,
                    "seconds_ago": 0,
                    "type": "agent",
                })

        return {
            "agents": agents,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "agent instances failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/performance-trends")
async def get_performance_trends() -> dict[str, Any]:
    """Get performance trends and analytics data."""
    try:
        async with AsyncSessionFactory() as session:
            # Get PnL trends over time
            pnl_result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at) as date,
                        SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as profits,
                        SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as losses,
                        SUM(pnl) as net_pnl,
                        COUNT(*) as trade_count
                    FROM orders
                    WHERE created_at >= DATE('now', '-30 days')
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                    LIMIT 30
                """)
            )
            pnl_rows = pnl_result.all()

            performance_trends = []
            for row in pnl_rows:
                performance_trends.append({
                    "date": row[0].isoformat() if row[0] else None,
                    "profits": float(row[1]) if row[1] else 0.0,
                    "losses": float(row[2]) if row[2] else 0.0,
                    "net_pnl": float(row[3]) if row[3] else 0.0,
                    "trade_count": row[4] if row[4] else 0,
                })

            # Get win rate trends
            win_rate_result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at) as date,
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades
                    FROM orders
                    WHERE created_at >= DATE('now', '-30 days')
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                    LIMIT 30
                """)
            )
            win_rate_rows = win_rate_result.all()

            win_rate_trends = []
            for row in win_rate_rows:
                win_rate = (row[2] / row[1] * 100) if row[1] > 0 else 0.0
                win_rate_trends.append({
                    "date": row[0].isoformat() if row[0] else None,
                    "win_rate": win_rate,
                    "total_trades": row[1] if row[1] else 0,
                    "winning_trades": row[2] if row[2] else 0,
                })

            return {
                "pnl_trends": performance_trends,
                "win_rate_trends": win_rate_trends,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception:
        log_structured("error", "performance trends failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/kill-switch")
async def toggle_kill_switch(active: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle the trading kill switch."""
    try:
        redis_client = await get_redis()

        # Store kill switch state in Redis
        await redis_client.set("kill_switch:active", "true" if active else "false")
        await redis_client.set("kill_switch:updated_at", datetime.now(timezone.utc).isoformat())

        # Log the action
        log_structured(
            "info",
            "kill_switch_toggled",
            active=active,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        return {
            "active": active,
            "message": f"Kill switch {'activated' if active else 'deactivated'}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "kill switch toggle failed", active=active, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
