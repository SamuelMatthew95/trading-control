"""Tool Registry read API — feeds the operator UI's tool-attribution panel.

Exposes every registered tool with its live telemetry (alpha attribution,
latency, failure rate, enabled state) plus the capability graph (which tool
unlocks which). Read-only; the registry is mutated by the runtime, not here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.services.tool_registry import ToolMetadata, ToolSuggestion, get_tool_registry

router = APIRouter(prefix="/dashboard", tags=["tools"])


class ToolRegistryResponse(BaseModel):
    tools: list[ToolMetadata]
    capability_graph: dict[str, list[str]]
    suggestions: list[ToolSuggestion]
    count: int


@router.get("/tools", response_model=ToolRegistryResponse)
async def get_tools() -> ToolRegistryResponse:
    registry = get_tool_registry()
    tools = registry.attribution()
    return ToolRegistryResponse(
        tools=tools,
        capability_graph=registry.capability_graph(),
        # Read-only governance advice (which tools to keep/drop from the
        # reasoning prompt) — the operator approves; the registry never
        # self-mutates here.
        suggestions=registry.suggest_tool_changes(),
        count=len(tools),
    )
