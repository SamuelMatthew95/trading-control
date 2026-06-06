"""Tool Registry + dynamic prompt assembly (Prompt-OS Layers 2-3).

Covers the Runtime Tool Governance directive: node-scoped tool visibility,
state-flag gating, alpha/latency/failure telemetry, dead-tool suppression, and
that the assembled prompt exposes ONLY the eligible tools beneath the immutable
constitution.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from api.constants import ToolPhase
from api.main import app
from api.services.agents.prompts import SYSTEM_CONSTITUTION_PROMPT
from api.services.prompt_assembly import build_node_prompt, build_runtime_prompt
from api.services.tool_registry import (
    ToolMetadata,
    ToolRegistry,
    default_tools,
    get_tool_registry,
    set_tool_registry,
)


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_many(default_tools())
    set_tool_registry(reg)
    yield reg
    set_tool_registry(None)  # reset singleton for the next test


def test_select_tools_is_phase_scoped(registry: ToolRegistry):
    perception = {t.name for t in registry.select_tools(ToolPhase.PERCEPTION)}
    assert "get_stream_confluence_metrics" in perception
    # Execution tools must NOT leak into the perception node.
    assert "execute_bracket_order" not in perception


def test_state_flags_gate_execution_tools(registry: ToolRegistry):
    # Without risk_approved, the gated execution tool is hidden.
    without = {t.name for t in registry.select_tools(ToolPhase.EXECUTION)}
    assert "calculate_vwap_execution" not in without

    # Once risk_approved is set it becomes visible; the bracket order still
    # needs thesis_committed too.
    with_risk = {
        t.name
        for t in registry.select_tools(ToolPhase.EXECUTION, available_state_flags={"risk_approved"})
    }
    assert "calculate_vwap_execution" in with_risk
    assert "execute_bracket_order" not in with_risk

    full = {
        t.name
        for t in registry.select_tools(
            ToolPhase.EXECUTION,
            available_state_flags={"risk_approved", "thesis_committed"},
        )
    }
    assert "execute_bracket_order" in full


def test_select_tools_ranked_by_alpha(registry: ToolRegistry):
    tools = registry.select_tools(ToolPhase.PERCEPTION)
    alphas = [t.alpha_score for t in tools]
    assert alphas == sorted(alphas, reverse=True)


def test_record_call_updates_telemetry():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY))
    reg.record_call("t", latency_ms=50.0, success=True, realized_pnl=10.0)
    tool = reg.get("t")
    assert tool.call_count == 1
    assert tool.success_count == 1
    # First sample seeds the EMA directly.
    assert tool.latency_ms == 50.0
    assert tool.alpha_score == 10.0
    assert tool.failure_rate == 0.0

    reg.record_call("t", latency_ms=150.0, success=False, realized_pnl=-10.0)
    tool = reg.get("t")
    assert tool.call_count == 2
    assert tool.success_count == 1
    assert 0.0 < tool.failure_rate < 1.0  # EMA blended a failure in
    assert tool.latency_ms > 50.0


def test_disable_dead_tools_suppresses_negative_alpha():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="noise", phase=ToolPhase.PERCEPTION, alpha_score=-0.5))
    # Enough negative-alpha calls to be judged.
    for _ in range(25):
        reg.record_call("noise", latency_ms=100.0, success=True, realized_pnl=-0.5)
    disabled = reg.disable_dead_tools(min_calls=20)
    assert "noise" in disabled
    assert reg.get("noise").enabled is False
    # A disabled tool is no longer selectable.
    assert reg.select_tools(ToolPhase.PERCEPTION) == []


def test_capability_graph_exposes_unlocks(registry: ToolRegistry):
    graph = registry.capability_graph()
    assert "calculate_vwap_execution" in graph["get_stream_confluence_metrics"]


def test_build_runtime_prompt_exposes_only_active_tools(registry: ToolRegistry):
    active = registry.select_tools(ToolPhase.PERCEPTION)
    prompt = build_runtime_prompt(
        node="thesis",
        active_tools=active,
        regime="risk_off",
        challenger_variant="prefer mean-reversion",
    )
    # Constitution always first and present.
    assert prompt.startswith(SYSTEM_CONSTITUTION_PROMPT)
    # Challenger variant included but reminded it is subordinate.
    assert "CHALLENGER VARIANT" in prompt
    assert "risk_off" in prompt
    # Only perception tools are listed; an execution tool must not appear.
    assert "get_stream_confluence_metrics" in prompt
    assert "execute_bracket_order" not in prompt


def test_build_node_prompt_uses_registry_selection(registry: ToolRegistry):
    prompt = build_node_prompt(node="execution", phase=ToolPhase.EXECUTION)
    # No state flags → gated execution tools are absent.
    assert "calculate_vwap_execution" not in prompt
    assert "none for this node" in prompt or "AVAILABLE TOOLS" in prompt


@pytest.mark.asyncio
async def test_tools_endpoint_returns_attribution(registry: ToolRegistry):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.get("/dashboard/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    names = [t["name"] for t in body["tools"]]
    assert "calculate_vwap_execution" in names
    assert "get_stream_confluence_metrics" in body["capability_graph"]


def test_record_call_without_pnl_preserves_alpha_prior():
    """Decision-time calls (no realized PnL) update latency/reliability but must
    NOT drag the alpha prior toward zero — outcome attribution comes later."""
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY, alpha_score=0.5))
    reg.record_call("t", latency_ms=20.0, success=True)  # no realized_pnl
    tool = reg.get("t")
    assert tool.call_count == 1
    assert tool.alpha_score == 0.5  # prior untouched
    assert tool.latency_ms == 20.0  # latency telemetry is live
    assert tool.failure_rate == 0.0


def test_suggest_tool_changes_flags_negative_alpha_and_top_performer(registry: ToolRegistry):
    suggestions = registry.suggest_tool_changes()
    by_tool = {(s.tool, s.action) for s in suggestions}
    # Negative-alpha sector scan is suggested for removal from the prompt.
    assert ("scan_sector_correlation", "disable") in by_tool
    # Highest-alpha tool is highlighted to keep at the top of the prompt. Execution
    # mechanics (VWAP/bracket) seed neutral alpha, so the top directional-alpha tool
    # is the perception confluence metric.
    assert ("get_stream_confluence_metrics", "prioritize") in by_tool


def test_suggest_tool_changes_flags_unreliable_tool():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="flaky", phase=ToolPhase.MEMORY, alpha_score=0.3))
    for _ in range(25):
        reg.record_call("flaky", latency_ms=10.0, success=False)
    actions = {(s.tool, s.action) for s in reg.suggest_tool_changes(min_calls=20)}
    assert ("flaky", "disable") in actions


@pytest.mark.asyncio
async def test_tools_endpoint_returns_suggestions(registry: ToolRegistry):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.get("/dashboard/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert "suggestions" in body
    # Seeded catalog always yields at least the negative-alpha disable hint.
    actions = {(s["tool"], s["action"]) for s in body["suggestions"]}
    assert ("scan_sector_correlation", "disable") in actions


def test_get_tool_registry_seeds_defaults():
    set_tool_registry(None)
    reg = get_tool_registry()
    assert reg.get("get_stream_confluence_metrics") is not None
    set_tool_registry(None)


def test_new_perception_tools_registered_and_governable(registry: ToolRegistry):
    """Order-book depth, news sentiment, and cross-asset correlation are seeded
    as perception tools — so they appear in the reasoning prompt and are graded
    / suggested like any other tool."""
    from api.constants import (
        TOOL_CORRELATION_CHECK,
        TOOL_FLAG_CONFLUENCE_LOADED,
        TOOL_NEWS_SENTIMENT,
        TOOL_ORDER_BOOK_DEPTH,
    )

    # Order-book depth + news sentiment are eligible at the perception node.
    perception = {t.name for t in registry.select_tools(ToolPhase.PERCEPTION)}
    assert TOOL_ORDER_BOOK_DEPTH in perception
    assert TOOL_NEWS_SENTIMENT in perception

    # Correlation check is gated on confluence-loaded (cross-asset context).
    assert TOOL_CORRELATION_CHECK not in perception
    gated = {
        t.name
        for t in registry.select_tools(
            ToolPhase.PERCEPTION, available_state_flags={TOOL_FLAG_CONFLUENCE_LOADED}
        )
    }
    assert TOOL_CORRELATION_CHECK in gated

    # Governable: they carry telemetry and appear in the attribution ranking.
    attributed = {t.name for t in registry.attribution()}
    assert {TOOL_ORDER_BOOK_DEPTH, TOOL_NEWS_SENTIMENT, TOOL_CORRELATION_CHECK} <= attributed


# ---------------------------------------------------------------------------
# Durable telemetry — snapshot / restore
# ---------------------------------------------------------------------------


def test_snapshot_and_restore_roundtrip():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY))
    reg.record_call("t", latency_ms=50.0, success=True, realized_pnl=5.0)

    snap = reg.snapshot()

    fresh = ToolRegistry()
    fresh.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY))
    restored = fresh.restore(snap)

    assert restored == 1
    tool = fresh.get("t")
    assert tool.call_count == 1
    assert tool.success_count == 1
    assert tool.alpha_score == 5.0
    assert tool.latency_ms == 50.0


def test_restore_ignores_unknown_tools():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="known", phase=ToolPhase.MEMORY))
    restored = reg.restore({"gone": {"call_count": 9}})
    assert restored == 0
    assert reg.get("known").call_count == 0


def test_restore_preserves_governance_enabled_state():
    reg = ToolRegistry()
    reg.register(ToolMetadata(name="t", phase=ToolPhase.MEMORY, enabled=True))
    reg.restore({"t": {"enabled": False}})
    assert reg.get("t").enabled is False
