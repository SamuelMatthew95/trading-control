"""Live Reasoning payload — what the buy/sell LLM is actually running.

Answers the operator's three questions in one place:
  * "what prompt are we using live?"  -> the champion's fully-assembled runtime
    prompt (constitution + node-scoped tools + output contract).
  * "what is the challenger using / how does it differ?" -> each running
    ChallengerAgent's config diff vs the champion, plus any prompt-variant or
    tool-override it carries.
  * "what do the proposals change?" -> the pending proposal content.

Pure read model built from the in-process registries + the existing proposals
helper. Pydantic response models mean there are no payload dict literals here,
so the FieldName guardrail has nothing to enforce on the output side.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from api.constants import (
    REASONING_NODE,
    REASONING_TOOL_MIN_ALPHA,
    TOOL_FLAG_CONFLUENCE_LOADED,
    FieldName,
    ToolPhase,
)
from api.observability import log_structured
from api.services.agents.prompts import DECISION_OUTPUT_CONTRACT, SYSTEM_CONSTITUTION_PROMPT
from api.services.dashboard.control import list_challengers_payload
from api.services.dashboard.proposals import get_learning_proposals_payload
from api.services.prompt_assembly import build_runtime_prompt
from api.services.strategy_registry import get_strategy_registry
from api.services.tool_registry import ToolMetadata, get_tool_registry

# The live reasoning node always has cross-stream confluence loaded (the signal
# carries composite_score), so confluence-gated tools are eligible.
_LIVE_FLAGS = frozenset({TOOL_FLAG_CONFLUENCE_LOADED})


class ToolView(BaseModel):
    name: str
    phase: str
    enabled: bool
    alpha_score: float
    latency_ms: float
    failure_rate: float
    call_count: int


class ChampionView(BaseModel):
    node: str
    strategy_version: int | None
    config: dict[str, Any]
    active_tools: list[ToolView]
    assembled_prompt: str
    constitution: str
    output_contract: str


class ChallengerView(BaseModel):
    challenger_id: str
    fills: int
    max_fills: int
    running: bool
    variant: str | None
    tool_overrides: list[str] | None
    config_diff: dict[str, Any]
    differs_by: str


class ProposalView(BaseModel):
    id: str
    proposal_type: str
    description: str
    confidence: float | None
    status: str
    applied: bool


class PromptOsResponse(BaseModel):
    champion: ChampionView
    challengers: list[ChallengerView]
    proposals: list[ProposalView]
    tool_count: int
    timestamp: str


def _tool_view(tool: ToolMetadata) -> ToolView:
    return ToolView(
        name=tool.name,
        phase=str(tool.phase),
        enabled=tool.enabled,
        alpha_score=tool.alpha_score,
        latency_ms=tool.latency_ms,
        failure_rate=tool.failure_rate,
        call_count=tool.call_count,
    )


def _live_active_tools() -> list[ToolMetadata]:
    """The perception + memory tools the live reasoning node currently exposes."""
    registry = get_tool_registry()
    tools = registry.select_tools(
        ToolPhase.PERCEPTION,
        available_state_flags=_LIVE_FLAGS,
        min_alpha=REASONING_TOOL_MIN_ALPHA,
    )
    tools += registry.select_tools(
        ToolPhase.MEMORY,
        available_state_flags=_LIVE_FLAGS,
        min_alpha=REASONING_TOOL_MIN_ALPHA,
    )
    return tools


def _build_champion() -> ChampionView:
    active = _live_active_tools()
    live = get_strategy_registry().current_live()
    assembled = (
        build_runtime_prompt(
            node=REASONING_NODE,
            active_tools=active,
            regime="<filled per signal: macro regime>",
            portfolio_summary="<filled per signal: score / momentum / strength>",
            telemetry_summary="<filled per signal: ic factors + similar-trade recalls>",
        )
        + "\n\n"
        + DECISION_OUTPUT_CONTRACT
    )
    return ChampionView(
        node=REASONING_NODE,
        strategy_version=live.version if live else None,
        config=dict(live.config) if live else {},
        active_tools=[_tool_view(t) for t in active],
        assembled_prompt=assembled,
        constitution=SYSTEM_CONSTITUTION_PROMPT,
        output_contract=DECISION_OUTPUT_CONTRACT,
    )


def _challenger_view(raw: dict[str, Any], champion_config: dict[str, Any]) -> ChallengerView:
    config = raw.get(FieldName.CONFIG) or {}
    variant = config.get(FieldName.PROMPT_VARIANT)
    tool_overrides = config.get(FieldName.TOOL_OVERRIDES)
    # The real difference: config keys whose value diverges from the champion's.
    config_diff = {k: v for k, v in config.items() if champion_config.get(k) != v}

    if variant:
        differs_by = "prompt variant"
    elif tool_overrides:
        differs_by = "tool set"
    elif config_diff:
        differs_by = "config params"
    else:
        differs_by = "nothing yet — shadowing champion"

    return ChallengerView(
        challenger_id=str(raw.get(FieldName.CHALLENGER_ID) or ""),
        fills=int(raw.get(FieldName.FILLS) or 0),
        max_fills=int(raw.get(FieldName.MAX_FILLS) or 0),
        running=bool(raw.get(FieldName.RUNNING)),
        variant=str(variant) if variant else None,
        tool_overrides=list(tool_overrides) if isinstance(tool_overrides, list) else None,
        config_diff=config_diff,
        differs_by=differs_by,
    )


def _proposal_view(raw: dict[str, Any]) -> ProposalView:
    content = raw.get(FieldName.CONTENT)
    if isinstance(content, dict):
        description = str(content.get(FieldName.DESCRIPTION) or content.get(FieldName.NOTE) or "")
    else:
        description = str(content or "")
    confidence = raw.get(FieldName.CONFIDENCE)
    return ProposalView(
        id=str(raw.get(FieldName.ID) or ""),
        proposal_type=str(raw.get(FieldName.PROPOSAL_TYPE) or "proposal"),
        description=description,
        confidence=float(confidence) if confidence is not None else None,
        status=str(raw.get(FieldName.STATUS) or "pending"),
        applied=bool(raw.get(FieldName.APPLIED, False)),
    )


async def get_prompt_os_payload(agents: list[Any]) -> dict[str, Any]:
    """Assemble the full Reasoning Cockpit snapshot. Never raises."""
    try:
        champion = _build_champion()
        try:
            challengers_raw = (await list_challengers_payload(agents)).get(
                FieldName.CHALLENGERS, []
            )
        except Exception:
            log_structured("warning", "prompt_os_challengers_failed", exc_info=True)
            challengers_raw = []
        challengers = [_challenger_view(c, champion.config) for c in challengers_raw]

        try:
            proposals_raw = (await get_learning_proposals_payload(limit=8)).get(
                FieldName.PROPOSALS, []
            )
        except Exception:
            log_structured("warning", "prompt_os_proposals_failed", exc_info=True)
            proposals_raw = []
        proposals = [_proposal_view(p) for p in proposals_raw]

        return PromptOsResponse(
            champion=champion,
            challengers=challengers,
            proposals=proposals,
            tool_count=len(get_tool_registry().all_tools()),
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
    except Exception:
        log_structured("error", "prompt_os_payload_failed", exc_info=True)
        # Degrade to an empty-but-valid champion so the panel renders calmly.
        empty = ChampionView(
            node=REASONING_NODE,
            strategy_version=None,
            config={},
            active_tools=[],
            assembled_prompt="",
            constitution=SYSTEM_CONSTITUTION_PROMPT,
            output_contract=DECISION_OUTPUT_CONTRACT,
        )
        return PromptOsResponse(
            champion=empty,
            challengers=[],
            proposals=[],
            tool_count=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
