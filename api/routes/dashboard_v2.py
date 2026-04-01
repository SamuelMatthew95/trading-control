"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
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


# ---------------------------------------------------------------------------
# Proposals panel (queries events table)
# ---------------------------------------------------------------------------


@router.get("/proposals")
async def list_proposals() -> dict[str, Any]:
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
# Learning analytics
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Trade feed — end-to-end lifecycle per trade
# ---------------------------------------------------------------------------


@router.get("/trade-feed")
async def get_trade_feed(limit: int = 50) -> dict[str, Any]:
    """Return the most recent trades with full lifecycle state.

    Each row shows what happened end-to-end: filled price, P&L, grade, and
    whether a reflection has been written.  The frontend displays these as a
    clear "Bought AAPL 100 @ $150 → +$23.50 (A)" feed.
    """
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id, symbol, side, qty, entry_price, exit_price,
                        pnl, pnl_percent, order_id,
                        execution_trace_id, signal_trace_id,
                        grade, grade_score, grade_label,
                        status, filled_at, graded_at, reflected_at,
                        created_at
                    FROM trade_lifecycle
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": min(limit, 200)},
            )
            rows = result.all()

        def _fmt(row: Any) -> dict[str, Any]:
            pnl = float(row[6]) if row[6] is not None else None
            pnl_pct = float(row[7]) if row[7] is not None else None
            return {
                "id": str(row[0]),
                "symbol": row[1],
                "side": row[2],
                "qty": float(row[3]) if row[3] is not None else None,
                "entry_price": float(row[4]) if row[4] is not None else None,
                "exit_price": float(row[5]) if row[5] is not None else None,
                "pnl": round(pnl, 2) if pnl is not None else None,
                "pnl_percent": round(pnl_pct, 4) if pnl_pct is not None else None,
                "order_id": str(row[8]) if row[8] else None,
                "execution_trace_id": row[9],
                "signal_trace_id": row[10],
                "grade": row[11],
                "grade_score": float(row[12]) if row[12] is not None else None,
                "grade_label": row[13],
                "status": row[14],
                "filled_at": row[15].isoformat() if row[15] else None,
                "graded_at": row[16].isoformat() if row[16] else None,
                "reflected_at": row[17].isoformat() if row[17] else None,
                "created_at": row[18].isoformat() if row[18] else None,
            }

        return {
            "trades": [_fmt(r) for r in rows],
            "count": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "trade_feed_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Performance trends — agent grade history + P&L by day
# ---------------------------------------------------------------------------


@router.get("/performance-trends")
async def get_performance_trends() -> dict[str, Any]:
    """Return agent grade history and daily P&L for the last 30 days."""
    try:
        async with AsyncSessionFactory() as session:
            # Daily P&L from trade_lifecycle
            pnl_result = await session.execute(
                text("""
                    SELECT
                        DATE(filled_at AT TIME ZONE 'UTC') AS day,
                        SUM(pnl)                           AS daily_pnl,
                        COUNT(*)                           AS trade_count,
                        COUNT(*) FILTER (WHERE pnl > 0)    AS wins,
                        COUNT(*) FILTER (WHERE pnl <= 0)   AS losses,
                        AVG(pnl)                           AS avg_pnl
                    FROM trade_lifecycle
                    WHERE filled_at >= NOW() - INTERVAL '30 days'
                      AND status IN ('filled', 'graded', 'reflected')
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            daily_pnl = [
                {
                    "day": str(r[0]),
                    "pnl": round(float(r[1]), 2) if r[1] is not None else 0.0,
                    "trade_count": int(r[2]),
                    "wins": int(r[3]),
                    "losses": int(r[4]),
                    "avg_pnl": round(float(r[5]), 2) if r[5] is not None else 0.0,
                }
                for r in pnl_result.all()
            ]

            # Grade distribution from agent_grades
            grade_result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at AT TIME ZONE 'UTC') AS day,
                        AVG(score) * 100                    AS avg_score_pct
                    FROM agent_grades
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY day
                    ORDER BY day DESC
                """)
            )
            grade_trend = [
                {
                    "day": str(r[0]),
                    "avg_score_pct": round(float(r[1]), 1) if r[1] is not None else None,
                }
                for r in grade_result.all()
            ]

            # Summary stats
            summary_result = await session.execute(
                text("""
                    SELECT
                        COALESCE(SUM(pnl), 0)                       AS total_pnl,
                        COUNT(*)                                     AS total_trades,
                        COUNT(*) FILTER (WHERE pnl > 0)             AS total_wins,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) AS avg_win,
                        COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0) AS avg_loss,
                        COALESCE(MAX(pnl), 0)                        AS best_trade,
                        COALESCE(MIN(pnl), 0)                        AS worst_trade
                    FROM trade_lifecycle
                    WHERE status IN ('filled', 'graded', 'reflected')
                """)
            )
            s = summary_result.first()
            total_trades = int(s[1]) if s else 0
            total_wins = int(s[2]) if s else 0
            summary = {
                "total_pnl": round(float(s[0]), 2) if s else 0.0,
                "total_trades": total_trades,
                "win_rate": round(total_wins / total_trades * 100, 1) if total_trades else 0.0,
                "avg_win": round(float(s[3]), 2) if s else 0.0,
                "avg_loss": round(float(s[4]), 2) if s else 0.0,
                "best_trade": round(float(s[5]), 2) if s else 0.0,
                "worst_trade": round(float(s[6]), 2) if s else 0.0,
            }

        return {
            "summary": summary,
            "daily_pnl": daily_pnl,
            "grade_trend": grade_trend,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "performance_trends_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Agent instances — lifecycle view
# ---------------------------------------------------------------------------


@router.get("/agent-instances")
async def get_agent_instances() -> dict[str, Any]:
    """Return all agent instances with lifecycle info.

    Active instances show how long they have been running and how many events
    they have processed.  Retired instances are kept for audit.
    """
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        id, instance_key, pool_name, status,
                        started_at, retired_at, event_count, metadata,
                        EXTRACT(EPOCH FROM (
                            COALESCE(retired_at, NOW()) - started_at
                        ))::int AS uptime_seconds
                    FROM agent_instances
                    ORDER BY started_at DESC
                    LIMIT 100
                """)
            )
            rows = result.all()

        instances = [
            {
                "id": str(r[0]),
                "instance_key": r[1],
                "pool_name": r[2],
                "status": r[3],
                "started_at": r[4].isoformat() if r[4] else None,
                "retired_at": r[5].isoformat() if r[5] else None,
                "event_count": int(r[6]) if r[6] is not None else 0,
                "uptime_seconds": int(r[8]) if r[8] is not None else 0,
            }
            for r in rows
        ]

        active = [i for i in instances if i["status"] == "active"]
        retired = [i for i in instances if i["status"] == "retired"]

        return {
            "instances": instances,
            "active_count": len(active),
            "retired_count": len(retired),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "agent_instances_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


# ---------------------------------------------------------------------------
# Challenger agent management
# ---------------------------------------------------------------------------


@router.post("/challengers/spawn")
async def spawn_challenger(
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Spawn a new ChallengerAgent from an approved new_agent proposal.

    Body: { "challenger_config": {...}, "max_fills": 200 }

    The challenger runs in parallel with the existing pipeline agents,
    tracks its own grades, and retires itself after max_fills events,
    publishing a summary to the proposals stream.
    """
    try:
        from api.services.agents.pipeline_agents import ChallengerAgent

        event_bus = getattr(request.app.state, "event_bus", None)
        dlq_manager = getattr(request.app.state, "dlq_manager", None)
        agents: list[Any] = getattr(request.app.state, "agents", [])

        if event_bus is None or dlq_manager is None:
            raise HTTPException(status_code=503, detail="Event bus not ready") from None

        challenger_config = body.get("challenger_config", {})
        max_fills = int(body.get("max_fills", ChallengerAgent.DEFAULT_MAX_FILLS))

        challenger = ChallengerAgent(
            event_bus,
            dlq_manager,
            challenger_config=challenger_config,
            max_fills=max_fills,
        )
        await challenger.start()
        agents.append(challenger)

        log_structured(
            "info",
            "challenger_spawned",
            challenger_id=challenger._challenger_id,
            instance_id=challenger._instance_id,
            max_fills=max_fills,
        )
        return {
            "challenger_id": challenger._challenger_id,
            "instance_id": challenger._instance_id,
            "consumer": challenger.consumer,
            "max_fills": max_fills,
            "status": "spawned",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        log_structured("error", "challenger_spawn_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/challengers")
async def list_challengers(request: Request) -> dict[str, Any]:
    """List all active challenger agent instances."""
    try:
        from api.services.agents.pipeline_agents import ChallengerAgent

        agents: list[Any] = getattr(request.app.state, "agents", [])
        challengers = [a for a in agents if isinstance(a, ChallengerAgent)]

        return {
            "challengers": [
                {
                    "challenger_id": c._challenger_id,
                    "instance_id": c._instance_id,
                    "consumer": c.consumer,
                    "fills": c._fills,
                    "max_fills": c._max_fills,
                    "config": c._config,
                    "running": c._running,
                }
                for c in challengers
            ],
            "count": len(challengers),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "challengers_list_failed", exc_info=True)
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
