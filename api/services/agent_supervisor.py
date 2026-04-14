"""AgentSupervisor: monitors all pipeline agents and restarts any that have crashed.

Architecture:
  - Runs as a background asyncio task (NOT a Redis stream consumer).
  - Every SUPERVISOR_CHECK_INTERVAL_SECONDS it inspects each agent's asyncio Task.
  - If a task has completed with an exception (crashed), it restarts the agent and
    publishes an alert to STREAM_RISK_ALERTS so the dashboard and NotificationAgent
    can surface the crash.
  - If a task was cancelled (expected during shutdown), no action is taken.

This implements the Multi-Agent Coordination pattern from the agentic design guide:
a dedicated supervisor layer that detects and recovers from agent failures without
manual intervention, giving the system self-healing properties.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    SOURCE_SUPERVISOR,
    STREAM_RISK_ALERTS,
    SUPERVISOR_CHECK_INTERVAL_SECONDS,
)
from api.events.bus import EventBus
from api.observability import log_structured


class AgentSupervisor:
    """Background task that monitors pipeline agents and restarts crashed tasks.

    Start/stop interface mirrors the agent API so main.py can manage it uniformly.
    """

    def __init__(self, bus: EventBus, redis_client: Any, agents: list[Any]) -> None:
        self.bus = bus
        self.redis = redis_client
        self._agents = agents
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="agent-supervisor")
        log_structured(
            "info",
            "agent_supervisor_started",
            agent_count=len(self._agents),
            interval=SUPERVISOR_CHECK_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                log_structured("warning", "supervisor_health_check_failed", exc_info=True)
            await asyncio.sleep(SUPERVISOR_CHECK_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def _check_health(self) -> None:
        """Inspect each agent's asyncio task; restart any that died unexpectedly."""
        for agent in self._agents:
            task: asyncio.Task[None] | None = getattr(agent, "_task", None)

            # Healthy: task is running or hasn't started yet
            if task is None or not task.done():
                continue

            # Cancelled during shutdown — do not restart
            if task.cancelled():
                continue

            exc = task.exception()
            agent_name = getattr(agent, "consumer", type(agent).__name__)
            # Compute once — avoids repeating str(exc) which trips the logging safety check
            error_detail = repr(exc) if exc else "task_completed_unexpectedly"

            log_structured(
                "warning",
                "supervisor_agent_task_died",
                agent=agent_name,
                exc_info=exc if exc else False,
            )

            # Publish crash alert so dashboard and NotificationAgent see it
            try:
                await self.bus.publish(
                    STREAM_RISK_ALERTS,
                    {
                        "type": "agent_crashed",
                        "agent": agent_name,
                        "error": error_detail,
                        "source": SOURCE_SUPERVISOR,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                log_structured("warning", "supervisor_alert_publish_failed", exc_info=True)

            # Restart the agent
            try:
                await agent.start()
                log_structured("info", "supervisor_restarted_agent", agent=agent_name)
            except Exception:
                log_structured(
                    "error",
                    "supervisor_restart_failed",
                    agent=agent_name,
                    exc_info=True,
                )
