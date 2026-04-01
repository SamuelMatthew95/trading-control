"""Pipeline agents wired into the runtime lifespan.

Stream chain:
  market_events → SIGNAL_AGENT → signals
  signals → REASONING_AGENT → decisions
  decisions → GRADE_AGENT → graded_decisions
  graded_decisions → IC_UPDATER / REFLECTION_AGENT / STRATEGY_PROPOSER / NOTIFICATION_AGENT
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class MultiStreamAgent:
    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        streams: list[str],
        consumer: str,
    ) -> None:
        self.bus = bus
        self.dlq = dlq
        self.streams = streams
        self.consumer = consumer
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.consumer}")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError

    async def _run(self) -> None:
        while self._running:
            for stream in self.streams:
                messages = await self.bus.consume(
                    stream,
                    group=DEFAULT_GROUP,
                    consumer=self.consumer,
                    count=20,
                    block_ms=100,
                )
                for redis_id, data in messages:
                    try:
                        await self.process(stream, redis_id, data)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
                    except Exception as exc:  # noqa: BLE001
                        log_structured(
                            "error",
                            "agent processing failed",
                            agent=self.consumer,
                            stream=stream,
                            redis_id=redis_id,
                            exc_info=True,
                        )
                        await self.dlq.push(stream, redis_id, data, error=str(exc), retries=1)
                        await self.bus.acknowledge(stream, DEFAULT_GROUP, redis_id)
            await asyncio.sleep(0.05)  # Agent processing throttle


# ---------------------------------------------------------------------------
# Helper: shared DB patterns
# ---------------------------------------------------------------------------


async def _get_agent_pool_id(name: str) -> str | None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            text("SELECT id FROM agent_pool WHERE name = :name"),
            {"name": name},
        )
        row = result.first()
        return str(row[0]) if row else None


async def _check_processed(msg_id: str) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            text("SELECT 1 FROM processed_events WHERE msg_id = :msg_id"),
            {"msg_id": msg_id},
        )
        return result.first() is not None


async def _mark_processed(msg_id: str, stream: str) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO processed_events (msg_id, stream)
                    VALUES (:msg_id, :stream) ON CONFLICT DO NOTHING
                """),
                {"msg_id": msg_id, "stream": stream},
            )


async def _create_agent_run(
    run_id: str,
    agent_pool_id: str | None,
    trace_id: str,
    msg_id: str,
    input_data: dict,
    source: str,
) -> None:
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
                         :input_data, 'v3', :source, 'running', NOW(), NOW())
                """),
                {
                    "id": run_id,
                    "agent_id": agent_pool_id,
                    "trace_id": trace_id,
                    "trigger": msg_id,
                    "input_data": json.dumps(input_data),
                    "source": source,
                },
            )


async def _complete_agent_run(run_id: str, output: dict, elapsed_ms: int) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    UPDATE agent_runs SET status='completed', output_data=:output,
                        execution_time_ms=:elapsed, updated_at=NOW()
                    WHERE id=:id
                """),
                {
                    "output": json.dumps(output),
                    "elapsed": elapsed_ms,
                    "id": run_id,
                },
            )


async def _fail_agent_run(run_id: str, error: str) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    UPDATE agent_runs SET status='failed', error_message=:err,
                        updated_at=NOW() WHERE id=:id
                """),
                {"err": error, "id": run_id},
            )


async def _write_agent_log(trace_id: str, log_type: str, payload: dict) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO agent_logs (trace_id, log_type, payload)
                    VALUES (:trace_id, :log_type, :payload)
                """),
                {
                    "trace_id": trace_id,
                    "log_type": log_type,
                    "payload": json.dumps(payload),
                },
            )


async def _write_heartbeat(
    redis: Redis,
    agent_name: str,
    last_event: str,
    event_count: int,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": "ACTIVE",
        "last_event": last_event,
        "event_count": event_count,
        "last_seen": int(time.time()),
    }
    if extra:
        payload.update(extra)
    await redis.set(
        f"agent:status:{agent_name}",
        json.dumps(payload),
        ex=60,
    )
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO agent_heartbeats
                        (agent_name, status, last_event, event_count, last_seen)
                    VALUES (:name, 'ACTIVE', :last_event, :count, NOW())
                    ON CONFLICT (agent_name) DO UPDATE SET
                        status='ACTIVE', last_event=EXCLUDED.last_event,
                        event_count=EXCLUDED.event_count, last_seen=NOW()
                """),
                {
                    "name": agent_name,
                    "last_event": last_event,
                    "count": event_count,
                },
            )


async def _write_event(
    event_type: str,
    data: dict,
    idem_key: str,
    source: str,
) -> None:
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO events
                        (event_type, entity_type, data,
                         idempotency_key, source, schema_version)
                    VALUES (:etype, 'agent', :data, :idem, :source, 'v3')
                    ON CONFLICT (idempotency_key) DO NOTHING
                """),
                {
                    "etype": event_type,
                    "data": json.dumps(data),
                    "idem": idem_key,
                    "source": source,
                },
            )


