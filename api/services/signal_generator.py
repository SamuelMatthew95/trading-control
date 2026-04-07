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

from api.constants import AGENT_SIGNAL, REDIS_AGENT_STATUS_KEY
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION

AGENT_NAME = AGENT_SIGNAL  # single source of truth from constants


class SignalGenerator(BaseStreamConsumer):
    def __init__(self, bus: EventBus, dlq: DLQManager):
        super().__init__(
            bus,
            dlq,
            stream="market_events",
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

        # Dedup check
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

        # Create agent_runs row
        run_id = str(uuid.uuid4())
        agent_pool_id = await self._ensure_agent_pool_id()
        start_time = time.perf_counter()

        async with AsyncSessionFactory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO agent_runs
                            (id, agent_id, trace_id, run_type, trigger_event,
                             input_data, schema_version, source, status,
                             created_at, updated_at)
                        VALUES
                            (:id, :agent_id, :trace_id, 'analysis', :trigger,
                             :input_data, :schema_version, :source, 'running',
                             NOW(), NOW())
                    """),
                    {
                        "id": run_id,
                        "agent_id": agent_pool_id or None,
                        "trace_id": trace_id,
                        "trigger": msg_id,
                        "input_data": json.dumps(payload),
                        "schema_version": DB_SCHEMA_VERSION,
                        "source": AGENT_NAME,
                    },
                )

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
            await self.bus.publish("signals", signal_payload)

            # Write to events table
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO events
                                (event_type, entity_type, data,
                                 idempotency_key, source, schema_version)
                            VALUES
                                ('signal.generated', 'signal', :data,
                                 :idem_key, :source, :schema_version)
                            ON CONFLICT (idempotency_key) DO NOTHING
                        """),
                        {
                            "data": json.dumps(signal_payload),
                            "idem_key": f"signal-{symbol}-{trace_id}",
                            "source": AGENT_NAME,
                            "schema_version": DB_SCHEMA_VERSION,
                        },
                    )

                    # Write to agent_grades
                    await session.execute(
                        text("""
                            INSERT INTO agent_grades
                                (agent_id, agent_run_id, grade_type, score, metrics,
                                 trace_id, schema_version, source)
                            VALUES
                                (:agent_id, :agent_run_id, 'accuracy', :score, CAST(:metrics AS JSONB),
                                 :trace_id, :schema_version, :source)
                        """),
                        {
                            "agent_id": agent_pool_id or None,
                            "agent_run_id": run_id,
                            "score": score,
                            "metrics": json.dumps({"signal_type": signal_type, "symbol": symbol}),
                            "trace_id": trace_id,
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": AGENT_NAME,
                        },
                    )

                    # Mark processed
                    await session.execute(
                        text("""
                            INSERT INTO processed_events (msg_id, stream)
                            VALUES (:msg_id, 'market_events')
                            ON CONFLICT DO NOTHING
                        """),
                        {"msg_id": msg_id},
                    )

            # Update agent_runs — success
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
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
                            "id": run_id,
                        },
                    )

            # Write agent_logs
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO agent_logs
                                (agent_run_id, trace_id, log_type, payload, schema_version, source)
                            VALUES
                                (:agent_run_id, :trace_id, 'signal_generated',
                                 CAST(:payload AS JSONB), :schema_version, :source)
                        """),
                        {
                            "agent_run_id": run_id,
                            "trace_id": trace_id,
                            "payload": json.dumps(signal_payload),
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": AGENT_NAME,
                        },
                    )

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
                ex=60,
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
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE agent_runs SET status='failed',
                                error_message=:err, updated_at=NOW()
                            WHERE id=:id
                        """),
                        {"err": "processing_error", "id": run_id},
                    )
            raise
