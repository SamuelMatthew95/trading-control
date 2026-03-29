from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from api.config import settings


async def with_retries(operation: Callable[[], Awaitable[Any]]) -> Any:
    last_error: Exception | None = None
    for attempt in range(settings.MAX_RETRIES + 1):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= settings.MAX_RETRIES:
                break
            # Configurable retry backoff - this is allowed
            await asyncio.sleep((settings.RETRY_BACKOFF_MS / 1000) * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Retry flow reached unexpected state")
