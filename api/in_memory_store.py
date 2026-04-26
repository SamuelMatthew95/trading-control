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
    FieldName,
    LogType,
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
    agent_logs: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    trade_feed: list[dict[str, Any]] = field(default_factory=list)
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

    def add_agent_log(self, log_payload: dict[str, Any]) -> dict[str, Any]:
        """Append one row to the in-memory agent_logs list.

        Surfaces reasoning / grade / reflection messages on the dashboard's
        Agent Thought Stream when Postgres is unavailable.
        """
        payload = dict(log_payload)
        payload.setdefault("timestamp", time.time())
        self.agent_logs.append(payload)
        if len(self.agent_logs) > 500:
            self.agent_logs = self.agent_logs[-500:]
        return payload

    def upsert_trade_fill(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Upsert one row into the in-memory trade_feed list.

        Keyed on execution_trace_id so grade/reflection updates merge into the
        existing row instead of creating duplicates.
        """
        payload = dict(trade)
        payload.setdefault("created_at", time.time())
        key = payload.get(FieldName.EXECUTION_TRACE_ID) or payload.get(FieldName.ORDER_ID)
        if key:
            for i, existing in enumerate(self.trade_feed):
                if (
                    existing.get(FieldName.EXECUTION_TRACE_ID) == key
                    or existing.get(FieldName.ORDER_ID) == key
                ):
                    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
                    self.trade_feed[i] = merged
                    return merged
        self.trade_feed.append(payload)
        if len(self.trade_feed) > 500:
            self.trade_feed = self.trade_feed[-500:]
        return payload

    def dashboard_fallback_snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "orders": list(reversed(self.orders[-50:])),
            "positions": [
                p for p in self.positions.values() if float(p.get(FieldName.QTY, 0) or 0) > 0
            ],
            "agent_logs": list(reversed(self.agent_logs[-50:])),
            "learning_events": list(reversed(self.grade_history[-20:])),
            "proposals": [
                e
                for e in reversed(self.event_history[-100:])
                if e.get(FieldName.LOG_TYPE) == LogType.PROPOSAL
            ][:20],
            "trade_feed": list(reversed(self.trade_feed[-50:])),
            "signals": [],
            "risk_alerts": [],
            "prices": {},
            "ic_weights": {},
            "agent_statuses": [
                {
                    "name": name,
                    "status": data.get(FieldName.STATUS, "unknown"),
                    "last_seen": data.get(FieldName.LAST_SEEN, now),
                    "last_seen_at": data.get("last_seen_at"),
                    "last_event": data.get(FieldName.LAST_EVENT, ""),
                    "event_count": int(data.get(FieldName.EVENT_COUNT, 0) or 0),
                    "source": data.get(FieldName.SOURCE, "in_memory"),
                }
                for name, data in self.agents.items()
            ],
            "notifications": list(self.notifications[-100:]),
            "mode": "in_memory",
            "db_health": self.last_health,
            "persistence_mode": "memory",  # Clear indication of deliberate in-memory mode
        }
