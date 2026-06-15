from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import AgentStatus, Source


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


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Coerce ``value`` to ``float``; return ``default`` when None or non-numeric.

    Single source of truth for the float-coercion idiom that was copy-pasted
    across half a dozen modules with subtly different defaults. Pass
    ``default=0.0`` for the "fill missing with zero" variant, or rely on the
    ``None`` default for the "no data" variant.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def now_iso() -> str:
    """Current UTC time as a timezone-aware ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: Any) -> datetime | None:
    """Best-effort parse of an ISO-8601 string into a timezone-aware UTC datetime.

    Accepts a trailing ``Z``, coerces non-str input via ``str()``, treats a
    naive datetime as UTC, and returns ``None`` for empty/unparseable input.
    Single source of truth for the
    ``datetime.fromisoformat(s.replace("Z", "+00:00"))`` idiom that was
    copy-pasted across many modules.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_iso_timestamp(value: Any) -> float | None:
    """ISO-8601 string → Unix epoch seconds (UTC). ``None`` for unparseable input."""
    parsed = parse_iso_datetime(value)
    return parsed.timestamp() if parsed is not None else None


def bytes_to_text(raw: Any, encoding: str = "utf-8") -> str:
    """Decode bytes to ``str`` (replacing decode errors); coerce any other value via ``str()``."""
    if isinstance(raw, bytes):
        return raw.decode(encoding, errors="replace")
    return str(raw)


def safe_json_loads(raw: Any, default: Any = None) -> Any:
    """Best-effort ``json.loads`` of a str/bytes value; ``default`` on failure.

    Decodes bytes first. Returns ``default`` (``None`` by default) for ``None``
    input or any decode/parse error (``json.JSONDecodeError`` is a ``ValueError``
    subclass). Callers needing a dict should check ``isinstance(result, dict)``.
    """
    if raw is None:
        return default
    try:
        return json.loads(bytes_to_text(raw))
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``value`` into the inclusive ``[lo, hi]`` range."""
    return max(lo, min(hi, value))


def parse_source(value: str | None) -> Source:
    """Parse a raw source label into a ``Source``; unknown/blank values map to FALLBACK."""
    if not value:
        return Source.FALLBACK
    try:
        return Source(str(value).strip().lower())
    except ValueError:
        return Source.FALLBACK


def parse_agent_status(value: str | None) -> AgentStatus:
    """Parse a raw status label into an ``AgentStatus``; unknown/blank values map to UNKNOWN."""
    if not value:
        return AgentStatus.UNKNOWN
    try:
        return AgentStatus(str(value).strip().upper())
    except ValueError:
        return AgentStatus.UNKNOWN


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two numeric vectors, truncated to the shorter length.

    Returns ``0.0`` when either vector is empty or has zero magnitude (similarity
    is undefined there). Pure math helper — no domain coupling.
    """
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a, b = a[:n], b[:n]
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
