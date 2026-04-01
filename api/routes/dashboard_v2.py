"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
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


# ---------------------------------------------------------------------------
# Proposals panel
# ---------------------------------------------------------------------------


@router.get("/proposals")
async def get_proposals() -> dict[str, Any]:
    """Get recent strategy proposals from events table."""
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT id, data, created_at, source
                    FROM events
                    WHERE event_type = 'strategy.proposal'
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
            )
            rows = result.all()
            proposals = []
            for row in rows:
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                proposals.append(
                    {
                        "id": str(row[0]),
                        "symbol": data.get("symbol"),
                        "action": data.get("action"),
                        "grade_score": data.get("grade_score"),
                        "bias": data.get("bias"),
                        "buys": data.get("buys"),
                        "sells": data.get("sells"),
                        "strategy_name": data.get("strategy_name"),
                        "trace_id": data.get("trace_id"),
                        "created_at": row[2].isoformat() if row[2] else None,
                        "source": row[3],
                        "status": data.get("status", "pending"),
                    }
                )
        return {
            "proposals": proposals,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "proposals fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as approved."""
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {"id": proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data["status"] = "approved"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), "id": proposal_id},
                )
        return {"status": "approved", "id": proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal approve failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as rejected."""
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        "SELECT id, data FROM events "
                        "WHERE id = :id AND event_type = 'strategy.proposal'"
                    ),
                    {"id": proposal_id},
                )
                row = result.first()
                if not row:
                    raise HTTPException(status_code=404, detail="Proposal not found") from None
                raw = row[1]
                data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                data["status"] = "rejected"
                await session.execute(
                    text("UPDATE events SET data = :data WHERE id = :id"),
                    {"data": json.dumps(data), "id": proposal_id},
                )
        return {"status": "rejected", "id": proposal_id}
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "proposal reject failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Trace view
# ---------------------------------------------------------------------------


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    """Return the full trace for a trace_id: agent_runs + agent_logs + agent_grades."""
    try:
        async with AsyncSessionFactory() as session:
            run_result = await session.execute(
                text("""
                    SELECT id, source, run_type, status,
                           input_data, output_data, execution_time_ms, created_at
                    FROM agent_runs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            runs = [
                {
                    "id": str(r[0]),
                    "agent_name": r[1],
                    "run_type": r[2],
                    "status": r[3],
                    "input_data": r[4],
                    "output_data": r[5],
                    "execution_time_ms": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in run_result.all()
            ]

            log_result = await session.execute(
                text("""
                    SELECT id, log_type, payload, created_at
                    FROM agent_logs
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            logs = [
                {
                    "id": str(lg[0]),
                    "log_type": lg[1],
                    "payload": lg[2],
                    "created_at": lg[3].isoformat() if lg[3] else None,
                }
                for lg in log_result.all()
            ]

            grade_result = await session.execute(
                text("""
                    SELECT id, agent_id, grade_type, score, metrics, created_at
                    FROM agent_grades
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC
                """),
                {"trace_id": trace_id},
            )
            grades = [
                {
                    "id": str(g[0]),
                    "agent_id": str(g[1]),
                    "grade_type": g[2],
                    "score": float(g[3]) if g[3] is not None else None,
                    "metrics": g[4],
                    "created_at": g[5].isoformat() if g[5] else None,
                }
                for g in grade_result.all()
            ]

        if not runs and not logs and not grades:
            raise HTTPException(status_code=404, detail="Trace not found") from None

        return {
            "trace_id": trace_id,
            "agent_runs": runs,
            "agent_logs": logs,
            "agent_grades": grades,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "trace fetch failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