def _parse_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Extract payload from stream message — handles both wrapped and flat."""
    raw = data.get("payload")
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    return data


# ---------------------------------------------------------------------------
# REASONING_AGENT — signals → decisions
# ---------------------------------------------------------------------------


class ReasoningAgent(MultiStreamAgent):
    AGENT_NAME = "REASONING_AGENT"

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["signals"], consumer="reasoning-agent")
        self.redis = redis_client
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            log_structured("warning", f"[{self.AGENT_NAME}] duplicate: {msg_id}")
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            signal_type = payload.get("type", "PRICE_UPDATE")
            symbol = payload.get("symbol", "")
            price = float(payload.get("price", 0))
            direction = payload.get("direction", "neutral")
            strength = payload.get("strength", "LOW")

            # Decision map
            if signal_type == "STRONG_MOMENTUM" and direction == "bullish":
                action, confidence = "BUY", 0.75
            elif signal_type == "STRONG_MOMENTUM" and direction == "bearish":
                action, confidence = "SELL", 0.75
            elif signal_type == "MOMENTUM" and direction == "bullish":
                action, confidence = "WATCH", 0.55
            elif signal_type == "MOMENTUM" and direction == "bearish":
                action, confidence = "WATCH", 0.45
            else:
                action, confidence = "HOLD", 0.30

            reasoning = f"{signal_type} {direction} signal detected for {symbol} at ${price}"

            ts = int(time.time())
            decision_payload = {
                "action": action,
                "symbol": symbol,
                "price": price,
                "confidence": confidence,
                "reasoning": reasoning,
                "signal_type": signal_type,
                "signal_strength": strength,
                "trace_id": trace_id,
                "ts": ts,
                "source": self.AGENT_NAME,
                "msg_id": str(uuid.uuid4()),
            }

            await self.bus.publish("decisions", decision_payload)
            await _write_event(
                "decision.made",
                decision_payload,
                f"decision-{symbol}-{trace_id}",
                self.AGENT_NAME,
            )
            await _mark_processed(msg_id, "signals")
            await _write_agent_log(trace_id, "decision_made", decision_payload)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, decision_payload, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.redis,
                self.AGENT_NAME,
                f"{action} {symbol} conf={confidence}",
                self.total_events,
            )

            log_structured(
                "info",
                f"[{self.AGENT_NAME}] decision: action={action} symbol={symbol} "
                f"confidence={confidence} trace_id={trace_id}",
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise


# ---------------------------------------------------------------------------
# GRADE_AGENT — decisions → graded_decisions
# ---------------------------------------------------------------------------


class GradeAgent(MultiStreamAgent):
    AGENT_NAME = "GRADE_AGENT"

    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(bus, dlq, streams=["decisions"], consumer="grade-agent")
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            action = payload.get("action", "HOLD")
            symbol = payload.get("symbol", "")
            price = float(payload.get("price", 0))
            confidence = float(payload.get("confidence", 0))
            reasoning = payload.get("reasoning", "")
            signal_strength = payload.get("signal_strength", "LOW")

            grade_score = round(confidence * 100, 2)

            # Write to agent_grades
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO agent_grades
                                (agent_id, grade_type, score, metrics,
                                 trace_id, schema_version, source)
                            VALUES (:agent_id, 'overall', :score, :metrics,
                                    :trace_id, 'v3', :source)
                        """),
                        {
                            "agent_id": self._pool_id,
                            "score": grade_score,
                            "metrics": json.dumps(
                                {
                                    "action": action,
                                    "symbol": symbol,
                                    "confidence": confidence,
                                    "signal_strength": signal_strength,
                                }
                            ),
                            "trace_id": trace_id,
                            "source": self.AGENT_NAME,
                        },
                    )

            ts = int(time.time())

            if grade_score >= 30:
                graded_payload = {
                    "action": action,
                    "symbol": symbol,
                    "price": price,
                    "confidence": confidence,
                    "grade_score": grade_score,
                    "reasoning": reasoning,
                    "signal_strength": signal_strength,
                    "trace_id": trace_id,
                    "ts": ts,
                    "source": self.AGENT_NAME,
                    "msg_id": str(uuid.uuid4()),
                }
                await self.bus.publish("graded_decisions", graded_payload)
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] passed: symbol={symbol} action={action} "
                    f"grade={grade_score} trace_id={trace_id}",
                )
            else:
                graded_payload = {"action": action, "grade_score": grade_score}
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] dropped: symbol={symbol} action={action} "
                    f"grade={grade_score} below 30",
                )

            await _mark_processed(msg_id, "decisions")
            await _write_agent_log(trace_id, "grade_assigned", graded_payload)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, graded_payload, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.bus.redis,
                self.AGENT_NAME,
                f"{action} {symbol} grade={grade_score}",
                self.total_events,
                extra={"last_grade_score": grade_score},
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise


