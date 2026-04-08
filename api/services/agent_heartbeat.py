"""Shared heartbeat writer for all agents.

Every agent must call write_heartbeat() after processing each event so the
dashboard can show accurate ACTIVE / STALE / offline status.

What it does:
  1. Writes agent:status:{AGENT_NAME} to Redis (TTL = AGENT_HEARTBEAT_TTL_SECONDS)
  2. Upserts a row into the agent_heartbeats Postgres table

Both writes are best-effort — a failure in either must never crash the agent.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text

from api.constants import AGENT_HEARTBEAT_TTL_SECONDS, REDIS_AGENT_STATUS_KEY, AgentStatus
from api.database import AsyncSessionFactory
from api.observability import log_structured


async def write_heartbeat(
    redis: Any,
    agent_name: str,
    last_event: str,
    event_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write agent heartbeat to Redis and Postgres.

    Args:
        redis:       An async Redis client instance.
        agent_name:  SCREAMING_SNAKE_CASE agent name constant (e.g. AGENT_SIGNAL).
        last_event:  Human-readable description of the most recent event processed.
        event_count: Running count of events processed (best-effort, can be 0).
        extra:       Optional extra fields to merge into the Redis payload.
    """
    payload: dict[str, Any] = {
        "status": "ACTIVE",
        "last_event": last_event,
        "event_count": event_count,
        "last_seen": int(time.time()),
    }
    if extra:
        payload.update(extra)

    # 1. Redis — fast path; dashboard polls this for live status
    try:
        await redis.set(
            REDIS_AGENT_STATUS_KEY.format(name=agent_name),
            json.dumps(payload),
            ex=AGENT_HEARTBEAT_TTL_SECONDS,
        )
    except Exception:
        log_structured("warning", "heartbeat_redis_failed", agent=agent_name, exc_info=True)

    # 2. Postgres — persistent record; survives Redis flush / restart
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO agent_heartbeats
                            (agent_name, status, last_event, event_count, last_seen)
                        VALUES (:name, :status, :last_event, :count, NOW())
                        ON CONFLICT (agent_name) DO UPDATE SET
                            status       = :status,
                            last_event   = EXCLUDED.last_event,
                            event_count  = EXCLUDED.event_count,
                            last_seen    = NOW()
                    """),
                    {
                        "name": agent_name,
                        "status": AgentStatus.ACTIVE,
                        "last_event": last_event,
                        "count": event_count,
                    },
                )
    except Exception:
        log_structured("warning", "heartbeat_db_failed", agent=agent_name, exc_info=True)
