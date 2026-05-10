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

from api.config import settings
from api.constants import (
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_KILL_SWITCH,
    REDIS_KEY_KILL_SWITCH_UPDATED_AT,
    REDIS_KEY_PRICES,
    REDIS_KEY_WORKER_HEARTBEAT,
    FieldName,
    LogType,
    ProposalStatus,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import is_db_available, runtime_mode
from api.services.dashboard_read_service import DashboardReadService
from api.services.dashboard_source_selector import DashboardReadSelector

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
read_service = DashboardReadService()
read_selector = DashboardReadSelector()

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


def _as_dict(payload: Any) -> dict[str, Any]:
    """Return payload as dict for mixed JSONB/text storage compatibility."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _timestamp_from_agent_data(data: dict[str, Any], now: datetime) -> str | None:
    """Return an ISO timestamp from mixed heartbeat fields."""
    for key in ("started_at", "last_seen_at", FieldName.UPDATED_AT):
        value = data.get(key)
        if value:
            return str(value)

    last_seen = data.get(FieldName.LAST_SEEN)
    try:
        ts = float(last_seen)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _timestamp_to_iso(value: Any) -> str | None:
    """Normalize DB, memory, and epoch timestamps to an ISO string."""
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _set_payload_status(record: dict[str, Any], status: str) -> None:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    payload[FieldName.STATUS] = status
    record[FieldName.PAYLOAD] = payload


def _proposal_matches(record: dict[str, Any], proposal_id: str) -> bool:
    payload = _as_dict(record.get(FieldName.PAYLOAD))
    candidates = {
        record.get("id"),
        record.get(FieldName.TRACE_ID),
        record.get(FieldName.MSG_ID),
        payload.get(FieldName.TRACE_ID),
        payload.get(FieldName.REFLECTION_TRACE_ID),
        payload.get(FieldName.MSG_ID),
    }
    return proposal_id in {str(candidate) for candidate in candidates if candidate is not None}


def _performance_trends_empty_payload(
    *, source: str | None = None, error: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": {
            "total_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        },
        "daily_pnl": [],
        "grade_trend": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if source:
        payload[FieldName.SOURCE] = source
    if error:
        payload[FieldName.ERROR] = error
    return payload


@router.get("/snapshot")
async def get_dashboard_snapshot() -> dict[str, Any]:
    """
    Get complete dashboard snapshot with all metrics.

    This is the primary endpoint for the UI dashboard.
    Returns sanitized data with no NaN values.
    Uses in-memory store directly when the database is unavailable.
    """
    return await read_selector.select_resource(
        resource_name="snapshot",
        db_source=lambda: _db_snapshot(),
        runtime_source=read_service.runtime_snapshot_payload,
        empty_source=read_service.empty_snapshot_payload,
    )


async def _db_snapshot() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_snapshot_payload(session)


@router.get("/state")
async def get_dashboard_state() -> dict[str, Any]:
    """
    Get raw dashboard state in the format the frontend expects.

    Returns orders[], positions[], agent_logs[] — same shape as the WebSocket
    dashboard_update snapshot so the UI can hydrate via REST when the WebSocket
    is slow to connect or unavailable.
    """
    try:
        data = await read_selector.select_resource(
            resource_name="state",
            db_source=lambda: _db_state(),
            runtime_source=read_service.runtime_state_payload,
            empty_source=read_service.empty_state_payload,
        )

        # Redis enrichment is best-effort: a Redis outage must not prevent
        # the frontend from receiving its DB-backed hydration data.
        try:
            redis_client = await get_redis()
        except Exception:
            log_structured("warning", "dashboard_state_redis_unavailable", exc_info=True)
            data.setdefault("mode", runtime_mode())
            db_up = is_db_available()
            data["degraded_mode"] = True
            data["degraded_reason"] = "db_unavailable" if not db_up else "redis_unavailable"
            return data

        # Enrich with current prices from Redis cache
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        keys = [REDIS_KEY_PRICES.format(symbol=s) for s in symbols]
        try:
            cached_values = await redis_client.mget(keys)
            prices: dict[str, Any] = {}
            for symbol, raw in zip(symbols, cached_values, strict=False):
                if raw:
                    try:
                        prices[symbol] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
            if prices:
                data["prices"] = prices
        except Exception:
            log_structured("warning", "dashboard_state_prices_failed", exc_info=True)

        # Enrich with IC weights from Redis
        try:
            raw_weights = await redis_client.get(REDIS_KEY_IC_WEIGHTS)
            if raw_weights:
                data["ic_weights"] = json.loads(raw_weights)
        except Exception:
            log_structured("warning", "dashboard_state_ic_weights_failed", exc_info=True)

        # Enrich with agent heartbeats from Redis (keys must match what agents write)
        try:
            agent_keys = [REDIS_AGENT_STATUS_KEY.format(name=n) for n in ALL_AGENT_NAMES]
            agent_values = await redis_client.mget(agent_keys)
            agent_statuses: list[dict[str, Any]] = []
            for name, raw in zip(ALL_AGENT_NAMES, agent_values, strict=False):
                if raw:
                    try:
                        status = json.loads(raw)
                        agent_statuses.append({"name": name, **status})
                    except (json.JSONDecodeError, TypeError):
                        agent_statuses.append({"name": name, "status": "unknown"})
                else:
                    agent_statuses.append({"name": name, "status": "offline"})
            data["agent_statuses"] = agent_statuses
        except Exception:
            log_structured("warning", "dashboard_state_agent_statuses_failed", exc_info=True)

        data.setdefault("mode", runtime_mode())
        db_up = is_db_available()
        data["degraded_mode"] = not db_up
        if not db_up:
            data["degraded_reason"] = "db_unavailable"
        # Expose whether the configured LLM provider has an API key so the
        # frontend can surface a "rule-based mode" banner instead of silently
        # showing no reasoning decisions.
        provider = settings.LLM_PROVIDER.lower().strip()
        provider_key_map = {
            "gemini": getattr(settings, "GEMINI_API_KEY", None),
            "anthropic": getattr(settings, "ANTHROPIC_API_KEY", None),
            "openai": getattr(settings, "OPENAI_API_KEY", None),
            "groq": getattr(settings, "GROQ_API_KEY", None),
        }
        llm_key = provider_key_map.get(provider) or ""
        data["llm_available"] = bool(llm_key and llm_key.strip())
        data["llm_provider"] = provider
        return data

    except Exception:
        log_structured("error", "dashboard state failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


async def _db_state() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_state_payload(session)


@router.get("/stream-lag")
async def get_stream_lag() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="stream_lag",
        db_source=_db_stream_lag,
        runtime_source=read_service.runtime_stream_lag_payload,
        empty_source=read_service.empty_stream_lag_payload,
    )


async def _db_stream_lag() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_stream_lag_payload(session)


@router.get("/system-health")
async def get_system_health() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="system_health",
        db_source=_db_system_health,
        runtime_source=read_service.runtime_system_health_payload,
        empty_source=read_service.empty_system_health_payload,
    )


async def _db_system_health() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_system_health_payload(session)


@router.get("/pnl")
async def get_pnl_metrics() -> dict[str, Any]:
    """Get PnL metrics."""
    return await read_selector.select_resource(
        resource_name="pnl",
        db_source=lambda: _db_pnl(),
        runtime_source=read_service.runtime_pnl_payload,
        empty_source=read_service.empty_pnl_payload,
    )


async def _db_pnl() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_pnl_payload(session)


@router.get("/pnl/paired")
async def get_paired_pnl(request: Request) -> dict[str, Any]:
    """Paired P&L view: closed BUY→SELL pairs with realized PnL + open positions
    with live unrealized PnL enriched from the Redis price cache.

    Closed trades come from ``trade_lifecycle`` (one row per completed round-trip).
    Open positions are read from the ``positions`` table and enriched with current
    price so unrealized PnL updates on every request.
    """
    redis_client = getattr(request.app.state, "redis_client", None)
    return await read_selector.select_resource(
        resource_name="paired_pnl",
        db_source=lambda: _db_paired_pnl(redis_client),
        runtime_source=read_service.runtime_paired_pnl_payload,
        empty_source=read_service.empty_paired_pnl_payload,
    )


async def _db_paired_pnl(redis_client: Any) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_paired_pnl_payload(session, redis_client)


@router.get("/agents")
async def get_agent_metrics() -> dict[str, Any]:
    """Get agent activity metrics."""
    return await read_selector.select_resource(
        resource_name="agents",
        db_source=lambda: _db_agents(),
        runtime_source=read_service.runtime_agents_payload,
        empty_source=read_service.empty_agents_payload,
    )


async def _db_agents() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_agents_payload(session)


@router.get("/orders")
async def get_order_metrics() -> dict[str, Any]:
    """Get order flow metrics."""
    return await read_selector.select_resource(
        resource_name="orders",
        db_source=lambda: _db_orders(),
        runtime_source=read_service.runtime_orders_payload,
        empty_source=read_service.empty_orders_payload,
    )


async def _db_orders() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_orders_payload(session)


@router.get("/positions")
async def get_positions() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="positions",
        db_source=lambda: _db_positions(),
        runtime_source=read_service.runtime_positions_payload,
        empty_source=read_service.empty_positions_payload,
    )


async def _db_positions() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_positions_payload(session)


@router.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="portfolio",
        db_source=lambda: _db_portfolio(),
        runtime_source=read_service.runtime_portfolio_payload,
        empty_source=read_service.empty_portfolio_payload,
    )


async def _db_portfolio() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_portfolio_payload(session)


@router.get("/lifecycle")
async def get_lifecycle() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="lifecycle",
        db_source=lambda: _db_lifecycle(),
        runtime_source=read_service.runtime_lifecycle_payload,
        empty_source=read_service.empty_lifecycle_payload,
    )


async def _db_lifecycle() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_lifecycle_payload(session)


@router.get("/agent-runs")
async def get_agent_runs() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="agent_runs",
        db_source=lambda: _db_agent_runs(),
        runtime_source=read_service.runtime_agent_runs_payload,
        empty_source=read_service.empty_agent_runs_payload,
    )


async def _db_agent_runs() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_agent_runs_payload(session)


@router.get("/notifications")
async def get_notifications() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="notifications",
        db_source=lambda: _db_notifications(),
        runtime_source=read_service.runtime_notifications_payload,
        empty_source=read_service.empty_notifications_payload,
    )


async def _db_notifications() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_notifications_payload(session)


@router.get("/flow-status")
async def get_flow_status() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="flow_status",
        db_source=_db_flow_status,
        runtime_source=read_service.runtime_flow_status_payload,
        empty_source=read_service.empty_flow_status_payload,
    )


async def _db_flow_status() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_flow_status_payload(session)


@router.get("/prices")
async def get_prices() -> dict[str, Any]:
    """
    Get current market prices from Redis cache.

    This provides instant price data for dashboard initial load,
    without requiring WebSocket connection.
    """
    return await read_selector.select_resource(
        resource_name="prices",
        db_source=lambda: read_service.runtime_prices_payload(),
        runtime_source=lambda: read_service.runtime_prices_payload(),
        empty_source=read_service.empty_prices_payload,
    )


@router.get("/agents/status")
async def get_agents_status() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="agents_status",
        db_source=read_service.db_agents_status_payload,
        runtime_source=read_service.runtime_agents_status_payload,
        empty_source=read_service.empty_agents_status_payload,
    )


@router.get("/system/metrics")
@router.get("/system-metrics")
async def get_system_stream_metrics() -> dict[str, Any]:
    """Get Redis stream lengths for pipeline health display."""
    return await read_selector.select_resource(
        resource_name="system_metrics",
        db_source=lambda: _db_system_metrics(),
        runtime_source=lambda: read_service.runtime_system_metrics_stream_payload(),
        empty_source=read_service.empty_system_metrics_payload,
    )


async def _db_system_metrics() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_system_metrics_payload(session)


@router.get("/events/recent")
async def get_recent_events() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="recent_events",
        db_source=_db_recent_events,
        runtime_source=read_service.runtime_recent_events_payload,
        empty_source=read_service.empty_recent_events_payload,
    )


async def _db_recent_events() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_recent_events_payload(session)


@router.get("/history/events")
async def get_event_history(limit: int = 50) -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="event_history",
        db_source=lambda: _db_event_history(limit),
        runtime_source=lambda: read_service.runtime_event_history_payload(limit),
        empty_source=read_service.empty_event_history_payload,
    )


async def _db_event_history(limit: int) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_event_history_payload(session, limit)


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
        keys = [REDIS_KEY_PRICES.format(symbol=symbol) for symbol in symbols] + [
            REDIS_KEY_WORKER_HEARTBEAT
        ]
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
                    timestamp_str = price_data.get(FieldName.TIMESTAMP)
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
    return await read_selector.select_resource(
        resource_name="proposals_panel",
        db_source=_db_proposals_panel,
        runtime_source=read_service.runtime_proposals_panel_payload,
        empty_source=read_service.empty_proposals_panel_payload,
    )


async def _db_proposals_panel() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_proposals_panel_payload(session)


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict[str, Any]:
    """Mark a strategy proposal as approved."""
    if not is_db_available():
        if not read_service.update_in_memory_proposal_status(proposal_id, ProposalStatus.APPROVED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.APPROVED, "id": proposal_id, "source": "in_memory"}

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
                data[FieldName.STATUS] = "approved"
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
    if not is_db_available():
        if not read_service.update_in_memory_proposal_status(proposal_id, ProposalStatus.REJECTED):
            raise HTTPException(status_code=404, detail="Proposal not found") from None
        return {"status": ProposalStatus.REJECTED, "id": proposal_id, "source": "in_memory"}

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
                data[FieldName.STATUS] = "rejected"
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
    return await read_selector.select_resource(
        resource_name="learning_proposals",
        db_source=lambda: _db_learning_proposals(limit=limit),
        runtime_source=lambda: read_service.runtime_learning_proposals_payload(limit=limit),
        empty_source=read_service.empty_learning_proposals_payload,
    )


@router.get("/learning/grades")
async def get_grade_history(limit: int = 50) -> dict[str, Any]:
    """Get recent agent grade history from agent_grades table and agent_logs."""
    return await read_selector.select_resource(
        resource_name="learning_grades",
        db_source=lambda: _db_learning_grades(limit=limit),
        runtime_source=lambda: read_service.runtime_learning_grades_payload(limit=limit),
        empty_source=read_service.empty_learning_grades_payload,
    )


@router.get("/learning/ic-weights")
async def get_ic_weights() -> dict[str, Any]:
    """Get current IC factor weights from Redis."""
    return await read_selector.select_resource(
        resource_name="learning_ic_weights",
        db_source=_db_learning_ic_weights,
        runtime_source=read_service.runtime_learning_ic_weights_payload,
        empty_source=read_service.empty_learning_ic_weights_payload,
    )


@router.get("/learning/reflections")
async def get_reflections(limit: int = 20) -> dict[str, Any]:
    """Get recent reflection outputs from agent_logs."""
    return await read_selector.select_resource(
        resource_name="learning_reflections",
        db_source=lambda: _db_learning_reflections(limit=limit),
        runtime_source=lambda: read_service.runtime_learning_reflections_payload(limit=limit),
        empty_source=read_service.empty_learning_reflections_payload,
    )


@router.patch("/learning/proposals/{trace_id}")
async def update_proposal_status(
    trace_id: str, status: str = Body(..., embed=True)
) -> dict[str, Any]:
    """Persist proposal approval or rejection back to agent_logs payload."""
    if status not in {ProposalStatus.APPROVED, ProposalStatus.REJECTED}:
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    if not is_db_available():
        if not read_service.update_in_memory_proposal_status(trace_id, status):
            raise HTTPException(status_code=404, detail="Proposal not found")
        return {"trace_id": trace_id, "status": status, "source": "in_memory"}

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("""
                    UPDATE agent_logs
                    SET payload = (payload::jsonb || jsonb_build_object('status', :status::text))::text
                    WHERE trace_id = :trace_id AND log_type = :log_type
                    RETURNING trace_id
                """),
                {"trace_id": trace_id, "status": status, "log_type": LogType.PROPOSAL},
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


@router.get("/learning/loop")
@router.get("/learning/loop/status")
async def get_learning_loop_state() -> dict[str, Any]:
    """Snapshot of the learning-loop control plane.

    Returns: latest grade, recent proposals (with applied_at if ProposalApplier
    has acted on them), per-symbol × signal-type loss attribution, and the
    current Redis control-plane state (trading_paused, signal_weight_scale,
    suspended agents). The frontend "Learning Loop" panel renders this.
    """
    return await read_selector.select_resource(
        resource_name="learning_loop",
        db_source=_db_learning_loop,
        runtime_source=read_service.runtime_learning_loop_payload,
        empty_source=read_service.empty_learning_loop_payload,
    )


async def _db_learning_proposals(limit: int) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_learning_proposals_payload(session, limit=limit)


async def _db_learning_grades(limit: int) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_learning_grades_payload(session, limit=limit)


async def _db_learning_ic_weights() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_learning_ic_weights_payload(session)


async def _db_learning_reflections(limit: int) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_learning_reflections_payload(session, limit=limit)


async def _db_learning_loop() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_learning_loop_payload(session)


# ---------------------------------------------------------------------------
# Trace view
# ---------------------------------------------------------------------------


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    payload = await read_selector.select_resource(
        resource_name="trace",
        db_source=lambda: _db_trace(trace_id),
        runtime_source=lambda: read_service.runtime_trace_payload(trace_id),
        empty_source=lambda: read_service.empty_trace_payload(trace_id),
    )
    if not payload["agent_runs"] and not payload["agent_logs"] and not payload["agent_grades"]:
        raise HTTPException(status_code=404, detail="Trace not found") from None
    return payload


async def _db_trace(trace_id: str) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_trace_payload(session, trace_id)


@router.get("/trade-feed")
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, Any]:
    """Return the most recent trades with full lifecycle state.

    Each row shows what happened end-to-end: filled price, P&L, grade, and
    whether a reflection has been written.  The frontend displays these as a
    clear "Bought AAPL 100 @ $150 → +$23.50 (A)" feed.

    When ``count`` is 0 the response includes ``empty_reason`` to explain why:
    - ``db_degraded``            — DB unavailable; in-memory store also has no fills
    - ``no_orders_executed``     — DB reachable but orders table is empty
    - ``lifecycle_not_persisted``— orders exist but no trade_lifecycle rows yet
    - ``no_executable_intents``  — decisions were gated (HOLD/score/market) by EE
    """
    return await read_selector.select_resource(
        resource_name="trade_feed",
        db_source=lambda: _db_trade_feed(limit=limit, session_id=session_id),
        runtime_source=lambda: read_service.runtime_trade_feed_payload(limit=limit),
        empty_source=read_service.empty_trade_feed_payload,
        is_empty=lambda payload: payload.get("count", 0) == 0,
    )


async def _db_trade_feed(limit: int, session_id: str | None) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_trade_feed_payload(session, limit=limit, session_id=session_id)


# ---------------------------------------------------------------------------
# Performance trends — agent grade history + P&L by day
# ---------------------------------------------------------------------------


@router.get("/performance-trends")
async def get_performance_trends() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="performance_trends",
        db_source=_db_performance_trends,
        runtime_source=read_service.runtime_performance_trends_payload,
        empty_source=read_service.empty_performance_trends_payload,
    )


async def _db_performance_trends() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_performance_trends_payload(session)


@router.get("/agent-instances")
async def get_agent_instances() -> dict[str, Any]:
    return await read_selector.select_resource(
        resource_name="agent_instances",
        db_source=_db_agent_instances,
        runtime_source=read_service.runtime_agent_instances_payload,
        empty_source=read_service.empty_agent_instances_payload,
    )


async def _db_agent_instances() -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await read_service.db_agent_instances_payload(session)


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
    return await read_selector.select_resource(
        resource_name="challengers",
        db_source=lambda: read_service.db_challengers_payload(request),
        runtime_source=read_service.runtime_challengers_payload,
        empty_source=read_service.empty_challengers_payload,
    )


@router.get("/kill-switch")
async def get_kill_switch() -> dict[str, Any]:
    """Get current kill switch state."""
    try:
        redis_client = await get_redis()
        value = await redis_client.get(REDIS_KEY_KILL_SWITCH)
        updated_at = await redis_client.get(REDIS_KEY_KILL_SWITCH_UPDATED_AT)
        return {
            "active": value == "1",
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "kill_switch_read_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("/kill-switch")
async def toggle_kill_switch(active: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle the trading kill switch."""
    try:
        redis_client = await get_redis()
        await redis_client.set(REDIS_KEY_KILL_SWITCH, "1" if active else "0")
        await redis_client.set(
            REDIS_KEY_KILL_SWITCH_UPDATED_AT, datetime.now(timezone.utc).isoformat()
        )
        log_structured(
            "info",
            "kill_switch_toggled",
            active=active,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "active": active,
            "message": f"Kill switch {'activated' if active else 'deactivated'}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "kill switch toggle failed", active=active, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from None
