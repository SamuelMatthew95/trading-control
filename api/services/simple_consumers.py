"""Simple consumers for all missing streams."""

import logging
from typing import Any

from redis.asyncio import Redis

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

logger = logging.getLogger(__name__)


class SimpleConsumer(BaseStreamConsumer):
    """Simple consumer that just logs and acknowledges messages."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis, stream: str, consumer_name: str):
        super().__init__(
            bus, dlq, stream=stream, group=DEFAULT_GROUP, consumer=consumer_name
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        """Process message by logging and acknowledging."""
        if await self.redis.get("kill_switch:active") == "1":
            raise RuntimeError("KillSwitchActive")
        
        msg_id = data.get("msg_id", "unknown")
        
        # Just log and acknowledge - no processing needed for now
        log_structured(
            "debug",
            "message_processed",
            stream=self.stream,
            msg_id=msg_id,
            consumer=self.consumer
        )


class ExecutionsConsumer(SimpleConsumer):
    """Consumer for executions stream."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "executions", "executions-logger")


class RiskAlertsConsumer(SimpleConsumer):
    """Consumer for risk_alerts stream."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "risk_alerts", "risk-alerts-logger")


class LearningEventsConsumer(SimpleConsumer):
    """Consumer for learning_events stream."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "learning_events", "learning-events-logger")


class AgentLogsConsumer(SimpleConsumer):
    """Consumer for agent_logs stream."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "agent_logs", "agent-logs-logger")
