"""
API v1 endpoints for prices and agent status.

Provides REST endpoints and Server-Sent Events for real-time data.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["api-v1"])

# Symbols to track
SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]

# Agent names to track
AGENT_NAMES = [
    "SIGNAL_AGENT",
    "REASONING_AGENT", 
    "GRADE_AGENT",
    "IC_UPDATER",
    "REFLECTION_AGENT",
    "STRATEGY_PROPOSER",
    "NOTIFICATION_AGENT"
]


@router.get("/prices")
async def get_prices() -> Dict[str, Dict[str, Any]]:
    """
    Get current market prices for all symbols.
    
    Reads from Redis cache first, falls back to Postgres if cache miss.
    """
    try:
        redis_client = await get_redis()
        
        # Try to get all prices from Redis cache
        cache_keys = [f"prices:{symbol}" for symbol in SYMBOLS]
        cached_values = await redis_client.mget(cache_keys)
        
        result = {}
        missing_symbols = []
        
        for i, symbol in enumerate(SYMBOLS):
            cached_value = cached_values[i]
            if cached_value:
                try:
                    result[symbol] = json.loads(cached_value)
                except (json.JSONDecodeError, TypeError):
                    missing_symbols.append(symbol)
            else:
                missing_symbols.append(symbol)
        
        # Fall back to Postgres for missing symbols
        if missing_symbols:
            async with AsyncSessionFactory() as session:
                placeholders = ",".join([f"'{symbol}'" for symbol in missing_symbols])
                query = text(f"""
                    SELECT symbol, price, change_amt, change_pct, 
                           EXTRACT(EPOCH FROM updated_at) as ts
                    FROM prices_snapshot 
                    WHERE symbol IN ({placeholders})
                """)
                
                db_result = await session.execute(query)
                rows = db_result.fetchall()
                
                for row in rows:
                    symbol = row.symbol
                    result[symbol] = {
                        "price": float(row.price),
                        "change": float(row.change_amt or 0),
                        "pct": float(row.change_pct or 0),
                        "ts": int(row.ts) if row.ts else int(time.time())
                    }
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices/stream")
async def stream_prices():
    """
    Server-Sent Events stream for real-time price updates.
    
    Subscribes to Redis pub/sub channel and streams events to browser.
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        redis_client = await get_redis()
        pubsub = redis_client.pubsub()
        
        try:
            await pubsub.subscribe("price_updates")
            logger.info("SSE client subscribed to price_updates")
            
            # Send initial connection message
            yield f"data: {{\"type\": \"connected\", \"timestamp\": {int(time.time())}}}\n\n"
            
            last_heartbeat = time.time()
            
            while True:
                try:
                    # Check for heartbeat
                    current_time = time.time()
                    if current_time - last_heartbeat > 15:
                        yield ": heartbeat\n\n"
                        last_heartbeat = current_time
                    
                    # Check for messages with timeout
                    message = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=1.0)
                    
                    if message and message["type"] == "message":
                        data = message["data"].decode("utf-8")
                        yield f"data: {data}\n\n"
                        
                except asyncio.TimeoutError:
                    # Send periodic heartbeat
                    current_time = time.time()
                    if current_time - last_heartbeat > 15:
                        yield ": heartbeat\n\n"
                        last_heartbeat = current_time
                    continue
                except Exception as e:
                    logger.error(f"Error in SSE stream: {e}")
                    yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
                    break
                    
        except Exception as e:
            logger.error(f"Error setting up SSE stream: {e}")
            yield f"data: {{\"type\": \"error\", \"message\": \"Stream setup failed\"}}\n\n"
        finally:
            await pubsub.unsubscribe("price_updates")
            await pubsub.close()
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@router.get("/agents/status")
async def get_agents_status() -> Dict[str, Dict[str, Any]]:
    """
    Get status of all agents.
    
    Reads from Redis cache first, falls back to Postgres if cache miss.
    """
    try:
        redis_client = await get_redis()
        current_time = int(time.time())
        
        # Try to get all agent statuses from Redis
        cache_keys = [f"agent:status:{agent}" for agent in AGENT_NAMES]
        cached_values = await redis_client.mget(cache_keys)
        
        result = {}
        missing_agents = []
        
        for i, agent in enumerate(AGENT_NAMES):
            cached_value = cached_values[i]
            if cached_value:
                try:
                    status_data = json.loads(cached_value)
                    last_seen = status_data.get("last_seen", 0)
                    
                    # Check if agent is stale
                    if current_time - last_seen > 120:
                        status_data["status"] = "STALE"
                    
                    status_data["seconds_ago"] = current_time - last_seen
                    result[agent] = status_data
                except (json.JSONDecodeError, TypeError):
                    missing_agents.append(agent)
            else:
                missing_agents.append(agent)
                result[agent] = {
                    "status": "OFFLINE",
                    "last_event": "No data available",
                    "event_count": 0,
                    "last_seen": 0,
                    "seconds_ago": 999999
                }
        
        # Fall back to Postgres for missing agents
        if missing_agents:
            async with AsyncSessionFactory() as session:
                placeholders = ",".join([f"'{agent}'" for agent in missing_agents])
                query = text(f"""
                    SELECT agent_name, status, last_event, event_count,
                           EXTRACT(EPOCH FROM last_seen) as last_seen_ts
                    FROM agent_heartbeats 
                    WHERE agent_name IN ({placeholders})
                """)
                
                db_result = await session.execute(query)
                rows = db_result.fetchall()
                
                for row in rows:
                    agent = row.agent_name
                    last_seen_ts = int(row.last_seen_ts) if row.last_seen_ts else 0
                    
                    # Check if agent is stale
                    status = row.status
                    if current_time - last_seen_ts > 120:
                        status = "STALE"
                    
                    result[agent] = {
                        "status": status,
                        "last_event": row.last_event or "No recent events",
                        "event_count": row.event_count or 0,
                        "last_seen": last_seen_ts,
                        "seconds_ago": current_time - last_seen_ts
                    }
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting agent status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
