"""System metrics consumer - processes system_metrics stream."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.db import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.core.writer.safe_writer import SafeWriter

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
        Process a system metric message safely, generating a unique msg_id if missing.
        Ensures exactly-once writes with SafeWriter.
        """
        # Kill switch
        if await self.redis.get("kill_switch:active") == "1":
            raise RuntimeError("KillSwitchActive")
        # Use Redis msg_id if available, else generate UUID
        msg_id = data.get("msg_id") or str(uuid.uuid4())

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
        self.logger.info(
            "Processed system metric",
            extra={"msg_id": msg_id, "metric_name": metric_name},
        )

    def safe_parse_dt(self, dt_str):
        """Safely parse ISO datetime strings."""
        if not dt_str:
            return None

        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            self.logger.warning(f"Failed to parse datetime '{dt_str}': {e}")
            return None
