"""Shared heartbeat writer for all agents.

Every agent calls write_heartbeat() after processing each event so the
dashboard can show accurate ACTIVE / STALE / offline status.

Write order (all best-effort — a failure in any step never crashes the agent):
  1. In-memory store  — always; guarantees dashboard fallback has live data
  2. Redis            — fast path; dashboard polls this for live status
  3. Postgres         — persistent history; skipped entirely when DB is unavailable
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text

from api.constants import (
    AGENT_HEARTBEAT_TTL_SECONDS,
    REDIS_AGENT_STATUS_KEY,
    AgentStatus,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available


async def write_heartbeat(
    redis: Any,
    agent_name: str,
    last_event: str,
    event_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write agent heartbeat to in-memory store, Redis, and (if available) Postgres.

    Args:
        redis:       An async Redis client instance.
        agent_name:  SCREAMING_SNAKE_CASE agent name constant (e.g. AGENT_SIGNAL).
        last_event:  Human-readable description of the most recent event processed.
        event_count: Running count of events processed (best-effort, can be 0).
        extra:       Optional extra fields to merge into the payload.
    """
    payload: dict[str, Any] = {
        FieldName.STATUS: "ACTIVE",
        "last_event": last_event,
        "event_count": event_count,
        "last_seen": int(time.time()),
    }
    if extra:
        payload.update(extra)

    # 1. In-memory store — always written so dashboard fallback shows live agent status
    get_runtime_store().upsert_agent(agent_name, payload)

    # 2. Redis — fast path for live dashboard polling
    try:
        await redis.set(
            REDIS_AGENT_STATUS_KEY.format(name=agent_name),
            json.dumps(payload),
            ex=AGENT_HEARTBEAT_TTL_SECONDS,
        )
    except Exception:
        log_structured("warning", "heartbeat_redis_failed", agent=agent_name, exc_info=True)

    # 3. Postgres — persistent record; skip entirely when DB is unavailable
    if not is_db_available():
        return

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                # Update heartbeat record
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
                
                # Create or update agent_instances lifecycle record
                # Use a deterministic instance_key based on agent name
                instance_key = f"{agent_name.lower()}_lifecycle"
                
                await session.execute(
                    text("""
                        INSERT INTO agent_instances
                            (instance_key, pool_name, status, started_at, event_count, metadata)
                        VALUES (:instance_key, :pool_name, 'active', NOW(), :count, :metadata)
                        ON CONFLICT (instance_key) DO UPDATE SET
                            status      = 'active',
                            event_count = EXCLUDED.event_count + :count,
                            retired_at  = NULL
                    """),
                    {
                        "instance_key": instance_key,
                        "pool_name": agent_name,
                        "count": event_count,
                        "metadata": json.dumps({"source": "heartbeat", "last_event": last_event})
                    },
                )
    except Exception:
        log_structured("warning", "heartbeat_db_failed", agent=agent_name, exc_info=True)
