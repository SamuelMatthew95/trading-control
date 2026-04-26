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
from api.schema_version import DB_SCHEMA_VERSION


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
        FieldName.SOURCE: "heartbeat",
        "last_event": last_event,
        "event_count": event_count,
        "last_seen": int(time.time()),
        "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        FieldName.UPDATED_AT: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "heartbeat_count": max(int(event_count), 1),
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
                await session.execute(
                    text("""
                        UPDATE agent_instances
                        SET
                            status = 'active',
                            event_count = GREATEST(event_count, :event_count),
                            metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:metadata AS JSONB)
                        WHERE instance_key = :instance_key
                    """),
                    {
                        "instance_key": agent_name.lower().replace("_", "-"),
                        "pool_name": agent_name,
                        "event_count": event_count,
                        "metadata": json.dumps(
                            {
                                "last_seen_at": payload["last_seen_at"],
                                FieldName.UPDATED_AT: payload[FieldName.UPDATED_AT],
                                "heartbeat_count": payload["heartbeat_count"],
                                FieldName.SOURCE: payload[FieldName.SOURCE],
                            }
                        ),
                    },
                )
                # Heartbeats can arrive before (or instead of) explicit startup
                # registration in degraded environments. If no instance row exists,
                # create one so dashboard lifecycle views stay consistent.
                await session.execute(
                    text("""
                        INSERT INTO agent_instances
                            (id, instance_key, pool_name, status, started_at, event_count, schema_version, metadata)
                        SELECT
                            gen_random_uuid(),
                            :instance_key,
                            :pool_name,
                            'active',
                            NOW(),
                            :event_count,
                            :schema_version,
                            CAST(:metadata AS JSONB)
                        WHERE NOT EXISTS (
                            SELECT 1 FROM agent_instances WHERE instance_key = :instance_key
                        )
                    """),
                    {
                        "instance_key": agent_name.lower().replace("_", "-"),
                        "pool_name": agent_name,
                        "event_count": event_count,
                        "schema_version": DB_SCHEMA_VERSION,
                        "metadata": json.dumps(
                            {
                                "agent_name": agent_name,
                                "last_seen_at": payload["last_seen_at"],
                                FieldName.UPDATED_AT: payload[FieldName.UPDATED_AT],
                                "heartbeat_count": payload["heartbeat_count"],
                                FieldName.SOURCE: "heartbeat_upsert",
                            }
                        ),
                    },
                )
    except Exception:
        log_structured("warning", "heartbeat_db_failed", agent=agent_name, exc_info=True)
