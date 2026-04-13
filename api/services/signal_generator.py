"""SIGNAL_AGENT — bridges market_events → signals stream.

Reads price ticks from market_events, classifies signal type based on
percentage change, and writes classified signals to the signals stream.

DB routing:
  - is_db_available() is set once at startup.
  - Every code path checks it upfront and routes deterministically.
  - No "try DB, catch, fall back" — the mode is known and explicit.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import text

from api.constants import (
    AGENT_SIGNAL,
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
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat

AGENT_NAME = AGENT_SIGNAL


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
        self._agent_pool_id: str | None = None

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def _resolve_agent_pool_id(self) -> str | None:
        """Fetch agent_pool UUID once and cache it. Returns None in memory mode."""
        if self._agent_pool_id is not None:
            return self._agent_pool_id
        if not is_db_available():
            return None
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("SELECT id FROM agent_pool WHERE name = :name"),
                    {"name": AGENT_NAME},
                )
                row = result.first()
                if row:
                    self._agent_pool_id = str(row[0])
        except Exception:
            log_structured("warning", f"[{AGENT_NAME}] agent_pool_lookup_failed", exc_info=True)
        return self._agent_pool_id

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    async def process(self, data: dict[str, Any]) -> None:
        # --- Parse incoming tick -----------------------------------------
        raw = data.get("payload")
        if isinstance(raw, str):
            payload = json.loads(raw)
        elif isinstance(raw, dict):
            payload = raw
        else:
            payload = data

        symbol = payload.get("symbol")
        price = float(payload.get("price", 0))
        pct = float(payload.get("pct", 0))
        trace_id = payload.get("trace_id") or str(uuid.uuid4())
        msg_id = data.get("msg_id") or str(uuid.uuid4())

        if not symbol or price <= 0:
            return

        # --- Classify signal ---------------------------------------------
        abs_pct = abs(pct)
        direction = "bullish" if pct > 0 else ("bearish" if pct < 0 else "neutral")
        if abs_pct >= 3.0:
            signal_type, strength, score = "STRONG_MOMENTUM", "HIGH", 80.0
        elif abs_pct >= 1.5:
            signal_type, strength, score = "MOMENTUM", "NORMAL", 55.0
        else:
            signal_type, strength, score = "PRICE_UPDATE", "LOW", 30.0

        signal_payload: dict[str, Any] = {
            "type": signal_type,
            "symbol": symbol,
            "price": price,
            "pct": pct,
            "direction": direction,
            "strength": strength,
            "trace_id": trace_id,
            "ts": int(time.time()),
            "source": AGENT_NAME,
            "msg_id": str(uuid.uuid4()),
        }

        # --- Begin run (dedup check + run start write) -------------------
        run_id = str(uuid.uuid4())
        agent_pool_id = await self._resolve_agent_pool_id()
        start_time = time.perf_counter()

        should_proceed, db_run_id = await self._begin_run(
            run_id, trace_id, payload, agent_pool_id, msg_id
        )
        if not should_proceed:
            return

        # --- Publish signal to downstream agents -------------------------
        await self.bus.publish(STREAM_SIGNALS, signal_payload)

        # --- Persist signal data and complete the run --------------------
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        self.total_events += 1
        await self._persist_signal_complete(
            run_id, db_run_id, trace_id, signal_payload, agent_pool_id, msg_id, score, elapsed_ms
        )

        # --- Heartbeat ---------------------------------------------------
        await write_heartbeat(
            self.bus.redis,
            AGENT_NAME,
            f"{signal_type} {symbol} {pct:+.2f}%",
            event_count=self.total_events,
        )

        log_structured(
            "info",
            f"[{AGENT_NAME}] signal_published",
            signal_type=signal_type,
            symbol=symbol,
            price=price,
            direction=direction,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Unified persistence — single routing point per operation
    # ------------------------------------------------------------------

    async def _begin_run(
        self,
        run_id: str,
        trace_id: str,
        payload: dict,
        agent_pool_id: str | None,
        msg_id: str,
    ) -> tuple[bool, int | None]:
        """Dedup check (DB only) then write run start. Returns (should_proceed, db_run_id)."""
        if is_db_available():
            if await self._is_duplicate(msg_id):
                return False, None
            db_run_id = await self._db_write_run_start(run_id, trace_id, payload, agent_pool_id)
            return True, db_run_id
        get_runtime_store().add_agent_run(
            {
                "run_id": run_id,
                "trace_id": trace_id,
                "input_data": payload,
                "schema_version": DB_SCHEMA_VERSION,
                "source": SOURCE_SIGNAL,
                "status": "running",
                "created_at": time.time(),
            }
        )
        return True, None

    async def _persist_signal_complete(
        self,
        run_id: str,
        db_run_id: int | None,
        trace_id: str,
        signal_payload: dict,
        agent_pool_id: str | None,
        msg_id: str,
        score: float,
        elapsed_ms: int,
    ) -> None:
        """Persist signal event, grade, and run completion — routes DB vs memory."""
        if is_db_available():
            await self._db_write_signal(
                trace_id, msg_id, signal_payload, score, agent_pool_id, run_id
            )
            await self._db_write_run_complete(
                db_run_id, run_id, trace_id, signal_payload, elapsed_ms
            )
            return
        symbol = signal_payload["symbol"]
        store = get_runtime_store()
        store.add_event(
            {
                "event_type": "signal.generated",
                "entity_type": "signal",
                "entity_id": trace_id,
                "data": signal_payload,
                "idempotency_key": f"signal-{symbol}-{trace_id}",
                "schema_version": DB_SCHEMA_VERSION,
                "source": SOURCE_SIGNAL,
            }
        )
        store.add_grade(
            {
                "trace_id": trace_id,
                "grade_type": "ACCURACY",
                "score": score,
                "metrics": {"signal_type": signal_payload["type"], "symbol": symbol},
                "source": SOURCE_SIGNAL,
                "schema_version": DB_SCHEMA_VERSION,
            }
        )
        for run in store.agent_runs:
            if run.get("run_id") == run_id:
                run.update(
                    {
                        "status": "completed",
                        "output_data": signal_payload,
                        "execution_time_ms": elapsed_ms,
                    }
                )
                break
        store.add_event(
            {
                "agent_run_id": run_id,
                "trace_id": trace_id,
                "log_type": "SIGNAL_GENERATED",
                "payload": signal_payload,
                "schema_version": DB_SCHEMA_VERSION,
                "source": AGENT_NAME,
                "timestamp": time.time(),
            }
        )

    # ------------------------------------------------------------------
    # DB write helpers — only called when is_db_available() is True
    # ------------------------------------------------------------------

    async def _is_duplicate(self, msg_id: str) -> bool:
        """Return True if this msg_id has already been processed (DB mode only)."""
        try:
            async with AsyncSessionFactory() as session:
                row = await session.execute(
                    text("SELECT 1 FROM processed_events WHERE msg_id = :msg_id"),
                    {"msg_id": msg_id},
                )
                if row.first():
                    log_structured("debug", f"[{AGENT_NAME}] duplicate_skipped", msg_id=msg_id)
                    return True
        except Exception:
            # Dedup failure → allow through; duplicates are preferable to missed signals
            log_structured("warning", f"[{AGENT_NAME}] dedup_check_failed", exc_info=True)
        return False

    async def _db_write_run_start(
        self,
        run_id: str,
        trace_id: str,
        payload: dict,
        agent_pool_id: str | None,
    ) -> int | None:
        """INSERT agent_runs row. Returns the integer PK (RETURNING id)."""
        try:
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
                    return row[0] if row else None
        except Exception:
            log_structured(
                "error", f"[{AGENT_NAME}] agent_run_insert_failed", trace_id=trace_id, exc_info=True
            )
            return None

    async def _db_write_signal(
        self,
        trace_id: str,
        msg_id: str,
        signal_payload: dict,
        score: float,
        agent_pool_id: str | None,
        run_id: str,
    ) -> None:
        """Write event, grade, and processed-events marker in one transaction."""
        try:
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
                            "idem_key": f"signal-{signal_payload['symbol']}-{trace_id}",
                            "schema_version": DB_SCHEMA_VERSION,
                            "source": SOURCE_SIGNAL,
                        },
                    )
                    await session.execute(
                        text("""
                            INSERT INTO agent_grades
                                (agent_id, agent_run_id, grade_type, score, metrics,
                                 source, trace_id, schema_version)
                            VALUES
                                (:strategy_id, :agent_run_id, :grade_type, :score,
                                 CAST(:metrics AS JSONB), :source, :trace_id, :schema_version)
                        """),
                        {
                            "strategy_id": agent_pool_id or None,
                            "agent_run_id": run_id,
                            "grade_type": GradeType.ACCURACY,
                            "score": score,
                            "metrics": json.dumps(
                                {
                                    "signal_type": signal_payload["type"],
                                    "symbol": signal_payload["symbol"],
                                }
                            ),
                            "source": SOURCE_SIGNAL,
                            "trace_id": trace_id,
                            "schema_version": DB_SCHEMA_VERSION,
                        },
                    )
                    await session.execute(
                        text("""
                            INSERT INTO processed_events (msg_id, stream)
                            VALUES (:msg_id, :stream)
                            ON CONFLICT DO NOTHING
                        """),
                        {"msg_id": msg_id, "stream": STREAM_MARKET_EVENTS},
                    )
        except Exception:
            log_structured(
                "error", f"[{AGENT_NAME}] signal_db_write_failed", trace_id=trace_id, exc_info=True
            )

    async def _db_write_run_complete(
        self,
        db_run_id: int | None,
        run_id: str,
        trace_id: str,
        signal_payload: dict,
        elapsed_ms: int,
    ) -> None:
        """UPDATE agent_runs status and INSERT agent_log entry."""
        try:
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    if db_run_id is not None:
                        await session.execute(
                            text("""
                                UPDATE agent_runs
                                SET status='completed',
                                    output_data=:output,
                                    execution_time_ms=:elapsed,
                                    updated_at=NOW()
                                WHERE id=:id
                            """),
                            {
                                "output": json.dumps(signal_payload),
                                "elapsed": elapsed_ms,
                                "id": db_run_id,
                            },
                        )
                    await session.execute(
                        text("""
                            INSERT INTO agent_logs
                                (agent_run_id, trace_id, log_type,
                                 payload, schema_version, source)
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
        except Exception:
            log_structured(
                "warning",
                f"[{AGENT_NAME}] run_complete_write_failed",
                trace_id=trace_id,
                exc_info=True,
            )
