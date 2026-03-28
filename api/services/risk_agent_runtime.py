"""Background runtime that emits synthetic RISK_AGENT activity for dashboards."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from uuid import uuid4

from api.events.bus import EventBus
from api.observability import log_structured


class RiskAgentRuntime:
    """Lightweight runtime loop that publishes RISK_AGENT activity to Redis."""

    def __init__(self, bus: EventBus, *, interval_seconds: float = 5.0):
        self.bus = bus
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run(), name="risk-agent-runtime")
        log_structured(
            "info",
            "risk_agent_runtime_started",
            event_name="risk_agent_runtime_started",
            agent_name="RISK_AGENT",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def stop(self) -> None:
        self._running = False
        if not self._task:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while self._running:
            now = datetime.now(timezone.utc).isoformat()
            event = {
                "msg_id": str(uuid4()),
                "type": "agent_heartbeat",
                "event_type": "risk_check",
                "agent_name": "RISK_AGENT",
                "agent": "RISK_AGENT",
                "status": "monitoring",
                "health": "ok",
                "last_task": "risk_check",
                "timestamp": now,
                "heartbeat": True,
            }
            await self.bus.publish("risk_alerts", event)
            await asyncio.sleep(self.interval_seconds)
