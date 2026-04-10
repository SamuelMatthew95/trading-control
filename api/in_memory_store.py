from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    "signal_generator": {"status": "idle"},
    "reasoning": {"status": "idle"},
    "execution": {"status": "idle"},
    "grade": {"status": "idle"},
    "ic_updater": {"status": "idle"},
    "reflection": {"status": "idle"},
    "strategy_proposer": {"status": "idle"},
    "notification": {"status": "idle"},
}


@dataclass(slots=True)
class InMemoryStore:
    """Best-effort runtime fallback when external dependencies are down."""

    agents: dict[str, dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_AGENTS))
    notifications: list[dict[str, Any]] = field(default_factory=list)
    last_health: str = "unknown"

    def upsert_agent(self, agent_id: str, data: dict[str, Any]) -> None:
        existing = self.agents.get(agent_id, {})
        self.agents[agent_id] = {**existing, **data}

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.agents.get(agent_id)

    def add_notification(
        self,
        message: str,
        level: str = "info",
        *,
        notification_type: str = "system",
    ) -> dict[str, Any]:
        payload = {
            "id": len(self.notifications) + 1,
            "message": message,
            "type": level,
            "notification_type": notification_type,
            "timestamp": time.time(),
        }
        self.notifications.append(payload)
        return payload

    def dashboard_fallback_snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "orders": [],
            "positions": [],
            "agent_logs": [],
            "prices": {},
            "ic_weights": {},
            "agent_statuses": [
                {
                    "name": name,
                    "status": data.get("status", "unknown"),
                    "last_seen": data.get("last_seen", now),
                }
                for name, data in self.agents.items()
            ],
            "notifications": list(self.notifications[-100:]),
            "mode": "in_memory",
            "db_health": self.last_health,
        }

