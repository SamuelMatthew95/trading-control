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
