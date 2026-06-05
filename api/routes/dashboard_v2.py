"""
Dashboard API - Clean metrics read layer using MetricsAggregator.

Provides real-time dashboard data without NaN issues.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from api.constants import FieldName
from api.services.dashboard.agent_performance import (
    get_agent_detail_payload,
    get_agent_performance_payload,
)
from api.services.dashboard.agents import (
    get_agent_instances_payload,
    get_agent_metrics_payload,
    get_agents_status_payload,
)
from api.services.dashboard.control import (
    get_debug_state_payload,
    get_kill_switch_payload,
    list_challengers_payload,
    spawn_challenger_payload,
    toggle_kill_switch_payload,
)
from api.services.dashboard.events import (
    get_event_history_payload,
    get_recent_events_payload,
)
from api.services.dashboard.flow import get_flow_status_payload, get_order_metrics_payload
from api.services.dashboard.learning import (
    get_grade_history_payload,
    get_ic_weights_payload,
    get_learning_loop_payload,
    get_learning_proposals_payload,
    get_reflections_payload,
    update_proposal_status_payload,
)
from api.services.dashboard.pnl import get_paired_pnl_payload, get_pnl_payload
from api.services.dashboard.prompt_evolution import get_prompt_evolution_payload
from api.services.dashboard.prompt_os import get_prompt_os_payload
from api.services.dashboard.proposals import (
    approve_proposal_payload,
    list_proposals_payload,
    reject_proposal_payload,
)
from api.services.dashboard.state import get_snapshot_payload, get_state_payload
from api.services.dashboard.system import (
    get_prices_payload,
    get_stream_lag_payload,
    get_system_health_payload,
    get_system_stream_metrics_payload,
    get_worker_health_payload,
)
from api.services.dashboard.traces import get_trace_payload
from api.services.dashboard.trading import (
    get_performance_trends_payload,
    get_trade_feed_payload,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Track process start time for startup grace period
PROCESS_START_TIME = datetime.now(timezone.utc)


@router.get("/snapshot")
async def get_dashboard_snapshot() -> dict[str, Any]:
    return await get_snapshot_payload()


@router.get("/state")
async def get_dashboard_state() -> dict[str, Any]:
    return await get_state_payload()


@router.get("/stream-lag")
async def get_stream_lag() -> dict[str, Any]:
    return await get_stream_lag_payload()


@router.get("/system-health")
async def get_system_health() -> dict[str, Any]:
    return await get_system_health_payload()


@router.get("/pnl")
async def get_pnl_metrics() -> dict[str, Any]:
    return await get_pnl_payload()


@router.get("/pnl/paired")
async def get_paired_pnl(request: Request) -> dict[str, Any]:
    redis_client = getattr(request.app.state, "redis_client", None)
    return await get_paired_pnl_payload(redis_client)


@router.get("/agents")
async def get_agent_metrics() -> dict[str, Any]:
    return await get_agent_metrics_payload()


@router.get("/orders")
async def get_order_metrics() -> dict[str, Any]:
    return await get_order_metrics_payload()


@router.get("/flow-status")
async def get_flow_status() -> dict[str, Any]:
    return await get_flow_status_payload()


@router.get("/prices")
async def get_prices() -> dict[str, Any]:
    return await get_prices_payload()


@router.get("/agents/status")
async def get_agents_status() -> dict[str, Any]:
    return await get_agents_status_payload()


@router.get("/agents/performance")
async def get_agent_performance() -> dict[str, Any]:
    """Per-agent grades, tiers, and learnings — the agent scorecard overview."""
    return await get_agent_performance_payload()


@router.get("/agents/{agent_name}/detail")
async def get_agent_detail(agent_name: str) -> dict[str, Any]:
    """Drill-in for one agent: grade, dimensions, learnings, recent activity."""
    payload = await get_agent_detail_payload(agent_name)
    if payload.get(FieldName.ERROR):
        raise HTTPException(status_code=404, detail="unknown_agent") from None
    return payload


@router.get("/system/metrics")
@router.get("/system-metrics")
async def get_system_stream_metrics() -> dict[str, Any]:
    return await get_system_stream_metrics_payload()


@router.get("/events/recent")
async def get_recent_events() -> dict[str, Any]:
    return await get_recent_events_payload()


@router.get("/history/events")
async def get_event_history(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    return await get_event_history_payload(safe_limit)


@router.get("/health/worker")
async def get_worker_health() -> dict[str, Any]:
    return await get_worker_health_payload(PROCESS_START_TIME)


@router.get("/proposals")
async def list_proposals() -> dict[str, Any]:
    return await list_proposals_payload()


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> dict[str, Any]:
    return await approve_proposal_payload(proposal_id)


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> dict[str, Any]:
    return await reject_proposal_payload(proposal_id)


@router.get("/learning/proposals")
async def get_proposals(limit: int = 50) -> dict[str, Any]:
    return await get_learning_proposals_payload(limit)


@router.get("/learning/grades")
async def get_grade_history(limit: int = 50) -> dict[str, Any]:
    return await get_grade_history_payload(limit)


@router.get("/learning/ic-weights")
async def get_ic_weights() -> dict[str, Any]:
    return await get_ic_weights_payload()


@router.get("/learning/reflections")
async def get_reflections(limit: int = 20) -> dict[str, Any]:
    return await get_reflections_payload(limit)


@router.patch("/learning/proposals/{trace_id}")
async def update_proposal_status(
    trace_id: str, status: str = Body(..., embed=True)
) -> dict[str, Any]:
    return await update_proposal_status_payload(trace_id, status)


@router.get("/learning/loop")
async def get_learning_loop_state() -> dict[str, Any]:
    return await get_learning_loop_payload()


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    return await get_trace_payload(trace_id)


@router.get("/trade-feed")
async def get_trade_feed(limit: int = 50, session_id: str | None = None) -> dict[str, Any]:
    return await get_trade_feed_payload(limit, session_id)


@router.get("/performance-trends")
async def get_performance_trends() -> dict[str, Any]:
    return await get_performance_trends_payload()


@router.get("/agent-instances")
async def get_agent_instances() -> dict[str, Any]:
    return await get_agent_instances_payload()


@router.post("/challengers/spawn")
async def spawn_challenger(
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    event_bus = getattr(request.app.state, "event_bus", None)
    dlq_manager = getattr(request.app.state, "dlq_manager", None)
    agents: list[Any] = getattr(request.app.state, "agents", [])
    if event_bus is None or dlq_manager is None:
        raise HTTPException(status_code=503, detail="Event bus not ready") from None
    return await spawn_challenger_payload(event_bus, dlq_manager, agents, body)


@router.get("/challengers")
async def list_challengers(request: Request) -> dict[str, Any]:
    agents: list[Any] = getattr(request.app.state, "agents", [])
    return await list_challengers_payload(agents)


@router.get("/prompt-os")
async def get_prompt_os(request: Request) -> dict[str, Any]:
    """Live Reasoning: the live prompt + active tools, each challenger's diff
    vs the live strategy, and what the pending proposals change."""
    agents: list[Any] = getattr(request.app.state, "agents", [])
    return await get_prompt_os_payload(agents)


@router.get("/prompt-evolution")
async def get_prompt_evolution() -> dict[str, Any]:
    """The self-evolving reasoning directive: active text + version + full
    history + loop config — so an operator can see how the prompt has evolved."""
    return await get_prompt_evolution_payload()


@router.get("/kill-switch")
async def get_kill_switch() -> dict[str, Any]:
    return await get_kill_switch_payload()


@router.post("/kill-switch")
async def toggle_kill_switch(active: bool = Body(..., embed=True)) -> dict[str, Any]:
    return await toggle_kill_switch_payload(active)


@router.get("/debug/state")
async def get_dashboard_debug_state() -> dict[str, Any]:
    return await get_debug_state_payload()
