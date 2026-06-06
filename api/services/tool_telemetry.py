"""Durable tool-telemetry persistence — load on startup, flush periodically.

The ToolRegistry is an in-process singleton with no backing store, so a redeploy
or restart wipes real usage back to seeded priors — which makes a live system
look like it has "never used" its tools. This module bridges the registry to
Redis (via RedisStore) so call_count / alpha / latency / failure-rate survive
restarts and the dashboard reflects cumulative usage, not a fresh-boot illusion.
"""

from __future__ import annotations

import asyncio

from api.constants import TOOL_TELEMETRY_FLUSH_INTERVAL_SECONDS
from api.observability import log_structured
from api.services.redis_store import get_redis_store
from api.services.tool_registry import get_tool_registry


async def hydrate_tool_registry() -> int:
    """Load persisted telemetry into the live registry. Returns tools restored."""
    store = get_redis_store()
    if store is None:
        return 0
    try:
        snapshot = await store.load_tool_telemetry()
    except Exception:
        log_structured("warning", "tool_telemetry_hydrate_failed", exc_info=True)
        return 0
    if not snapshot:
        return 0
    restored = get_tool_registry().restore(snapshot)
    log_structured("info", "tool_telemetry_hydrated", restored=restored)
    return restored


async def flush_tool_registry() -> None:
    """Persist the live registry telemetry snapshot to Redis (best-effort)."""
    store = get_redis_store()
    if store is None:
        return
    await store.save_tool_telemetry(get_tool_registry().snapshot())


async def tool_telemetry_flush_loop() -> None:
    """Periodically flush tool telemetry so usage survives a restart.

    On cancellation (shutdown) it flushes one last time so the final usage isn't
    lost between the last interval tick and the stop.
    """
    try:
        while True:
            await asyncio.sleep(TOOL_TELEMETRY_FLUSH_INTERVAL_SECONDS)
            try:
                await flush_tool_registry()
            except Exception:
                log_structured("warning", "tool_telemetry_flush_failed", exc_info=True)
    except asyncio.CancelledError:
        try:
            await flush_tool_registry()
        except Exception:
            log_structured("warning", "tool_telemetry_final_flush_failed", exc_info=True)
        raise
