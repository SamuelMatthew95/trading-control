"""In-memory agent status registry for UI/debug visibility."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AGENT_NAMES = ("SIGNAL_AGENT", "RISK_AGENT", "CONSENSUS_AGENT", "SIZING_AGENT")


class AgentStateRegistry:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {
            name: {
                "name": name,
                "status": "idle",
                "health": "ok",
                "last_task": "none",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            for name in AGENT_NAMES
        }

    def update(
        self,
        name: str,
        *,
        status: str = "running",
        health: str = "ok",
        last_task: str = "event",
    ) -> dict[str, Any]:
        state = {
            "name": name,
            "status": status,
            "health": health,
            "last_task": last_task,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._states[name] = state
        return state

    def snapshot(self) -> list[dict[str, Any]]:
        return sorted(self._states.values(), key=lambda x: x["name"])
