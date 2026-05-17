import json
from datetime import datetime, timezone
from typing import Any


def _as_dict(payload: Any) -> dict[str, Any]:
    """Return payload as dict for mixed JSONB/text storage compatibility."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _timestamp_to_iso(value: Any) -> str | None:
    """Normalize DB, memory, and epoch timestamps to an ISO string."""
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
