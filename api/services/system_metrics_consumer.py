"""System metrics consumer - processes system_metrics stream."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.core.writer.safe_writer import SafeWriter
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured

logger = logging.getLogger(__name__)


class SystemMetricsConsumer(BaseStreamConsumer):
    """Consumes system_metrics stream and processes them."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(
            bus,
            dlq,
            stream="system_metrics",
            group=DEFAULT_GROUP,
            consumer="system-metrics",
        )
        self.redis = redis_client
        self.safe_writer = SafeWriter(AsyncSessionFactory)
        self.logger = logging.getLogger(__name__)

    async def process(self, data: dict[str, Any]) -> None:
        """
        Process a system metric message safely.
        Ensures exactly-once writes with SafeWriter and proper msg_id validation.
        """
        # Kill switch - fix Redis bytes comparison
        value = await self.redis.get("kill_switch:active")
        if value and value.decode() == "1":
            raise RuntimeError("KillSwitchActive")
        # Use centralized msg_id extraction
        msg_id = self.extract_msg_id(data)

        # Parse timestamp, fallback to UTC now
        timestamp = self.safe_parse_dt(data.get("timestamp")) or datetime.now(
            timezone.utc
        )

        # Map input data to DB columns
        metric_name = data.get("metric_name")
        metric_value = data.get("value")
        metric_unit = data.get("unit") or None
        tags = data.get("tags") or {}

        # Write to database via SafeWriter
        await self.safe_writer.write_system_metric(
            msg_id=msg_id,
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            tags=tags,
            schema_version="v2",
            source="system_monitor",
            timestamp=timestamp,
        )

        # Log for observability
        log_structured("info", "system metric processed", msg_id=msg_id, metric_name=metric_name)

    def safe_parse_dt(self, dt_str):
        """Safely parse ISO datetime strings."""
        if not dt_str:
            return None

        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            log_structured("warning", "datetime parse failed", dt_str=dt_str, error=str(e))
            return None
