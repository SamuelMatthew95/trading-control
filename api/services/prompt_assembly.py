"""Layer 2 — Dynamic Runtime Prompt Assembly.

The LLM should never see the whole universe at once. At each DAG node we
assemble a prompt from: the immutable constitution (Layer 1), the current node,
ONLY the tools eligible for that node (selected from the Tool Registry), the
market regime, a compressed portfolio summary, and compressed prior telemetry.
A challenger may inject a variant *below* the constitution — never replacing it.

Inputs are pre-compressed strings (the caller owns summarization) plus typed
``ToolMetadata`` objects, so this module reads no payload dicts and stays
FieldName-clean.
"""

from __future__ import annotations

from api.constants import ToolPhase
from api.services.agents.prompts import SYSTEM_CONSTITUTION_PROMPT
from api.services.tool_registry import ToolMetadata, get_tool_registry


def _format_tools(active_tools: list[ToolMetadata]) -> str:
    if not active_tools:
        return "AVAILABLE TOOLS: none for this node — reason from provided state only."
    lines = ["AVAILABLE TOOLS (current node only — never use a tool not listed here):"]
    for tool in active_tools:
        gate = (
            f" [requires: {', '.join(tool.required_state_flags)}]"
            if tool.required_state_flags
            else ""
        )
        lines.append(f"- {tool.name}: {tool.description}{gate}")
    return "\n".join(lines)


def build_runtime_prompt(
    *,
    node: str,
    active_tools: list[ToolMetadata],
    regime: str = "unknown",
    portfolio_summary: str = "",
    telemetry_summary: str = "",
    challenger_variant: str | None = None,
    constitution: str = SYSTEM_CONSTITUTION_PROMPT,
) -> str:
    """Assemble the layered runtime prompt for one DAG node.

    Order is significant: the constitution is always first and authoritative;
    the optional challenger variant sits beneath it (and is reminded that the
    constitution wins on any conflict).
    """
    sections: list[str] = [constitution]

    if challenger_variant:
        sections.append(
            "CHALLENGER VARIANT (experimental — the constitution above overrides any conflict):\n"
            + challenger_variant
        )

    sections.append(f"CURRENT NODE: {node}")
    sections.append(f"MARKET REGIME: {regime}")
    if portfolio_summary:
        sections.append(f"PORTFOLIO STATE:\n{portfolio_summary}")
    if telemetry_summary:
        sections.append(f"RECENT CONTEXT (compressed):\n{telemetry_summary}")
    sections.append(_format_tools(active_tools))

    return "\n\n".join(sections)


def build_node_prompt(
    *,
    node: str,
    phase: ToolPhase,
    available_state_flags: frozenset[str] | set[str] | None = None,
    regime: str = "unknown",
    portfolio_summary: str = "",
    telemetry_summary: str = "",
    challenger_variant: str | None = None,
    max_latency_ms: float | None = None,
) -> str:
    """Convenience: select eligible tools from the registry, then assemble.

    This is the single call a DAG node makes — tool visibility is governed
    centrally by the registry, never hardcoded into the prompt.
    """
    active_tools = get_tool_registry().select_tools(
        phase,
        available_state_flags=available_state_flags,
        max_latency_ms=max_latency_ms,
    )
    return build_runtime_prompt(
        node=node,
        active_tools=active_tools,
        regime=regime,
        portfolio_summary=portfolio_summary,
        telemetry_summary=telemetry_summary,
        challenger_variant=challenger_variant,
    )
