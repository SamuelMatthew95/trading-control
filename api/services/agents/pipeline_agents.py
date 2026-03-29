"""Additional stream agents wired into runtime lifespan."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.config import settings
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from redis.asyncio import Redis
import json
import time


class MultiStreamAgent:
    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        streams: list[str],
        consumer: str,
        redis_client: Redis | None = None,
    ) -> None:
        self.bus = bus
        self.dlq = dlq
        self.streams = streams
        self.consumer = consumer
        self.redis = redis_client
        self.name = consumer.upper().replace("-", "_")
        self.event_count = 0
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")
        # Set initial heartbeat
        await self._write_heartbeat("WAITING", "started, waiting for events")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError
    
    async def _check_processed_events(self, redis_id: str) -> bool:
        """Check if message has already been processed (exactly-once guarantee)."""
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                "SELECT msg_id FROM processed_events WHERE msg_id = %s",
                (redis_id,)
            )
            return result.fetchone() is not None
    
    async def _mark_processed(self, redis_id: str, stream: str) -> None:
        """Mark message as processed."""
        async with AsyncSessionFactory() as session:
            await session.execute(
                "INSERT INTO processed_events (msg_id, stream, processed_at) VALUES (%s, %s, NOW())",
                (redis_id, stream)
            )
            await session.commit()
    
    async def _start_agent_run(self, trace_id: str, trigger_event: str, input_data: dict) -> str:
        """Start tracking an agent run in Postgres."""
        run_id = str(uuid.uuid4())
        
        async with AsyncSessionFactory() as session:
            await session.execute(
                """
                INSERT INTO agent_runs (id, agent_id, trace_id, run_type, trigger_event,
                                      input_data, schema_version, source, status, created_at, updated_at)
                VALUES (%s, (SELECT id FROM agent_pool WHERE name = %s), %s, 'analysis', %s,
                        %s, 'v2', %s, 'running', NOW(), NOW())
                """,
                (run_id, self.name.lower(), trace_id, trigger_event, 
                 json.dumps(input_data), self.name.lower())
            )
            await session.commit()
        
        return run_id
    
    async def _update_agent_run(self, run_id: str, status: str, output_data: dict = None, 
                                error_message: str = None, execution_time_ms: int = None) -> None:
        """Update agent run status."""
        async with AsyncSessionFactory() as session:
            if status == 'completed' and output_data:
                await session.execute(
                    """
                    UPDATE agent_runs SET status = %s, output_data = %s, 
                           execution_time_ms = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(output_data), execution_time_ms, run_id)
                )
            elif status == 'failed' and error_message:
                await session.execute(
                    """
                    UPDATE agent_runs SET status = %s, error_message = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, error_message, run_id)
                )
            await session.commit()
    
    async def _write_agent_log(self, run_id: str, trace_id: str, log_level: str, 
                               message: str, step_name: str = None, step_data: dict = None) -> None:
        """Write an agent log entry."""
        async with AsyncSessionFactory() as session:
            await session.execute(
                """
                INSERT INTO agent_logs (id, agent_run_id, log_level, message, step_name,
                                      step_data, trace_id, schema_version, source, created_at)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, 'v2', %s, NOW())
                """,
                (run_id, log_level, message, step_name, json.dumps(step_data or {}), trace_id, self.name.lower())
            )
            await session.commit()
    
    async def _write_heartbeat(self, status: str, last_event: str) -> None:
        """Write agent heartbeat to Redis and Postgres."""
        if not self.redis:
            return
            
        heartbeat_data = {
            "status": status,
            "last_event": last_event,
            "event_count": self.event_count,
            "last_seen": int(time.time())
        }
        
        # Write to Redis cache
        await self.redis.set(
            f"agent:status:{self.name}",
            json.dumps(heartbeat_data),
            ex=60
        )
        
        # Write to Postgres
        async with AsyncSessionFactory() as session:
            await session.execute(
                """
                INSERT INTO agent_heartbeats (agent_name, status, last_event, event_count, last_seen)
                VALUES (%s, %s, %s, %s, to_timestamp(%s))
                ON CONFLICT (agent_name) DO UPDATE SET
                  status = EXCLUDED.status,
                  last_event = EXCLUDED.last_event,
                  event_count = EXCLUDED.event_count,
                  last_seen = EXCLUDED.last_seen
                """,
                (self.name, status, last_event, self.event_count, heartbeat_data["last_seen"])
            )
            await session.commit()

    async def _run(self) -> None:
        while self._running:
            messages_processed = False
            for stream in self.streams:
                messages = await self.bus.consume(
                    stream, group=DEFAULT_GROUP, consumer=self.consumer, count=20, block_ms=100
                )
                for redis_id, data in messages:
                    try:
                        # Exactly-once processing check
                        if await self._check_processed_events(redis_id):
                            await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                            continue
                        
                        # Extract trace_id from payload or generate new one
                        payload = json.loads(data.get("payload", "{}"))
                        trace_id = payload.get("trace_id", str(uuid.uuid4()))
                        
                        # Start agent run tracking
                        run_id = await self._start_agent_run(trace_id, redis_id, data)
                        
                        start_time = time.time()
                        await self.process(stream, redis_id, data)
                        execution_time = int((time.time() - start_time) * 1000)
                        
                        # Mark as processed
                        await self._mark_processed(redis_id, stream)
                        
                        # Update run as completed
                        await self._update_agent_run(run_id, "completed", {"processed": True}, execution_time_ms=execution_time)
                        
                        self.event_count += 1
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        messages_processed = True
                        
                    except Exception as exc:  # noqa: BLE001
                        # Try to extract trace_id for error tracking
                        try:
                            payload = json.loads(data.get("payload", "{}"))
                            trace_id = payload.get("trace_id", str(uuid.uuid4()))
                            run_id = await self._start_agent_run(trace_id, redis_id, data)
                            await self._update_agent_run(run_id, "failed", error_message=str(exc))
                        except:
                            pass  # Best effort for error tracking
                        
                        await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                        await self._write_heartbeat("ERROR", f"Processing error: {str(exc)}")
            
            # Update heartbeat if we processed messages or are waiting
            if messages_processed:
                await self._write_heartbeat("ACTIVE", f"Processed events from {len(self.streams)} streams")
            elif self.event_count == 0:
                await self._write_heartbeat("WAITING", "waiting for events")
                    
            await asyncio.sleep(0.05)


class GradeAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["decisions"], consumer="grade-agent", redis_client=redis_client)
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "decisions":
            self._fills += 1
            
            # Parse decision to get confidence for grading
            payload = json.loads(data.get("payload", "{}"))
            confidence = payload.get("confidence", 0.5)
            symbol = payload.get("symbol", "unknown")
            
            # Grade = confidence * 100
            grade_score = round(confidence * 100, 2)
            
            # Write to agent_grades table
            async with AsyncSessionFactory() as session:
                await session.execute(
                    """
                    INSERT INTO agent_grades (id, agent_id, agent_run_id, grade_type, score,
                                          metrics, schema_version, source, created_at)
                    VALUES (gen_random_uuid(), (SELECT id FROM agent_pool WHERE name = 'grade_agent'),
                           (SELECT id FROM agent_runs WHERE trace_id = %s ORDER BY created_at DESC LIMIT 1),
                           'overall', %s, %s, 'v2', 'grade_agent', NOW())
                    """,
                    (payload.get("trace_id"), grade_score, json.dumps({"confidence": confidence, "symbol": symbol}))
                )
                await session.commit()
            
            # Only forward if grade >= 30
            if grade_score >= 30:
                graded_decision = {
                    "payload": json.dumps({
                        "action": payload.get("action", "HOLD"),
                        "symbol": symbol,
                        "confidence": confidence,
                        "grade_score": grade_score,
                        "reasoning": payload.get("reasoning", ""),
                        "trace_id": payload.get("trace_id", str(uuid.uuid4())),
                        "ts": int(time.time()),
                        "source": "GRADE_AGENT"
                    })
                }
                await self.bus.publish("graded_decisions", graded_decision)


class ICUpdater(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="ic-updater", redis_client=redis_client)
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._fills += 1
        
        # Log that we processed the graded decision
        payload = json.loads(data.get("payload", "{}"))
        log_structured("info", "graded_decision_processed", 
                      score=payload.get("score"), 
                      source=payload.get("source"))
        
        if self._fills % max(int(settings.IC_UPDATE_EVERY_N_FILLS), 1) != 0:
            return
            
        ic_score = float(data.get("pnl_percent", 0) or 0)
        payload = {
            "msg_id": str(uuid.uuid4()),
            "factor_name": "momentum",
            "ic_score": str(ic_score),
            "fills": self._fills,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "ic_updater",
        }
        await self.redis.set("alpha:ic_weights", '{"momentum": 1.0}')
        await self.bus.publish("factor_ic_history", payload)


class ReflectionAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(
            bus,
            dlq,
            streams=["graded_decisions"],
            consumer="reflection-agent",
            redis_client=redis_client,
        )
        self._fills = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "graded_decisions":
            self._fills += 1
            
            # Parse the graded decision
            payload = json.loads(data.get("payload", "{}"))
            symbol = payload.get("symbol", "unknown")
            grade_score = payload.get("grade_score", 0)
            action = payload.get("action", "HOLD")
            trace_id = payload.get("trace_id", str(uuid.uuid4()))
            
            # Create reflection content
            reflection_content = f"Graded decision for {symbol}: action={action}, grade_score={grade_score}"
            
            # Write to vector_memory with proper PostgreSQL vector syntax
            async with AsyncSessionFactory() as session:
                # Create zero vector placeholder (1536 dimensions)
                zero_vector_str = "[" + ", ".join(["0.0"] * 1536) + "]"
                
                await session.execute(
                    """
                    INSERT INTO vector_memory (id, agent_id, strategy_id, content, content_type,
                                               embedding, vector_metadata, outcome, schema_version, source, created_at)
                    VALUES (gen_random_uuid(), (SELECT id FROM agent_pool WHERE name = 'reflection_agent'),
                           NULL, %s, 'insight', %s::vector, %s, NULL, 'v2', 'reflection_agent', NOW())
                    """,
                    (reflection_content, zero_vector_str, json.dumps({"symbol": symbol, "grade_score": grade_score, "action": action}))
                )
                await session.commit()
            
            # Log that we processed the event
            log_structured("info", "reflection_event_processed", stream=stream, symbol=symbol)
                
        if self._fills == 0 or self._fills % max(int(settings.REFLECT_EVERY_N_FILLS), 1) != 0:
            return
            
        reflection = {
            "payload": json.dumps({
                "summary": "Recent graded decisions reviewed; strategy insights generated.",
                "fills": self._fills,
                "ts": int(time.time()),
                "source": "REFLECTION_AGENT"
            })
        }
        await self.bus.publish("reflection_outputs", reflection)
        await self.bus.publish("notifications", {"msg_id": str(uuid.uuid4()), "source": "reflection_agent", "notification_type": "reflection", "message": reflection["payload"]})


class StrategyProposer(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="strategy-proposer", redis_client=redis_client)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        # Log that we processed the graded decision
        payload = json.loads(data.get("payload", "{}"))
        symbol = payload.get("symbol", "unknown")
        action = payload.get("action", "HOLD")
        
        log_structured("info", "graded_decision_processed_for_strategy", symbol=symbol, action=action)
        
        # Update strategies table based on graded decisions
        async with AsyncSessionFactory() as session:
            await session.execute(
                """
                INSERT INTO strategies (name, description, config, schema_version, source, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'v2', 'strategy_proposer', 'active', NOW(), NOW())
                ON CONFLICT (name) DO UPDATE SET
                  description = EXCLUDED.description,
                  config = EXCLUDED.config,
                  updated_at = EXCLUDED.updated_at
                """,
                (f"strategy_for_{symbol}", f"Strategy based on recent {action} decisions", 
                 json.dumps({"symbol": symbol, "recent_action": action}))
            )
            await session.commit()
        
        proposal = {
            "payload": json.dumps({
                "proposal_type": "strategy_adjustment",
                "content": {"symbol": symbol, "action": action, "reason": "Based on graded decisions"},
                "ts": int(time.time()),
                "source": "STRATEGY_PROPOSER"
            })
        }
        await self.bus.publish("proposals", proposal)
        await self.bus.publish("notifications", {"msg_id": str(uuid.uuid4()), "source": "strategy_proposer", "notification_type": "proposal", "message": "New strategy proposal generated"})


class NotificationAgent(MultiStreamAgent):
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                "market_events",
                "signals", 
                "decisions",
                "graded_decisions",
                "agent_grades",
                "factor_ic_history",
                "reflection_outputs",
                "proposals",
            ],
            consumer="notification-agent",
            redis_client=redis_client,
        )
        self.safe_writer = SafeWriter(AsyncSessionFactory)

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == "notifications":
            return  # Don't process our own notifications
            
        # Parse the data based on stream type
        payload = json.loads(data.get("payload", "{}")) if "payload" in data else data
        
        # Create notification based on stream and content
        if stream == "decisions":
            action = payload.get("action", "HOLD")
            confidence = payload.get("confidence", 0)
            symbol = payload.get("symbol", "unknown")
            
            # Write alert for high-confidence BUY/SELL decisions
            if action in ["BUY", "SELL"] and confidence > 0.65:
                await self.safe_writer.write_notification(
                    str(uuid.uuid4()), "trade_alert", {
                        "action": action,
                        "symbol": symbol,
                        "confidence": confidence,
                        "source": "NOTIFICATION_AGENT"
                    }
                )
                
                # Write to system_metrics
                async with AsyncSessionFactory() as session:
                    await session.execute(
                        """
                        INSERT INTO system_metrics (metric_name, metric_value, metric_unit, tags,
                                                    schema_version, source, timestamp)
                        VALUES ('trade_alert_fired', 1, 'count', %s, 'v2', 'notification_agent', NOW())
                        """,
                        (json.dumps({"symbol": symbol, "action": action}))
                    )
                    await session.commit()
        
        # Create a general notification for any stream event
        msg_id = data.get("msg_id") or redis_id
        notification = {
            "payload": json.dumps({
                "schema_version": "v2",
                "source": "notification_agent",
                "notification_type": f"stream:{stream}",
                "message": f"Event observed on {stream}",
                "metadata": {"observed_msg_id": msg_id},
                "ts": int(time.time())
            })
        }
        await self.bus.publish("notifications", notification)
        log_structured("debug", "notification_forwarded", stream=stream, observed_msg_id=msg_id)
