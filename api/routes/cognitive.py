"""Read-only observability API for the cognitive trading brain.

Every endpoint reflects the LIVE agent pipeline (decisions, grades, proposals,
reflections, the real event stream) via ``api.services.cognitive_live``. The
standalone deterministic ``cognitive`` simulation is no longer served here — the
page shows real agents only, never seeded demo data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.services.cognitive_live import (
    build_live_config,
    build_live_events,
    build_live_snapshot,
    build_live_trace,
    live_roster,
)

router = APIRouter(prefix="/cognitive", tags=["cognitive"])


@router.get("/state")
async def cognitive_state() -> dict[str, Any]:
    """The full live observability snapshot from the real agent pipeline."""
    return await build_live_snapshot()


@router.get("/events")
async def cognitive_events(limit: int = 300) -> list[dict[str, Any]]:
    """The recent real event stream (newest last)."""
    return await build_live_events(limit)


@router.get("/config")
async def cognitive_config() -> dict[str, Any]:
    """The active live config (prompt-directive version + IC weights / thresholds)."""
    return await build_live_config()


@router.get("/agents")
async def cognitive_agents() -> list[dict[str, str]]:
    """The live cognitive-agent roster (name / role / emits / description)."""
    return live_roster()


@router.get("/trace/{trace_id}")
async def cognitive_trace(trace_id: str) -> dict[str, Any]:
    """Full agent->decision->perception chain for one trade ('why did we?')."""
    return await build_live_trace(trace_id)
