"""Observability API for the cognitive trading brain.

``/cognitive/state`` and ``/cognitive/events`` now mirror the LIVE agent pipeline
(decisions, grades, proposals, reflections, the real event stream) via
``api.services.cognitive_live``. The standalone deterministic ``cognitive`` demo
loop is still reachable behind ``?demo=true`` for design/QA, but is no longer the
default — the page reflects real agents.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.services.cognitive_live import build_live_events, build_live_snapshot
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
async def cognitive_state(demo: bool = False) -> dict[str, Any]:
    """The full observability snapshot. Live agent data by default; ``?demo=true``
    returns the deterministic seeded trajectory (design/QA only)."""
    if demo:
        return _get_loop().snapshot()
    return await build_live_snapshot()


@router.get("/events")
async def cognitive_events(limit: int = 300, demo: bool = False) -> list[dict[str, Any]]:
    """The recent event stream — live by default, seeded demo with ``?demo=true``."""
    if demo:
        return _get_loop().stream.snapshot()[-limit:]
    return await build_live_events(limit)


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