# ---------------------------------------------------------------------------
# IC_UPDATER — graded_decisions → strategies table
# ---------------------------------------------------------------------------


class ICUpdater(MultiStreamAgent):
    AGENT_NAME = "IC_UPDATER"

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="ic-updater")
        self.redis = redis_client
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            action = payload.get("action", "HOLD")
            symbol = payload.get("symbol", "")
            confidence = float(payload.get("confidence", 0))
            ts = payload.get("ts", int(time.time()))

            output = {"action": action, "symbol": symbol, "confidence": confidence}

            if action in ("BUY", "SELL") and confidence >= 0.6:
                strategy_name = f"auto_{symbol.replace('/', '_').lower()}"

                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("SELECT id, config FROM strategies WHERE name = :name"),
                        {"name": strategy_name},
                    )
                    row = result.first()

                    async with session.begin():
                        if not row:
                            config = {
                                "symbol": symbol,
                                "last_action": action,
                                "last_confidence": confidence,
                                "last_updated": ts,
                                "actions": [{"action": action, "confidence": confidence, "ts": ts}],
                            }
                            await session.execute(
                                text("""
                                    INSERT INTO strategies
                                        (name, description, config,
                                         schema_version, source, status, rules, risk_limits)
                                    VALUES (:name, :desc, :config,
                                            'v3', 'IC_UPDATER', 'active',
                                            '{}'::jsonb, '{}'::jsonb)
                                """),
                                {
                                    "name": strategy_name,
                                    "desc": f"Auto strategy for {symbol}",
                                    "config": json.dumps(config),
                                },
                            )
                        else:
                            existing_config = row[1] or {}
                            if isinstance(existing_config, str):
                                existing_config = json.loads(existing_config)
                            existing_config["last_action"] = action
                            existing_config["last_confidence"] = confidence
                            existing_config["last_updated"] = ts
                            actions = existing_config.get("actions", [])
                            actions.append({"action": action, "confidence": confidence, "ts": ts})
                            existing_config["actions"] = actions[-20:]
                            await session.execute(
                                text("""
                                    UPDATE strategies SET config=:config,
                                        updated_at=NOW() WHERE name=:name
                                """),
                                {
                                    "config": json.dumps(existing_config),
                                    "name": strategy_name,
                                },
                            )

                await _write_event(
                    "strategy.updated",
                    output,
                    f"ic-{symbol}-{trace_id}",
                    self.AGENT_NAME,
                )
                output["strategy"] = strategy_name
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] strategy updated: name={strategy_name} "
                    f"action={action} confidence={confidence} trace_id={trace_id}",
                )
            else:
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] no update: symbol={symbol} action={action} "
                    f"confidence={confidence} — skipping",
                )

            await _mark_processed(msg_id, "graded_decisions")
            await _write_agent_log(trace_id, "ic_update", output)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, output, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.redis,
                self.AGENT_NAME,
                f"{action} {symbol}",
                self.total_events,
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise


# ---------------------------------------------------------------------------
# REFLECTION_AGENT — graded_decisions → vector_memory
# ---------------------------------------------------------------------------


