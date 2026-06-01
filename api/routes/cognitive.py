"""Read-only observability API for the cognitive trading brain.

Every endpoint here is a pure read of one :class:`cognitive.loop.CognitiveLoop`
instance whose state lives entirely on its event stream — so the UI is a mirror
of the stream, never a second source of truth. There are no mutation endpoints
besides ``/reseed`` (which rebuilds the deterministic demo trajectory); behaviour
changes only ever happen through the GitOps PR path, never through this API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cognitive.demo import build_seeded_loop
from cognitive.loop import CognitiveLoop
from cognitive.trace import build_trace

router = APIRouter(prefix="/cognitive", tags=["cognitive"])

_loop: CognitiveLoop | None = None


def _get_loop() -> CognitiveLoop:
    """Lazily build the (deterministic) demo-seeded loop singleton."""
    global _loop
    if _loop is None:
        _loop = build_seeded_loop()
    return _loop


@router.get("/state")
async def cognitive_state() -> dict[str, Any]:
    """The full 7-tab observability snapshot (the single UI data source)."""
    return _get_loop().snapshot()


@router.get("/events")
async def cognitive_events(limit: int = 300) -> list[dict[str, Any]]:
    """The raw SYSTEM_EVENT_STREAM (most recent ``limit`` events)."""
    return _get_loop().stream.snapshot()[-limit:]


@router.get("/config")
async def cognitive_config() -> dict[str, Any]:
    """The active, Git-versioned config (weights / thresholds / risk limits)."""
    return _get_loop().config.to_dict()


@router.get("/agents")
async def cognitive_agents() -> list[dict[str, str]]:
    """The registered cognitive-agent roster (discovery via the registry)."""
    return _get_loop().registry.describe()


@router.get("/trace/{trace_id}")
async def cognitive_trace(trace_id: str) -> dict[str, Any]:
    """Full agent->decision->execution->grade chain for one trade ('why did we?')."""
    return build_trace(_get_loop().stream, trace_id)


@router.post("/reseed")
async def cognitive_reseed() -> dict[str, Any]:
    """Rebuild the deterministic demo trajectory and return the fresh snapshot."""
    global _loop
    _loop = build_seeded_loop()
    return _loop.snapshot()
