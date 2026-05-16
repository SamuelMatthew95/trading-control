import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.constants import (
    AGENT_EXECUTION,
    AGENT_STALE_THRESHOLD_SECONDS,
    ALL_AGENT_NAMES,
    REDIS_AGENT_STATUS_KEY,
    STREAM_DECISIONS,
    STREAM_SIGNALS,
    FieldName,
)
from api.database import AsyncSessionFactory
from api.observability import log_structured
from api.redis_client import get_redis
from api.runtime_state import get_runtime_store, is_db_available
from api.services.metrics_aggregator import MetricsAggregator


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


def _agent_memory_payload() -> dict[str, Any]:
    store = get_runtime_store()
    return {
        FieldName.AGENTS: [
            {
                FieldName.NAME: name,
                **({} if not store.get_agent(name) else store.get_agent(name)),
            }
            for name in ALL_AGENT_NAMES
        ],
        FieldName.RUNS: store.agent_runs[-50:],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "in_memory",
    }


def _in_memory_agent_instances_payload() -> dict[str, Any]:
    """Build agent instance rows from in-memory heartbeat state without touching Postgres."""
    store = get_runtime_store()
    now = datetime.now(timezone.utc)
    instances: list[dict[str, Any]] = []

    for name in ALL_AGENT_NAMES:
        data = store.get_agent(name) or {}
        status_raw = str(data.get(FieldName.STATUS) or "").strip().lower()
        if status_raw not in {"active", "running", "live"}:
            continue

        started_at = _timestamp_from_agent_data(data, now)
        last_seen = data.get(FieldName.LAST_SEEN)
        try:
            uptime_seconds = max(0, int(now.timestamp()) - int(float(last_seen)))
        except (TypeError, ValueError):
            uptime_seconds = 0

        instances.append(
            {
                FieldName.ID: str(data.get(FieldName.AGENT_ID) or f"memory:{name}"),
                FieldName.INSTANCE_KEY: str(
                    data.get(FieldName.INSTANCE_KEY) or name.lower().replace("_", "-")
                ),
                FieldName.POOL_NAME: str(data.get(FieldName.POOL_NAME) or name),
                "status": "active",
                FieldName.STARTED_AT: started_at,
                FieldName.RETIRED_AT: None,
                "event_count": int(data.get(FieldName.EVENT_COUNT) or 0),
                FieldName.UPTIME_SECONDS: uptime_seconds,
            }
        )

    return {
        FieldName.INSTANCES: instances,
        FieldName.ACTIVE_COUNT: len(instances),
        FieldName.RETIRED_COUNT: 0,
        "timestamp": now.isoformat(),
        "source": "in_memory",
    }


async def get_agent_metrics_payload() -> dict[str, Any]:
    """Get agent activity metrics."""
    if not is_db_available():
        return _agent_memory_payload()
    try:
        async with AsyncSessionFactory() as session:
            aggregator = MetricsAggregator(session)
            return await aggregator.get_agent_metrics()
    except Exception:
        log_structured("warning", "agent_metrics_db_failed", exc_info=True)
        return _agent_memory_payload()


