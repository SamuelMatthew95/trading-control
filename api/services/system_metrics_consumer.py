"""System metrics consumer - processes system_metrics stream."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.system_metrics_handler import handle_system_metric

logger = logging.getLogger(__name__)


class SystemMetricsConsumer(BaseStreamConsumer):
    """Consumes system_metrics stream and processes them."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(
            bus, dlq, stream="system_metrics", group=DEFAULT_GROUP, consumer="system-metrics"
        )
        self.redis = redis_client

    async def process(self, data: dict[str, Any]) -> None:
        """Process system metric data."""
        if await self.redis.get("kill_switch:active") == "1":
            raise RuntimeError("KillSwitchActive")
        
        # Extract message metadata
        msg_id = data.get("msg_id", "unknown")
        stream = data.get("stream", "system_metrics")
        trace_id = data.get("trace_id", msg_id)
        
        # Process the metric using our handler
        result = await handle_system_metric(msg_id, stream, data, trace_id)
        
        if not result.success:
            if result.retryable:
                # Retryable error - let the consumer retry
                raise RuntimeError(f"Retryable error: {result.message}")
            else:
                # Non-retryable error - log but don't fail
                log_structured(
                    "warning",
                    "system_metric_processing_failed",
                    msg_id=msg_id,
                    error=result.message
                )
        
        log_structured(
            "debug",
            "system_metric_processed",
            msg_id=msg_id,
            metric_name=data.get("metric_name"),
            success=result.success
        )
