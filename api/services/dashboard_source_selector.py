from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from api.runtime_state import is_db_available
from api.services.dashboard_read_service import DashboardReadService


class DashboardReadSelector:
    def __init__(self) -> None:
        self.reads = DashboardReadService()

    async def snapshot_or_memory(
        self,
        *,
        fetch_db: Callable[[], Awaitable[dict[str, Any]]],
        runtime_mode_value: str,
        include_mode: bool = False,
    ) -> dict[str, Any]:
        if not is_db_available():
            payload = self.reads.runtime_dashboard_snapshot()
            payload["source"] = "memory"
            if include_mode:
                payload["mode"] = runtime_mode_value
            return payload
        try:
            payload = await fetch_db()
            payload["source"] = "database"
            return payload
        except Exception:
            payload = self.reads.runtime_dashboard_snapshot()
            payload["source"] = "memory"
            payload["degraded_mode"] = True
            payload["degraded_reason"] = "db_unavailable"
            if include_mode:
                payload["mode"] = runtime_mode_value
            return payload

    async def resource_or_memory(
        self,
        *,
        memory_payload: dict[str, Any],
        key: str,
        fetch_db: Callable[[], Awaitable[list[dict[str, Any]]]],
        empty_factory: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        rows = memory_payload.get(key, [])
        if not is_db_available():
            return {"rows": rows, "source": "memory" if rows else "empty"}
        try:
            db_rows = await fetch_db()
            if db_rows:
                return {"rows": db_rows, "source": "database"}
            if rows:
                return {"rows": rows, "source": "memory"}
            return {"rows": empty_factory() if empty_factory else [], "source": "empty"}
        except Exception:
            if rows:
                return {"rows": rows, "source": "memory"}
            return {"rows": empty_factory() if empty_factory else [], "source": "empty"}

    async def prices_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        mem = self.reads.memory_prices()
        mem_prices = mem.get("prices", {})
        if not is_db_available():
            return {
                "prices": mem_prices,
                "source": "memory" if mem_prices else "empty",
                "meta": mem["meta"],
            }
        try:
            db_prices = await fetch_db()
            if db_prices:
                return {"prices": db_prices, "source": "database", "meta": mem["meta"]}
            return {
                "prices": mem_prices,
                "source": "memory" if mem_prices else "empty",
                "meta": mem["meta"],
            }
        except Exception:
            return {
                "prices": mem_prices,
                "source": "memory" if mem_prices else "empty",
                "meta": mem["meta"],
            }

    async def system_metrics_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        if not is_db_available():
            payload = self.reads.runtime_system_metrics_payload()
            payload["source"] = "memory"
            return payload
        try:
            payload = await fetch_db()
            payload["source"] = "database"
            return payload
        except Exception:
            payload = self.reads.runtime_system_metrics_payload()
            payload["source"] = "memory"
            return payload

    async def agents_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        if not is_db_available():
            payload = self.reads.runtime_agents_payload()
            payload["source"] = "memory"
            return payload
        try:
            payload = await fetch_db()
            payload["source"] = "database"
            return payload
        except Exception:
            payload = self.reads.runtime_agents_payload()
            payload["source"] = "memory"
            return payload

    async def agent_runs_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[list[dict[str, Any]]]]
    ) -> dict[str, Any]:
        mem_runs = self.reads.runtime_agents_payload()["runs"]
        if not is_db_available():
            return {"runs": mem_runs, "source": "memory" if mem_runs else "empty"}
        try:
            db_runs = await fetch_db()
            if db_runs:
                return {"runs": db_runs, "source": "database"}
            if mem_runs:
                return {"runs": mem_runs, "source": "memory"}
            return {"runs": [], "source": "empty"}
        except Exception:
            if mem_runs:
                return {"runs": mem_runs, "source": "memory"}
            return {"runs": [], "source": "empty"}

    async def notifications_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[list[dict[str, Any]]]], limit: int = 50
    ) -> dict[str, Any]:
        mem_payload = self.reads.runtime_notifications_payload(limit=limit)
        mem_rows = mem_payload["notifications"]
        if not is_db_available():
            return {
                "notifications": mem_rows,
                "count": len(mem_rows),
                "source": "memory" if mem_rows else "empty",
            }
        try:
            db_rows = await fetch_db()
            if db_rows:
                return {"notifications": db_rows, "count": len(db_rows), "source": "database"}
            if mem_rows:
                return {"notifications": mem_rows, "count": len(mem_rows), "source": "memory"}
            return {**self.reads.empty_notifications_payload(), "source": "empty"}
        except Exception:
            if mem_rows:
                return {"notifications": mem_rows, "count": len(mem_rows), "source": "memory"}
            return {**self.reads.empty_notifications_payload(), "source": "empty"}

    async def learning_grades_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[list[dict[str, Any]]]], limit: int = 50
    ) -> dict[str, Any]:
        mem_payload = self.reads.runtime_learning_grades_payload(limit=limit)
        mem_rows = mem_payload["grades"]
        if not is_db_available():
            return {**mem_payload, "source": "memory" if mem_rows else "empty"}
        try:
            db_rows = await fetch_db()
            if db_rows:
                return {"grades": db_rows, "total": len(db_rows), "source": "database"}
            if mem_rows:
                return {**mem_payload, "source": "memory"}
            return {**self.reads.empty_learning_grades_payload(), "source": "empty"}
        except Exception:
            if mem_rows:
                return {**mem_payload, "source": "memory"}
            return {**self.reads.empty_learning_grades_payload(), "source": "empty"}

    async def ic_weights_or_memory(
        self, *, fetch_db: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        mem_payload = self.reads.runtime_ic_weights_payload()
        mem_has = bool(mem_payload.get("current_weights"))
        if not is_db_available():
            return {**mem_payload, "source": "memory" if mem_has else "empty"}
        try:
            db_payload = await fetch_db()
            if db_payload.get("current_weights") or db_payload.get("history"):
                db_payload["source"] = "database"
                return db_payload
            if mem_has:
                return {**mem_payload, "source": "memory"}
            return {**self.reads.empty_ic_weights_payload(), "source": "empty"}
        except Exception:
            if mem_has:
                return {**mem_payload, "source": "memory"}
            return {**self.reads.empty_ic_weights_payload(), "source": "empty"}
