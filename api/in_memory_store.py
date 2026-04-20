from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from api.constants import (
    AGENT_CHALLENGER,
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
)

DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    AGENT_SIGNAL: {"status": "idle"},
    AGENT_REASONING: {"status": "idle"},
    AGENT_EXECUTION: {"status": "idle"},
    AGENT_GRADE: {"status": "idle"},
    AGENT_IC_UPDATER: {"status": "idle"},
    AGENT_REFLECTION: {"status": "idle"},
    AGENT_STRATEGY_PROPOSER: {"status": "idle"},
    AGENT_NOTIFICATION: {"status": "idle"},
    AGENT_CHALLENGER: {"status": "idle"},
}


@dataclass(slots=True)
class InMemoryStore:
    """Best-effort runtime fallback when external dependencies are down."""

    agents: dict[str, dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_AGENTS))
    notifications: list[dict[str, Any]] = field(default_factory=list)
    grade_history: list[dict[str, Any]] = field(default_factory=list)
    event_history: list[dict[str, Any]] = field(default_factory=list)
    vector_memory: list[dict[str, Any]] = field(default_factory=list)
    agent_runs: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
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

    def add_grade(self, grade_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(grade_payload)
        payload.setdefault("timestamp", time.time())
        self.grade_history.append(payload)
        if len(self.grade_history) > 500:
            self.grade_history = self.grade_history[-500:]
        return payload

    def get_grades(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self.grade_history[-safe_limit:]))

    def add_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event_payload)
        payload.setdefault("timestamp", time.time())
        self.event_history.append(payload)
        if len(self.event_history) > 1000:
            self.event_history = self.event_history[-1000:]
        return payload

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self.event_history[-safe_limit:]))

    def add_vector_memory(self, memory_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(memory_payload)
        payload.setdefault("created_at", time.time())
        self.vector_memory.append(payload)
        if len(self.vector_memory) > 1000:
            self.vector_memory = self.vector_memory[-1000:]
        return payload

    def add_agent_run(self, run_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(run_payload)
        payload.setdefault("created_at", time.time())
        self.agent_runs.append(payload)
        if len(self.agent_runs) > 500:
            self.agent_runs = self.agent_runs[-500:]
        return payload

    def add_order(self, order: dict[str, Any]) -> dict[str, Any]:
        payload = dict(order)
        payload.setdefault("created_at", time.time())
        self.orders.append(payload)
        if len(self.orders) > 500:
            self.orders = self.orders[-500:]
        return payload

    def upsert_position(self, symbol: str, position: dict[str, Any]) -> None:
        existing = self.positions.get(symbol, {})
        self.positions[symbol] = {**existing, **position}

    def dashboard_fallback_snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "orders": list(reversed(self.orders[-50:])),
            "positions": [p for p in self.positions.values() if float(p.get("qty", 0)) > 0],
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
            "persistence_mode": "memory",  # Clear indication of deliberate in-memory mode
        }
