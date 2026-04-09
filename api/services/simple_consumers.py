"""Simple consumers for all missing streams - UUID-safe exactly-once processing."""

import logging
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    REDIS_KEY_KILL_SWITCH,
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_RISK_ALERTS,
)
from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

logger = logging.getLogger(__name__)


class SimpleConsumer(BaseStreamConsumer):
    """Simple consumer that logs and acknowledges messages with UUID-safe msg_id generation."""

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        stream: str,
        consumer_name: str,
    ):
        super().__init__(bus, dlq, stream=stream, group=DEFAULT_GROUP, consumer=consumer_name)
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        """Process message by logging and acknowledging with UUID-safe msg_id."""
        # Kill switch check — Redis is decode_responses=True so get() returns str
        value = await self.redis.get(REDIS_KEY_KILL_SWITCH)
        if value == "1":
            raise RuntimeError("KillSwitchActive")

        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        # Log payload for visibility (temporary fix for missing data)
        log_structured(
            "info",
            "message_processed",
            extra={
                "stream": self.stream,
                "msg_id": msg_id,
                "consumer": self.consumer,
                "payload": data,  # Log actual payload
            },
        )


class ExecutionsConsumer(SimpleConsumer):
    """Consumer for executions stream - writes executions to database."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, STREAM_EXECUTIONS, "executions-logger")
        self.safe_writer = SafeWriter(AsyncSessionFactory)

    async def process(self, data: dict[str, Any]) -> None:
        """Process execution message by writing to database."""
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")

        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        try:
            # Write execution to database using SafeWriter
            success = await self.safe_writer.write_execution(
                msg_id=msg_id, stream=self.stream, data=data
            )

            if success:
                log_structured(
                    "info",
                    "execution_processed",
                    stream=self.stream,
                    msg_id=msg_id,
                    order_id=data.get("order_id"),
                )
            else:
                log_structured(
                    "warning",
                    "execution_write_failed",
                    stream=self.stream,
                    msg_id=msg_id,
                )

        except Exception:
            log_structured(
                "error",
                "execution_processing_error",
                stream=self.stream,
                msg_id=msg_id,
                exc_info=True,
            )
            raise


class RiskAlertsConsumer(SimpleConsumer):
    """Consumer for risk_alerts stream - writes risk alerts to database."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, STREAM_RISK_ALERTS, "risk-alerts-logger")
        self.safe_writer = SafeWriter(AsyncSessionFactory)

    async def process(self, data: dict[str, Any]) -> None:
        """Process risk alert message by writing to database."""
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")

        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        try:
            # Write risk alert to database using SafeWriter
            success = await self.safe_writer.write_risk_alert(
                msg_id=msg_id, stream=self.stream, data=data
            )

            if success:
                log_structured(
                    "info",
                    "risk_alert_processed",
                    stream=self.stream,
                    msg_id=msg_id,
                    alert_type=data.get("alert_type"),
                )
            else:
                log_structured(
                    "warning",
                    "risk_alert_write_failed",
                    stream=self.stream,
                    msg_id=msg_id,
                )

        except Exception:
            log_structured(
                "error",
                "risk_alert_processing_error",
                stream=self.stream,
                msg_id=msg_id,
                exc_info=True,
            )
            raise


class LearningEventsConsumer(SimpleConsumer):
    """Consumer for learning_events stream - writes vector memories to database."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, STREAM_LEARNING_EVENTS, "learning-events-logger")
        self.safe_writer = SafeWriter(AsyncSessionFactory)

    async def process(self, data: dict[str, Any]) -> None:
        """Process learning event message by writing to database."""
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")

        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        try:
            # Write vector memory to database using SafeWriter
            success = await self.safe_writer.write_vector_memory(
                msg_id=msg_id, stream=self.stream, data=data
            )

            if success:
                log_structured(
                    "info",
                    "learning_event_processed",
                    stream=self.stream,
                    msg_id=msg_id,
                    content_type=data.get("content_type"),
                )
            else:
                log_structured(
                    "warning",
                    "learning_event_write_failed",
                    stream=self.stream,
                    msg_id=msg_id,
                )

        except Exception:
            log_structured(
                "error",
                "learning_event_processing_error",
                stream=self.stream,
                msg_id=msg_id,
                exc_info=True,
            )
            raise


class AgentLogsConsumer(SimpleConsumer):
    """Consumer for agent_logs stream - writes agent logs to database."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, STREAM_AGENT_LOGS, "agent-logs-logger")
        self.safe_writer = SafeWriter(AsyncSessionFactory)

    async def process(self, data: dict[str, Any]) -> None:
        """Process agent log message by writing to database."""
        if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
            raise RuntimeError("KillSwitchActive")

        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        try:
            # Write agent log to database using SafeWriter
            success = await self.safe_writer.write_agent_log(
                msg_id=msg_id, stream=self.stream, data=data
            )

            if success:
                log_structured(
                    "info",
                    "agent_log_processed",
                    stream=self.stream,
                    msg_id=msg_id,
                    agent_id=data.get("agent_id"),
                )
            else:
                log_structured(
                    "warning",
                    "agent_log_write_failed",
                    stream=self.stream,
                    msg_id=msg_id,
                )

        except Exception:
            log_structured(
                "error",
                "agent_log_processing_error",
                stream=self.stream,
                msg_id=msg_id,
                exc_info=True,
            )
            raise
