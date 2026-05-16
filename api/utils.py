from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
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


def get_str(
    data: Mapping[str, Any] | None,
    key: str,
    default: str | None = None,
    *,
    strip: bool = True,
) -> str | None:
    """Return ``data[key]`` as a string, or ``default`` when missing/None. Pass FieldName keys."""
    if not data:
        return default
    value = data.get(key, default)
    if value is None:
        return default
    text = str(value)
    return text.strip() if strip else text


def get_required_str(
    data: Mapping[str, Any] | None,
    key: str,
    *,
    context: str = "payload",
) -> str:
    """Return a non-empty string for ``key``; raise ``ValueError`` when it is absent or blank."""
    value = get_str(data, key)
    if not value:
        raise ValueError(f"missing required key '{key}' in {context}")
    return value


def get_dict(data: Mapping[str, Any] | None, key: str) -> dict[str, Any]:
    """Return ``data[key]`` when it is a dict, else a fresh empty dict."""
    value = data.get(key) if data else None
    return value if isinstance(value, dict) else {}


def get_nested(data: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Return the value at a chain of nested keys, or ``default`` if any level is missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current