class ReflectionAgent(MultiStreamAgent):
    AGENT_NAME = "REFLECTION_AGENT"

    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="reflection-agent")
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            action = payload.get("action", "HOLD")
            symbol = payload.get("symbol", "")
            price = float(payload.get("price", 0))
            confidence = float(payload.get("confidence", 0))
            grade_score = float(payload.get("grade_score", 0))
            reasoning = payload.get("reasoning", "")
            ts = payload.get("ts", int(time.time()))

            content = (
                f"{action} signal for {symbol} at ${price}. "
                f"Confidence: {confidence}. Grade: {grade_score}. "
                f"Reasoning: {reasoning}."
            )

            metadata = json.dumps(
                {
                    "symbol": symbol,
                    "action": action,
                    "confidence": confidence,
                    "grade_score": grade_score,
                    "trace_id": trace_id,
                    "ts": ts,
                }
            )

            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            INSERT INTO vector_memory
                                (agent_id, content, content_type,
                                 vector_metadata, schema_version, source)
                            VALUES
                                (:agent_id, :content, 'memory',
                                 :metadata, 'v3', 'REFLECTION_AGENT')
                        """),
                        {
                            "agent_id": self._pool_id,
                            "content": content,
                            "metadata": metadata,
                        },
                    )

            output = {
                "action": action,
                "symbol": symbol,
                "grade_score": grade_score,
                "content_length": len(content),
            }

            await _mark_processed(msg_id, "graded_decisions")
            await _write_agent_log(trace_id, "reflection", output)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, output, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.bus.redis,
                self.AGENT_NAME,
                f"{action} {symbol} grade={grade_score}",
                self.total_events,
            )

            log_structured(
                "info",
                f"[{self.AGENT_NAME}] memory written: symbol={symbol} "
                f"action={action} grade={grade_score} trace_id={trace_id}",
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise


# ---------------------------------------------------------------------------
# STRATEGY_PROPOSER — graded_decisions → strategies table
# ---------------------------------------------------------------------------


class StrategyProposer(MultiStreamAgent):
    AGENT_NAME = "STRATEGY_PROPOSER"

    def __init__(self, bus: EventBus, dlq: DLQManager) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="strategy-proposer")
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            action = payload.get("action", "HOLD")
            symbol = payload.get("symbol", "")
            confidence = float(payload.get("confidence", 0))
            grade_score = float(payload.get("grade_score", 0))
            ts = payload.get("ts", int(time.time()))

            output = {"action": action, "symbol": symbol, "grade_score": grade_score}

            if action in ("BUY", "SELL") and grade_score >= 60:
                strategy_name = f"auto_{symbol.replace('/', '_').lower()}"

                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("SELECT id, config FROM strategies WHERE name = :name"),
                        {"name": strategy_name},
                    )
                    row = result.first()

                    if row:
                        config = row[1] or {}
                        if isinstance(config, str):
                            config = json.loads(config)
                    else:
                        config = {}

                    proposed_actions = config.get("proposed_actions", [])
                    proposed_actions.append(
                        {
                            "action": action,
                            "confidence": confidence,
                            "grade_score": grade_score,
                            "ts": ts,
                        }
                    )
                    proposed_actions = proposed_actions[-10:]

                    recent_buys = sum(1 for a in proposed_actions if a["action"] == "BUY")
                    recent_sells = sum(1 for a in proposed_actions if a["action"] == "SELL")
                    if recent_buys >= 5:
                        bias = "bullish"
                    elif recent_sells >= 5:
                        bias = "bearish"
                    else:
                        bias = "neutral"

                    config["proposed_actions"] = proposed_actions
                    config["bias"] = bias

                    async with session.begin():
                        if row:
                            await session.execute(
                                text("""
                                    UPDATE strategies SET config=:config,
                                        updated_at=NOW() WHERE name=:name
                                """),
                                {
                                    "config": json.dumps(config),
                                    "name": strategy_name,
                                },
                            )
                        else:
                            await session.execute(
                                text("""
                                    INSERT INTO strategies
                                        (name, description, config,
                                         schema_version, source, status,
                                         rules, risk_limits)
                                    VALUES (:name, :desc, :config,
                                            'v3', 'STRATEGY_PROPOSER', 'active',
                                            '{}'::jsonb, '{}'::jsonb)
                                """),
                                {
                                    "name": strategy_name,
                                    "desc": f"Auto strategy for {symbol}",
                                    "config": json.dumps(config),
                                },
                            )

                await _write_event(
                    "strategy.proposal",
                    output,
                    f"proposal-{symbol}-{trace_id}",
                    self.AGENT_NAME,
                )
                output["bias"] = bias
                output["buys"] = recent_buys
                output["sells"] = recent_sells

                await self.bus.publish(
                    "proposals",
                    {
                        "type": "strategy_proposal",
                        "symbol": symbol,
                        "action": action,
                        "confidence": confidence,
                        "grade_score": grade_score,
                        "bias": bias,
                        "buys": recent_buys,
                        "sells": recent_sells,
                        "strategy_name": strategy_name,
                        "trace_id": trace_id,
                        "source": self.AGENT_NAME,
                        "schema_version": "v3",
                        "ts": ts,
                    },
                )

                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] proposal: symbol={symbol} bias={bias} "
                    f"buys={recent_buys} sells={recent_sells} trace_id={trace_id}",
                )
            else:
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] skipped: symbol={symbol} "
                    f"grade={grade_score} below 60 threshold",
                )

            await _mark_processed(msg_id, "graded_decisions")
            await _write_agent_log(trace_id, "strategy_proposal", output)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, output, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.bus.redis,
                self.AGENT_NAME,
                f"{action} {symbol} grade={grade_score}",
                self.total_events,
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise


# ---------------------------------------------------------------------------
# NOTIFICATION_AGENT — graded_decisions → events + system_metrics + Redis alert
# ---------------------------------------------------------------------------


class NotificationAgent(MultiStreamAgent):
    AGENT_NAME = "NOTIFICATION_AGENT"

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis) -> None:
        super().__init__(bus, dlq, streams=["graded_decisions"], consumer="notification-agent")
        self.redis = redis_client
        self.total_events = 0
        self._pool_id: str | None = None

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        payload = _parse_payload(data)
        msg_id = data.get("msg_id") or payload.get("msg_id") or redis_id
        trace_id = payload.get("trace_id") or str(uuid.uuid4())

        if await _check_processed(msg_id):
            return

        if not self._pool_id:
            self._pool_id = await _get_agent_pool_id(self.AGENT_NAME)

        run_id = str(uuid.uuid4())
        start = time.perf_counter()
        await _create_agent_run(run_id, self._pool_id, trace_id, msg_id, payload, self.AGENT_NAME)

        try:
            action = payload.get("action", "HOLD")
            symbol = payload.get("symbol", "")
            price = float(payload.get("price", 0))
            confidence = float(payload.get("confidence", 0))
            grade_score = float(payload.get("grade_score", 0))
            ts = payload.get("ts", int(time.time()))

            output = {
                "action": action,
                "symbol": symbol,
                "confidence": confidence,
                "grade_score": grade_score,
                "alerted": False,
            }

            if action in ("BUY", "SELL") and confidence >= 0.65 and grade_score >= 65:
                alert_data = {
                    "symbol": symbol,
                    "action": action,
                    "confidence": confidence,
                    "grade_score": grade_score,
                    "price": price,
                    "trace_id": trace_id,
                }

                await _write_event(
                    "trade.alert",
                    alert_data,
                    f"alert-{symbol}-{trace_id}",
                    self.AGENT_NAME,
                )

                # system_metrics
                async with AsyncSessionFactory() as session:
                    async with session.begin():
                        await session.execute(
                            text("""
                                INSERT INTO system_metrics
                                    (metric_name, metric_value, metric_unit,
                                     tags, schema_version, source, timestamp)
                                VALUES ('trade_alert_fired', 1, 'count',
                                        :tags, 'v3', 'NOTIFICATION_AGENT', NOW())
                            """),
                            {
                                "tags": json.dumps(
                                    {
                                        "symbol": symbol,
                                        "action": action,
                                        "confidence": confidence,
                                    }
                                ),
                            },
                        )

                # Redis alert for dashboard
                await self.redis.set(
                    f"alert:latest:{symbol}",
                    json.dumps(
                        {
                            "action": action,
                            "price": price,
                            "confidence": confidence,
                            "grade_score": grade_score,
                            "ts": ts,
                        }
                    ),
                    ex=300,
                )

                output["alerted"] = True

                await self.bus.publish(
                    "notifications",
                    {
                        "type": "trade_alert",
                        "symbol": symbol,
                        "action": action,
                        "confidence": confidence,
                        "grade_score": grade_score,
                        "price": price,
                        "trace_id": trace_id,
                        "source": self.AGENT_NAME,
                        "schema_version": "v3",
                        "ts": ts,
                    },
                )

                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] ALERT FIRED: symbol={symbol} "
                    f"action={action} confidence={confidence} "
                    f"grade={grade_score} price={price} trace_id={trace_id}",
                )
            else:
                log_structured(
                    "info",
                    f"[{self.AGENT_NAME}] no alert: symbol={symbol} "
                    f"action={action} confidence={confidence} "
                    f"grade={grade_score} — below threshold",
                )

            await _mark_processed(msg_id, "graded_decisions")
            await _write_agent_log(trace_id, "notification", output)

            elapsed = int((time.perf_counter() - start) * 1000)
            await _complete_agent_run(run_id, output, elapsed)

            self.total_events += 1
            await _write_heartbeat(
                self.redis,
                self.AGENT_NAME,
                f"{action} {symbol} alert={'yes' if output['alerted'] else 'no'}",
                self.total_events,
            )

        except Exception:
            log_structured("error", "agent processing failed", agent=self.AGENT_NAME, exc_info=True)
            await _fail_agent_run(run_id, "processing_error")
            raise