async def get_agents_status_payload() -> dict[str, Any]:
    """Get agent status from Redis heartbeats, with in-memory fallback."""
    try:
        redis_client = await get_redis()
        now = int(datetime.now(timezone.utc).timestamp())
        heartbeat_map: dict[str, dict[str, Any]] = {}
        for name in ALL_AGENT_NAMES:
            raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=name))
            if raw:
                data = json.loads(raw)
                last_seen = data.get(FieldName.LAST_SEEN, 0)
                age = now - last_seen
                if age > AGENT_STALE_THRESHOLD_SECONDS:
                    status = "STALE"
                else:
                    status = data.get(FieldName.STATUS, "ACTIVE")
                heartbeat_map[name] = {
                    FieldName.NAME: name,
                    "status": status,
                    "event_count": data.get(FieldName.EVENT_COUNT, 0),
                    "last_event": data.get(FieldName.LAST_EVENT, ""),
                    "last_seen": last_seen,
                    "last_seen_at": datetime.fromtimestamp(last_seen, tz=timezone.utc).isoformat()
                    if last_seen
                    else None,
                    FieldName.SECONDS_AGO: age,
                }
            else:
                heartbeat_map[name] = {
                    FieldName.NAME: name,
                    "status": "WAITING",
                    "event_count": 0,
                    "last_event": "",
                    "last_seen": 0,
                    "last_seen_at": None,
                    FieldName.SECONDS_AGO: 0,
                }

        agents = list(heartbeat_map.values())
        if is_db_available():
            async with AsyncSessionFactory() as session:
                res = await session.execute(
                    text("""
                        SELECT instance_key, status, started_at, retired_at, event_count, metadata
                        FROM agent_instances
                        WHERE status IN ('active', 'retired')
                    """)
                )
                for row in res.all():
                    key = str(row[0] or "").upper().replace("-", "_")
                    existing = heartbeat_map.get(key)
                    if existing is None:
                        continue
                    meta = row[5] if isinstance(row[5], dict) else {}
                    existing[FieldName.INSTANCE_STATUS] = row[1]
                    existing[FieldName.STARTED_AT] = row[2].isoformat() if row[2] else None
                    existing[FieldName.RETIRED_AT] = row[3].isoformat() if row[3] else None
                    existing[FieldName.EVENT_COUNT] = max(
                        int(existing[FieldName.EVENT_COUNT]), int(row[4] or 0)
                    )
                    existing[FieldName.HEARTBEAT_COUNT] = int(
                        meta.get(FieldName.HEARTBEAT_COUNT) or 0
                    )
                    if existing[FieldName.STATUS] == "ACTIVE" and not existing.get(
                        FieldName.LAST_SEEN_AT
                    ):
                        existing[FieldName.STATUS] = "STALE"
                        existing[FieldName.LAST_EVENT] = "missing_last_seen_at"

        # Pipeline health summary: signal / decision stream lengths + EE last status
        pipeline_health: dict[str, Any] = {}
        try:
            pipeline_health[FieldName.SIGNAL_STREAM_LENGTH] = await redis_client.xlen(
                STREAM_SIGNALS
            )
            pipeline_health[FieldName.DECISION_STREAM_LENGTH] = await redis_client.xlen(
                STREAM_DECISIONS
            )
            _ee_raw = await redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=AGENT_EXECUTION))
            if _ee_raw:
                _ee = json.loads(_ee_raw)
                pipeline_health[FieldName.EE_LAST_STATUS] = _ee.get(FieldName.LAST_EVENT, "")
                pipeline_health[FieldName.EE_DECISIONS_EVALUATED] = int(
                    _ee.get(FieldName.EVENT_COUNT, 0)
                )
        except Exception:
            pass

        return {
            FieldName.AGENTS: agents,
            FieldName.PIPELINE_HEALTH: pipeline_health,
            FieldName.DEGRADED_MODE: not is_db_available(),
            **({FieldName.DEGRADED_REASON: "db_unavailable"} if not is_db_available() else {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("warning", "agents_status_redis_unavailable_using_memory", exc_info=True)
        store = get_runtime_store()
        now = int(datetime.now(timezone.utc).timestamp())
        agents = [
            {
                FieldName.NAME: name,
                "status": (store.get_agent(name) or {}).get(FieldName.STATUS, "WAITING"),
                "event_count": (store.get_agent(name) or {}).get(FieldName.EVENT_COUNT, 0),
                "last_event": (store.get_agent(name) or {}).get(FieldName.LAST_EVENT, ""),
                "last_seen": (store.get_agent(name) or {}).get(FieldName.LAST_SEEN, 0),
                FieldName.SECONDS_AGO: now
                - (store.get_agent(name) or {}).get(FieldName.LAST_SEEN, now),
            }
            for name in ALL_AGENT_NAMES
        ]
        return {
            FieldName.AGENTS: agents,
            FieldName.DEGRADED_MODE: True,
            FieldName.DEGRADED_REASON: "redis_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "in_memory",
        }


async def get_agent_instances_payload() -> dict[str, Any]:
    """Return all agent instances with lifecycle info.

    Active instances show how long they have been running and how many events
    they have processed.  Retired instances are kept for audit.
    """
    if not is_db_available():
        return _in_memory_agent_instances_payload()

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
                FieldName.ID: str(r[0]),
                FieldName.INSTANCE_KEY: r[1],
                FieldName.POOL_NAME: r[2],
                "status": r[3],
                FieldName.STARTED_AT: r[4].isoformat() if r[4] else None,
                FieldName.RETIRED_AT: r[5].isoformat() if r[5] else None,
                "event_count": int(r[6]) if r[6] is not None else 0,
                FieldName.UPTIME_SECONDS: int(r[8]) if r[8] is not None else 0,
            }
            for r in rows
        ]

        active = [i for i in instances if i[FieldName.STATUS] == "active"]
        retired = [i for i in instances if i[FieldName.STATUS] == "retired"]

        return {
            FieldName.INSTANCES: instances,
            FieldName.ACTIVE_COUNT: len(active),
            FieldName.RETIRED_COUNT: len(retired),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        log_structured("error", "agent_instances_failed", exc_info=True)
        return {
            FieldName.INSTANCES: [],
            FieldName.ACTIVE_COUNT: 0,
            FieldName.RETIRED_COUNT: 0,
            "error": "agent_instances_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
