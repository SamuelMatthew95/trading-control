from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from api.runtime_state import is_db_available

T = TypeVar("T")


class DashboardReadSelector:
    async def _resolve(self, reader: Callable[[], Awaitable[T] | T]) -> T:
        result = reader()
        if hasattr(result, "__await__"):
            return await result  # type: ignore[return-value]
        return result

    async def select_resource(
        self,
        *,
        resource_name: str,
        db_source: Callable[[], Awaitable[T] | T],
        runtime_source: Callable[[], Awaitable[T] | T],
        empty_source: Callable[[], T],
        is_empty: Callable[[T], bool] | None = None,
    ) -> T:
        def _is_empty(payload: Any) -> bool:
            if is_empty is not None:
                return is_empty(payload)
            return payload is None

        if is_db_available():
            try:
                db_payload = await self._resolve(db_source)
                if not _is_empty(db_payload):
                    return db_payload
            except Exception:
                pass

        try:
            runtime_payload = await self._resolve(runtime_source)
            if not _is_empty(runtime_payload):
                return runtime_payload
        except Exception:
            pass

        return empty_source()
