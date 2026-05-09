from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.runtime_state import get_runtime_store, is_db_available


class DashboardReadService:
    """Shared memory-first dashboard read helpers."""

    def _meta(
        self,
        *,
        source: str,
        memory_record_count: int,
        db_checked: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        memory_has_data = memory_record_count > 0
        payload: dict[str, Any] = {
            "source": source,
            "memory_checked": True,
            "memory_initialized": get_runtime_store() is not None,
            "memory_has_data": memory_has_data,
            "memory_record_count": memory_record_count,
            "memory_last_updated_at": datetime.now(timezone.utc).isoformat(),
            "db_checked": db_checked,
            "db_available": bool(is_db_available()),
        }
        if reason is not None:
            payload["reason"] = reason
        return payload

    def memory_orders(self) -> dict[str, Any]:
        orders = list(reversed(get_runtime_store().orders[-50:]))
        return {
            "orders": orders,
            "meta": self._meta(source="memory", memory_record_count=len(orders), db_checked=False),
        }

    def memory_positions(self) -> dict[str, Any]:
        positions = list(get_runtime_store().positions.values())
        return {
            "positions": positions,
            "meta": self._meta(
                source="memory", memory_record_count=len(positions), db_checked=False
            ),
        }

    def memory_events(self, limit: int) -> dict[str, Any]:
        events = get_runtime_store().get_events(limit=limit)
        return {
            "events": events,
            "meta": self._meta(source="memory", memory_record_count=len(events), db_checked=False),
        }

    def memory_agents(self) -> dict[str, Any]:
        agents = list(get_runtime_store().agents.values())
        return {
            "agents": agents,
            "meta": self._meta(source="memory", memory_record_count=len(agents), db_checked=False),
        }

    def memory_grades(self, limit: int) -> dict[str, Any]:
        grades = get_runtime_store().get_grades(limit=limit)
        return {
            "grades": grades,
            "meta": self._meta(source="memory", memory_record_count=len(grades), db_checked=False),
        }

    def empty(self, key: str, *, db_checked: bool, reason: str) -> dict[str, Any]:
        return {
            key: [],
            "meta": self._meta(
                source="empty", memory_record_count=0, db_checked=db_checked, reason=reason
            ),
        }

    def memory_ic_weights(self) -> dict[str, Any]:
        return {
            "current_weights": {},
            "history": [],
            "meta": self._meta(
                source="empty",
                memory_record_count=0,
                db_checked=False,
                reason="memory_empty_db_unavailable",
            ),
        }
