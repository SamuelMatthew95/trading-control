"""In-memory agent status registry for UI/debug visibility."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Names match the actual running agents in main.py lifespan
AGENT_NAMES = (
    "SIGNAL_AGENT",
    "REASONING_AGENT",
    "GRADE_AGENT",
    "IC_UPDATER",
    "REFLECTION_AGENT",
    "STRATEGY_PROPOSER",
    "NOTIFICATION_AGENT",
)


class AgentStateRegistry:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {
            name: {
                "name": name,
                "status": "waiting",
                "health": "ok",
                "last_task": "none",
                "event_count": 0,
                "last_seen": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            for name in AGENT_NAMES
        }

    def record_event(self, name: str, *, task: str = "event") -> None:
        """Called by agents each time they process a message."""
        state = self._states.get(name)
        if state is None:
            state = {
                "name": name,
                "status": "waiting",
                "health": "ok",
                "last_task": "none",
                "event_count": 0,
                "last_seen": None,
            }
            self._states[name] = state
        now = datetime.now(timezone.utc).isoformat()
        state["status"] = "running"
        state["health"] = "ok"
        state["last_task"] = task
        state["event_count"] = int(state.get("event_count") or 0) + 1
        state["last_seen"] = now
        state["updated_at"] = now

    def update(
        self,
        name: str,
        *,
        status: str = "running",
        health: str = "ok",
        last_task: str = "event",
    ) -> dict[str, Any]:
        """Legacy update used by EventPipeline for agent_name events."""
        state = self._states.get(name) or {
            "name": name,
            "event_count": 0,
            "last_seen": None,
        }
        now = datetime.now(timezone.utc).isoformat()
        state.update(
            {
                "name": name,
                "status": status,
                "health": health,
                "last_task": last_task,
                "event_count": int(state.get("event_count") or 0) + 1,
                "last_seen": now,
                "updated_at": now,
            }
        )
        self._states[name] = state
        return state

    def snapshot(self) -> list[dict[str, Any]]:
        return sorted(self._states.values(), key=lambda x: x["name"])
