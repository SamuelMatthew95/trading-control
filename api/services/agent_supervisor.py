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
from collections import defaultdict, deque
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from api.constants import (
    SOURCE_SUPERVISOR,
    STREAM_RISK_ALERTS,
    SUPERVISOR_CHECK_INTERVAL_SECONDS,
    SUPERVISOR_MAX_RESTARTS_PER_WINDOW,
    SUPERVISOR_RESTART_WINDOW_SECONDS,
    FieldName,
)
from api.events.bus import EventBus
from api.observability import log_structured


class AgentSupervisor:
    """Background task that monitors pipeline agents and restarts crashed tasks.

    Start/stop interface mirrors the agent API so main.py can manage it uniformly.
    """

    def __init__(self, bus: EventBus, agents: list[Any]) -> None:
        self.bus = bus
        self._agents = agents
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._restart_history: defaultdict[str, deque[datetime]] = defaultdict(deque)

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
                log_structured("debug", "supervisor_tick", agent_count=len(self._agents))
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
        """Inspect each agent's task; restart any that died unexpectedly."""
        for agent in self._agents:
            # Skip healthy agents and those cancelled during normal shutdown.
            if not agent.has_crashed:
                continue

            exc = agent._task.exception()  # noqa: SLF001 — safe after has_crashed is True
            agent_name = agent.name
            error_detail = repr(exc) if exc else "task_completed_unexpectedly"

            log_structured(
                "warning",
                "supervisor_agent_task_died",
                agent=agent_name,
                exc_info=exc if exc else False,
            )

            # Publish crash alert so dashboard and NotificationAgent see it.
            try:
                await self.bus.publish(
                    STREAM_RISK_ALERTS,
                    {
                        FieldName.TYPE: "agent_crashed",
                        FieldName.AGENT: agent_name,
                        FieldName.ERROR: error_detail,
                        FieldName.SOURCE: SOURCE_SUPERVISOR,
                        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                log_structured("warning", "supervisor_alert_publish_failed", exc_info=True)

            # Restart the agent.
            try:
                if not self._can_restart(agent_name):
                    log_structured(
                        "error",
                        "supervisor_restart_suppressed",
                        agent=agent_name,
                        max_restarts=SUPERVISOR_MAX_RESTARTS_PER_WINDOW,
                        window_seconds=SUPERVISOR_RESTART_WINDOW_SECONDS,
                    )
                    continue
                await agent.start()
                self._record_restart(agent_name)
                log_structured("info", "supervisor_restarted_agent", agent=agent_name)
            except Exception:
                log_structured(
                    "error",
                    "supervisor_restart_failed",
                    agent=agent_name,
                    exc_info=True,
                )

    def _can_restart(self, agent_name: str) -> bool:
        now = datetime.now(timezone.utc)
        restarts = self._restart_history[agent_name]
        window_start = now.timestamp() - SUPERVISOR_RESTART_WINDOW_SECONDS
        while restarts and restarts[0].timestamp() < window_start:
            restarts.popleft()
        return len(restarts) < SUPERVISOR_MAX_RESTARTS_PER_WINDOW

    def _record_restart(self, agent_name: str) -> None:
        self._restart_history[agent_name].append(datetime.now(timezone.utc))
