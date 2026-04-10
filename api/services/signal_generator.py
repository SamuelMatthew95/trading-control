"""SIGNAL_AGENT — bridges market_events → signals stream.

Reads price ticks from market_events, classifies signal type based on
percentage change, writes classified signals to the signals stream.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import text

from api.constants import (
    AGENT_HEARTBEAT_TTL_SECONDS,
    AGENT_SIGNAL,
    REDIS_AGENT_STATUS_KEY,
    SOURCE_SIGNAL,
    STREAM_MARKET_EVENTS,
    STREAM_SIGNALS,
    GradeType,
    LogType,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import is_db_available, get_runtime_store
from api.schema_version import DB_SCHEMA_VERSION

AGENT_NAME = AGENT_SIGNAL  # single source of truth from constants


class SignalGenerator(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager):
        super().__init__(
            bus,
            dlq,
            stream=STREAM_MARKET_EVENTS,
            group=DEFAULT_GROUP,
            consumer="signal-agent",
        )
        self.total_events = 0
        self.agent_pool_id: str | None = None

    async def _ensure_agent_pool_id(self) -> str:
        if self.agent_pool_id:
            return self.agent_pool_id
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                text("SELECT id FROM agent_pool WHERE name = :name"),
                {"name": AGENT_NAME},
            )
            row = result.first()
            if row:
                self.agent_pool_id = str(row[0])
        return self.agent_pool_id or ""

    async def process(self, data: dict[str, Any]) -> None:
        # Parse payload — market_events has a "payload" JSON field
        raw_payload = data.get("payload")
        if isinstance(raw_payload, str):
            payload = json.loads(raw_payload)
        elif isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            payload = data

        symbol = payload.get("symbol")
        price = float(payload.get("price", 0))
        pct = float(payload.get("pct", 0))
        trace_id = payload.get("trace_id") or str(uuid.uuid4())
        msg_id = data.get("msg_id") or str(uuid.uuid4())

        if not symbol or price <= 0:
            return

        # Dedup check with retry and in-memory fallback
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Skip database entirely if in memory mode (deliberate design choice)
                if not is_db_available():
                    log_structured(
                        "info",
                        f"[{AGENT_NAME}] memory_mode_active",
                        message=f"Signal generator running in deliberate in-memory mode: msg_id={msg_id}",
                    )
                    break
                
                async with AsyncSessionFactory() as session:
                    exists = await session.execute(
                        text("SELECT 1 FROM processed_events WHERE msg_id = :msg_id"),
                        {"msg_id": msg_id},
                    )
                    if exists.first():
                        log_structured(
                            "warning",
                            f"[{AGENT_NAME}] duplicate skipped: msg_id={msg_id}",
                        )
                        return
                break  # Success, exit retry loop
            except Exception as e:
                if attempt == max_retries - 1:
                    log_structured(
                        "error",
                        f"[{AGENT_NAME}] dedup check failed: msg_id={msg_id}",
                        attempt=attempt + 1,
                        exc_info=True,
                    )
                    # In memory mode, continue without dedup
                    if not is_db_available():
                        log_structured(
                            "info",
                            f"[{AGENT_NAME}] continuing without dedup in memory mode: msg_id={msg_id}",
                        )
                        break
                    return  # Skip processing if dedup fails in db mode
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Brief delay before retry

        # Create agent_runs row — id is a legacy integer sequence, so let DB generate it.
        # run_id (UUID) is used as a correlation key in downstream tables only.
        run_id = str(uuid.uuid4())
        db_run_id: int | None = None
        agent_pool_id = await self._ensure_agent_pool_id()
        start_time = time.perf_counter()

        # Create agent_runs row with retry and in-memory fallback
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Skip database entirely if in memory mode (deliberate design choice)
                if not is_db_available():
                    log_structured(
                        "info",
                        f"[{AGENT_NAME}] memory_mode_active",
                        message=f"Signal generator using deliberate in-memory mode: trace_id={trace_id}",
                    )
                    # Store in memory store (primary storage)
                    store = get_runtime_store()
                    store.add_agent_run({
                        "trace_id": trace_id,
                        "input_data": payload,
                        "schema_version": DB_SCHEMA_VERSION,
                        "source": SOURCE_SIGNAL,
                        "status": "running",
                        "created_at": time.time(),
                    })
                    db_run_id = None  # No DB ID in memory mode
                    break
                
                async with AsyncSessionFactory() as session:
                    async with session.begin():
                        result = await session.execute(
                            text("""
                                INSERT INTO agent_runs
                                    (strategy_id, trace_id, input_data,
                                     schema_version, source, status,
                                     created_at, updated_at)
                                VALUES
                                    (:strategy_id, :trace_id, :input_data,
                                     :schema_version, :source, 'running',
                                     NOW(), NOW())
                                RETURNING id
                            """),
                            {
                                "strategy_id": agent_pool_id or None,
                                "trace_id": trace_id,
                                "input_data": json.dumps(payload),
                                "schema_version": DB_SCHEMA_VERSION,
                                "source": SOURCE_SIGNAL,
                            },
                        )
                        row = result.first()
                        db_run_id = row[0] if row else None
                break  # Success, exit retry loop
            except Exception as e:
                if attempt == max_retries - 1:
                    log_structured(
                        "error",
                        f"[{AGENT_NAME}] agent_runs insert failed: trace_id={trace_id}",
                        attempt=attempt + 1,
                        exc_info=True,
                    )
                    # Fallback to memory store
                    if not is_db_available():
                        store = get_runtime_store()
                        store.add_agent_run({
                            "trace_id": trace_id,
                            "input_data": payload,
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": SOURCE_SIGNAL,
                            "status": "running",
                            "created_at": time.time(),
                        })
                        db_run_id = None
                        break
                    return  # Skip processing if agent_runs insert fails in db mode
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Brief delay before retry

        try:
            # Signal classification logic
            abs_pct = abs(pct)
            direction = "bullish" if pct > 0 else ("bearish" if pct < 0 else "neutral")

            if abs_pct >= 3.0:
                signal_type = "STRONG_MOMENTUM"
                strength = "HIGH"
                score = 80.0
            elif abs_pct >= 1.5:
                signal_type = "MOMENTUM"
                strength = "NORMAL"
                score = 55.0
            else:
                signal_type = "PRICE_UPDATE"
                strength = "LOW"
                score = 30.0

            ts = int(time.time())

            # Write to signals stream
            signal_payload = {
                "type": signal_type,
                "symbol": symbol,
                "price": price,
                "pct": pct,
                "direction": direction,
                "strength": strength,
                "trace_id": trace_id,
                "ts": ts,
                "source": AGENT_NAME,
                "msg_id": str(uuid.uuid4()),
            }
            await self.bus.publish(STREAM_SIGNALS, signal_payload)

            # Write to events table with in-memory fallback
            try:
                if not is_db_available():
                    # Store in memory store
                    store = get_runtime_store()
                    store.add_event({
                        "event_type": "signal.generated",
                        "entity_type": "signal",
                        "entity_id": trace_id,
                        "data": signal_payload,
                        "idempotency_key": f"signal-{symbol}-{trace_id}",
                        "schema_version": DB_SCHEMA_VERSION,
                        "source": SOURCE_SIGNAL,
                    })
                    # Store grade in memory
                    store.add_grade({
                        "trace_id": trace_id,
                        "grade_type": "ACCURACY",
                        "score": score,
                        "metrics": {"signal_type": signal_type, "symbol": symbol},
                        "source": SOURCE_SIGNAL,
                        "schema_version": DB_SCHEMA_VERSION,
                    })
                else:
                    async with AsyncSessionFactory() as session:
                        async with session.begin():
                            await session.execute(
                                text("""
                                    INSERT INTO events
                                        (event_type, entity_type, entity_id, data,
                                         idempotency_key, schema_version, source)
                                    VALUES
                                        ('signal.generated', 'signal', :entity_id, :data,
                                         :idem_key, :schema_version, :source)
                                    ON CONFLICT (idempotency_key) DO NOTHING
                                """),
                                {
                                    "entity_id": trace_id,
                                    "data": json.dumps(signal_payload),
                                    "idem_key": f"signal-{symbol}-{trace_id}",
                                    "schema_version": DB_SCHEMA_VERSION,
                                    "source": SOURCE_SIGNAL,
                                },
                            )

                            # Write to agent_grades
                            await session.execute(
                                text("""
                                    INSERT INTO agent_grades
                                        (agent_id, agent_run_id, grade_type, score, metrics,
                                         source, trace_id, schema_version)
                                    VALUES
                                        (:strategy_id, :agent_run_id, :grade_type, :score, CAST(:metrics AS JSONB),
                                         :source, :trace_id, :schema_version)
                                """),
                                {
                                    "strategy_id": agent_pool_id or None,
                                    "agent_run_id": run_id,
                                    "grade_type": GradeType.ACCURACY,
                                    "score": score,
                                    "metrics": json.dumps({"signal_type": signal_type, "symbol": symbol}),
                                    "source": SOURCE_SIGNAL,
                                    "trace_id": trace_id,
                                    "schema_version": DB_SCHEMA_VERSION,
                                },
                            )

                            # Mark processed
                            await session.execute(
                                text("""
                                    INSERT INTO processed_events (msg_id, stream)
                                    VALUES (:msg_id, :stream)
                                    ON CONFLICT DO NOTHING
                                """),
                                {"msg_id": msg_id, "stream": STREAM_MARKET_EVENTS},
                            )
            except Exception as e:
                if not is_db_available():
                    log_structured(
                        "info",
                        f"[{AGENT_NAME}] event storage skipped in memory mode: trace_id={trace_id}",
                    )
                else:
                    raise

            # Update agent_runs — success with in-memory fallback
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            try:
                if db_run_id is not None:
                    if not is_db_available():
                        # Update memory store
                        store = get_runtime_store()
                        # Find the agent run and update it
                        for i, run in enumerate(store.agent_runs):
                            if run.get("trace_id") == trace_id:
                                store.agent_runs[i].update({
                                    "status": "completed",
                                    "output_data": signal_payload,
                                    "execution_time_ms": elapsed_ms,
                                    "updated_at": time.time(),
                                })
                                break
                    else:
                        async with AsyncSessionFactory() as session:
                            async with session.begin():
                                await session.execute(
                                    text("""
                                        UPDATE agent_runs SET status='completed',
                                            output_data=:output, execution_time_ms=:elapsed,
                                            updated_at=NOW()
                                        WHERE id=:id
                                    """),
                                    {
                                        "output": json.dumps(signal_payload),
                                        "elapsed": elapsed_ms,
                                        "id": db_run_id,
                                    },
                                )

                # Write agent_logs with in-memory fallback
                if not is_db_available():
                    store = get_runtime_store()
                    store.add_event({
                        "agent_run_id": run_id,
                        "trace_id": trace_id,
                        "log_type": "SIGNAL_GENERATED",
                        "payload": signal_payload,
                        "schema_version": DB_SCHEMA_VERSION,
                        "source": AGENT_NAME,
                        "timestamp": time.time(),
                    })
                else:
                    async with AsyncSessionFactory() as session:
                        async with session.begin():
                            await session.execute(
                                text("""
                                    INSERT INTO agent_logs
                                        (agent_run_id, trace_id, log_type, payload, schema_version, source)
                                    VALUES
                                        (:agent_run_id, :trace_id, :log_type,
                                         CAST(:payload AS JSONB), :schema_version, :source)
                                """),
                                {
                                    "agent_run_id": run_id,
                                    "trace_id": trace_id,
                                    "log_type": LogType.SIGNAL_GENERATED,
                                    "payload": json.dumps(signal_payload),
                                    "schema_version": DB_SCHEMA_VERSION,
                                    "source": AGENT_NAME,
                                },
                            )
            except Exception as e:
                if not is_db_available():
                    log_structured(
                        "info",
                        f"[{AGENT_NAME}] agent update skipped in memory mode: trace_id={trace_id}",
                    )
                else:
                    raise

            self.total_events += 1

            # Redis heartbeat
            redis = self.bus.redis
            await redis.set(
                REDIS_AGENT_STATUS_KEY.format(name=AGENT_NAME),
                json.dumps(
                    {
                        "status": "ACTIVE",
                        "last_event": f"{signal_type} {symbol} {pct:+.2f}%",
                        "event_count": self.total_events,
                        "last_seen": int(time.time()),
                    }
                ),
                ex=AGENT_HEARTBEAT_TTL_SECONDS,
            )

            # Postgres heartbeat
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO agent_heartbeats
                                (agent_name, status, last_event,
                                 event_count, last_seen)
                            VALUES (:name, 'ACTIVE', :last_event,
                                    :count, NOW())
                            ON CONFLICT (agent_name) DO UPDATE SET
                                status='ACTIVE',
                                last_event=EXCLUDED.last_event,
                                event_count=EXCLUDED.event_count,
                                last_seen=NOW()
                        """),
                        {
                            "name": AGENT_NAME,
                            "last_event": f"{signal_type} {symbol} {pct:+.2f}%",
                            "count": self.total_events,
                        },
                    )

            log_structured(
                "info",
                f"[{AGENT_NAME}] signal: type={signal_type} symbol={symbol} "
                f"price={price} pct={pct:+.2f}% direction={direction} "
                f"trace_id={trace_id}",
            )

        except Exception:
            log_structured("error", "signal agent processing failed", exc_info=True)
            # Update agent_runs — failure
            if db_run_id is not None:
                async with AsyncSessionFactory() as session:
                    async with session.begin():
                        await session.execute(
                            text("""
                                UPDATE agent_runs SET status='failed',
                                    error_message=:err, updated_at=NOW()
                                WHERE id=:id
                            """),
                            {"err": "processing_error", "id": db_run_id},
                        )
            raise
