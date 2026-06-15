import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from api.constants import (
    PRICE_STALE_SECONDS,
    REDIS_KEY_PRICES,
    REDIS_KEY_WORKER_HEARTBEAT,
    STREAM_DECISIONS,
    STREAM_GRADED_DECISIONS,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available, runtime_mode
from api.services.metrics_aggregator import MetricsAggregator, filter_fresh_prices


async def get_stream_lag_payload() -> dict[str, Any]:
    """Get stream lag metrics per stream."""
    if not is_db_available():
        return {
            FieldName.STREAM_LAG: {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            lag_metrics = await aggregator.get_stream_lag_metrics()
            return {
                FieldName.STREAM_LAG: lag_metrics,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    except Exception:
        log_structured("warning", "stream_lag_db_unavailable", exc_info=True)
        return {
            FieldName.STREAM_LAG: [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_system_health_payload() -> dict[str, Any]:
    """Get system health metrics."""
    if not is_db_available():
        return await MetricsAggregator(None, use_memory_store=True).get_system_health()

    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_system_health()

    except Exception:
        log_structured("warning", "system_health_db_unavailable", exc_info=True)
        store = get_runtime_store()
        return {
            "status": "degraded",
            FieldName.MODE: runtime_mode(),
            FieldName.DB_HEALTH: store.last_health,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_system_stream_metrics_payload() -> dict[str, Any]:
    """Get Redis stream lengths for pipeline health display."""
    try:
        redis_client = await get_redis()

        streams = {
            FieldName.MARKET_EVENTS: STREAM_MARKET_EVENTS,
            FieldName.SIGNALS: STREAM_SIGNALS,
            FieldName.DECISIONS: STREAM_DECISIONS,
            FieldName.GRADED_DECISIONS: STREAM_GRADED_DECISIONS,
        }

        result = {}
        for key, stream_name in streams.items():
            try:
                result[key] = await redis_client.xlen(stream_name)
            except Exception:
                result[key] = 0

        # agent_logs count from DB (skip if DB unavailable)
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    row = await session.execute(text("SELECT COUNT(*) FROM agent_logs"))
                    result[FieldName.AGENT_LOGS] = row.scalar() or 0
            except Exception:
                result[FieldName.AGENT_LOGS] = 0
        else:
            result[FieldName.AGENT_LOGS] = len(get_runtime_store().event_history)

        # trade_alerts count from events table (skip if DB unavailable)
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    row = await session.execute(
                        text("SELECT COUNT(*) FROM events WHERE event_type = 'trade.alert'")
                    )
                    result[FieldName.TRADE_ALERTS] = row.scalar() or 0
            except Exception:
                result[FieldName.TRADE_ALERTS] = 0
        else:
            result[FieldName.TRADE_ALERTS] = 0

        return {
            **result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "system_metrics_unavailable", exc_info=True)
        return {
            FieldName.MARKET_EVENTS: 0,
            FieldName.SIGNALS: 0,
            FieldName.DECISIONS: 0,
            FieldName.GRADED_DECISIONS: 0,
            FieldName.AGENT_LOGS: 0,
            FieldName.TRADE_ALERTS: 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_prices_payload() -> dict[str, Any]:
    """
    Get current market prices from Redis cache.

    This provides instant price data for dashboard initial load,
    without requiring WebSocket connection.
    """
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
        redis_client = await get_redis()

        # Get all price keys from Redis
        keys = [REDIS_KEY_PRICES.format(symbol=symbol) for symbol in symbols]
        cached_values = await redis_client.mget(keys)

        present: dict[str, Any] = {}
        for symbol, cached_value in zip(symbols, cached_values, strict=False):
            if cached_value:
                try:
                    present[symbol] = json.loads(cached_value)
                except json.JSONDecodeError:
                    log_structured("warning", "invalid price json", symbol=symbol)

        # Drop prices too stale to be a live quote, then pad missing/stale
        # symbols back to None so the payload keeps its fixed shape — the
        # dashboard renders "--" for them instead of a frozen dead price.
        fresh = filter_fresh_prices(present)
        prices: dict[str, Any] = {symbol: fresh.get(symbol) for symbol in symbols}

        return {
            FieldName.PRICES: prices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "redis_cache",
        }

    except Exception:
        log_structured("warning", "price_cache_redis_unavailable", exc_info=True)
        return {
            FieldName.PRICES: dict.fromkeys(
                ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_price_history_payload(limit: int = 1000) -> dict[str, Any]:
    """Recent REAL price series per symbol, reconstructed from the market_events
    stream — the same polled prices the agents act on.

    The poller appends one event per symbol per cycle, so scanning the stream
    yields a real intraday series for each symbol with no extra market-data call.
    Used by the trading-terminal chart + sparklines so they show real movement
    immediately instead of waiting for live samples to trickle in.
    """
    try:
        redis_client = await get_redis()
        entries = await redis_client.xrevrange(STREAM_MARKET_EVENTS, count=limit)
        histories: dict[str, list[dict[str, float]]] = {}
        for _entry_id, fields in entries:
            raw = fields.get(FieldName.PAYLOAD)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            symbol = payload.get(FieldName.SYMBOL)
            price = payload.get(FieldName.PRICE)
            ts = payload.get(FieldName.TS)
            if symbol is None or price is None:
                continue
            histories.setdefault(symbol, []).append(
                {FieldName.TS: ts, FieldName.PRICE: float(price)}
            )
        # xrevrange is newest-first; reverse each series to chronological order.
        for series in histories.values():
            series.reverse()
        return {
            FieldName.HISTORY: histories,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "market_events",
        }
    except Exception:
        log_structured("warning", "price_history_unavailable", exc_info=True)
        return {
            FieldName.HISTORY: {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_worker_health_payload(process_start_time: datetime) -> dict[str, Any]:
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
    uptime_seconds = (now - process_start_time).total_seconds()
    if uptime_seconds < 60:
        return {
            "status": "starting",
            "message": "Worker is warming up",
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
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
                FieldName.CHECK_TIME: now.isoformat(),
            }
        except Exception as e:
            log_structured("warning", "redis connection failed during health check", exc_info=True)
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                FieldName.CHECK_TIME: now.isoformat(),
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
                FieldName.CHECK_TIME: now.isoformat(),
            }
        except Exception as e:
            log_structured("warning", "redis read failed during health check", exc_info=True)
            return {
                "status": "degraded",
                "message": "Redis unavailable or slow",
                "error": str(e),
                FieldName.CHECK_TIME: now.isoformat(),
            }

        # Extract heartbeat (last item)
        heartbeat_value = cached_values[-1]
        price_values = cached_values[:-1]

        timestamps = []
        stale_symbols = []

        # Check price freshness. The poll cache stamps the tick epoch under
        # ``ts`` (FieldName.TS) — NOT ``timestamp`` — so reading TIMESTAMP here
        # silently found nothing and every price slipped through as "fresh".
        # Read ``ts`` and compare against PRICE_STALE_SECONDS (the same bound the
        # served payloads use) so this health view agrees with what's shown.
        for symbol, cached_value in zip(symbols, price_values, strict=False):
            if cached_value:
                try:
                    price_data = json.loads(cached_value)
                    ts_epoch = price_data.get(FieldName.TS)
                    if ts_epoch is not None:
                        timestamp = datetime.fromtimestamp(float(ts_epoch), tz=timezone.utc)
                        timestamps.append(timestamp)
                        if (now - timestamp).total_seconds() > PRICE_STALE_SECONDS:
                            stale_symbols.append(symbol)
                    else:
                        stale_symbols.append(symbol)
                except (json.JSONDecodeError, ValueError, TypeError):
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
                FieldName.LAST_UPDATE: None,
                FieldName.HEARTBEAT_STATUS: heartbeat_status,
                FieldName.HEARTBEAT_AGE: int(heartbeat_age) if heartbeat_age else None,
                FieldName.STALE_SYMBOLS: symbols,
                FieldName.TOTAL_SYMBOLS: len(symbols),
                FieldName.FRESH_SYMBOLS: 0,
                FieldName.UPTIME_SECONDS: uptime_seconds,
                FieldName.CHECK_TIME: now.isoformat(),
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
            FieldName.LAST_UPDATE: last_update.isoformat(),
            FieldName.AGE_SECONDS: int(age_seconds),
            FieldName.HEARTBEAT_STATUS: heartbeat_status,
            FieldName.HEARTBEAT_AGE: int(heartbeat_age) if heartbeat_age else None,
            FieldName.STALE_SYMBOLS: stale_symbols if stale_symbols else None,
            FieldName.TOTAL_SYMBOLS: len(symbols),
            FieldName.FRESH_SYMBOLS: len(symbols) - len(stale_symbols),
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
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
            FieldName.UPTIME_SECONDS: uptime_seconds,
            FieldName.CHECK_TIME: now.isoformat(),
        }
        raise HTTPException(status_code=503, detail=error_data) from None
