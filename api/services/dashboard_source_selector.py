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
            return {
                "market_events": 0,
                "signals": 0,
                "decisions": 0,
                "graded_decisions": 0,
                "agent_logs": len(self.reads.runtime_dashboard_snapshot().get("agent_logs", [])),
                "trade_alerts": 0,
                "source": "memory",
            }
        try:
            payload = await fetch_db()
            payload["source"] = "database"
            return payload
        except Exception:
            return {
                "market_events": 0,
                "signals": 0,
                "decisions": 0,
                "graded_decisions": 0,
                "agent_logs": len(self.reads.runtime_dashboard_snapshot().get("agent_logs", [])),
                "trade_alerts": 0,
                "source": "memory",
            }
