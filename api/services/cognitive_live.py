"""Live cognitive snapshot — assembles the Cognitive dashboard's data shape from
the REAL agent pipeline instead of the deterministic ``cognitive`` demo loop.

The Cognitive page contract (``frontend/src/types/cognitive.ts``) was modelled on
the standalone ``cognitive`` simulation (4 signal agents news/tech/macro/risk,
weight-based scoring, counterfactuals, drift, governor). The live system has a
different shape — one SignalGenerator, an LLM ReasoningAgent, GradeAgent, etc. —
so this adapter maps what maps cleanly to real sources and returns honest empties
for sim-only analytics (counterfactuals, drift, governor scorecards) that no live
agent produces. Nothing here invents numbers.

Real sources reused:
- decisions   → ``RedisStore.list_decisions`` (ReasoningAgent output)
- grades      → runtime store ``grade_history`` (GradeAgent)
- proposals   → ``dashboard.proposals.list_proposals_payload`` (StrategyProposer)
- events      → runtime store ``event_history`` + decisions
- weights     → IC weights (Redis) via the dashboard learning payload
- roster      → ``ALL_AGENT_NAMES`` + static role descriptors

This module is an API-contract builder: its OUTPUT dict keys follow the sim
snapshot contract (hence it is in ``SQL_BIND_HEAVY_FILES``), while every READ of a
live payload goes through ``FieldName``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.constants import (
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
    FieldName,
)
from api.observability import log_structured
from api.runtime_state import get_runtime_store
from api.services.dashboard.learning import get_ic_weights_payload
from api.services.dashboard.proposals import list_proposals_payload
from api.services.redis_store import get_redis_store

# Static roster descriptors for the live agents (name → role / emits / blurb).
# ``emits`` mirrors the sim contract so the frontend's roster→grade keying still
# works; for live agents that don't emit a signal it is just an identifier.
_ROSTER: list[dict[str, str]] = [
    {
        "name": AGENT_SIGNAL,
        "role": "perception",
        "emits": "signal",
        "description": "Converts market ticks into trading signals.",
    },
    {
        "name": AGENT_REASONING,
        "role": "reasoning",
        "emits": "decision",
        "description": "LLM reasoning over signals + evolving directive → decision.",
    },
    {
        "name": AGENT_EXECUTION,
        "role": "execution",
        "emits": "execution",
        "description": "Routes decisions to the paper broker and records fills.",
    },
    {
        "name": AGENT_GRADE,
        "role": "evaluation",
        "emits": "grade",
        "description": "Scores closed trades on a 4-D rubric and attributes tool alpha.",
    },
    {
        "name": AGENT_IC_UPDATER,
        "role": "weighting",
        "emits": "ic_weights",
        "description": "Recomputes factor weights from realized performance.",
    },
    {
        "name": AGENT_REFLECTION,
        "role": "reflection",
        "emits": "observation",
        "description": "LLM reflection on graded outcomes → hypotheses.",
    },
    {
        "name": AGENT_STRATEGY_PROPOSER,
        "role": "proposer",
        "emits": "proposal",
        "description": "Drafts backtest-backed strategy / prompt proposals.",
    },
    {
        "name": AGENT_NOTIFICATION,
        "role": "notification",
        "emits": "notification",
        "description": "Fans out user-facing notifications for fills and alerts.",
    },
]


def _to_decision_payload(d: dict[str, Any], buy: float, sell: float) -> dict[str, Any]:
    """Map a live ReasoningAgent decision → the sim DecisionPayload shape."""
    return {
        "action": str(d.get(FieldName.ACTION) or "hold"),
        "score": float(d.get(FieldName.CONFIDENCE) or 0.0),
        "breakdown": {},
        "buy_threshold": buy,
        "sell_threshold": sell,
        "trace_id": d.get(FieldName.TRACE_ID),
        "symbol": d.get(FieldName.SYMBOL),
        "reasoning": d.get(FieldName.REASONING_SUMMARY),
    }


def _agent_grades(grades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate raw grade_history rows into per-subject AgentGrade entries."""
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for g in grades:
        subject = str(g.get(FieldName.SUBJECT) or g.get(FieldName.AGENT) or "")
        if not subject:
            continue
        by_subject.setdefault(subject, []).append(g)
    out: list[dict[str, Any]] = []
    for subject, rows in by_subject.items():
        scores = [float(r.get(FieldName.SCORE) or 0.0) for r in rows]
        avg = round(sum(scores) / len(scores), 4) if scores else 0.0
        latest = rows[-1]
        out.append(
            {
                "subject_id": subject,
                "grade": str(latest.get(FieldName.GRADE) or "NR"),
                "score": avg,
                "samples": len(rows),
            }
        )
    return out


def _proposal_entries(raw_proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map dashboard proposals → the sim QueueEntry shape."""
    entries: list[dict[str, Any]] = []
    for p in raw_proposals:
        ptype = str(p.get(FieldName.PROPOSAL_TYPE) or p.get(FieldName.ACTION) or "proposal")
        entries.append(
            {
                "proposal": {
                    "proposal_id": str(p.get(FieldName.ID) or p.get(FieldName.TRACE_ID) or ""),
                    "proposal_type": ptype,
                    "target": str(p.get(FieldName.STRATEGY_NAME) or p.get(FieldName.SYMBOL) or "—"),
                    "old_value": "—",
                    "new_value": "—",
                    "change": None,
                    "reason": str(
                        p.get(FieldName.REASONING_SUMMARY) or p.get(FieldName.BIAS) or ""
                    ),
                    "expected_impact": "",
                    "diff": {},
                },
                "status": str(p.get(FieldName.STATUS) or "pending"),
                "verdict": None,
                "delta": None,
                "pull_request": None,
                "proposal_grade": None,
            }
        )
    return entries


def _build_health(
    *, total_events: int, decisions_made: int, last_decision: str | None, observations: int
) -> dict[str, Any]:
    """Build the CognitiveHealth block inline from live counts (no mutation)."""
    return {
        "event_stream": {"total_events": total_events, "last_seq": 0, "by_type": {}},
        "agents": {},
        "decision": {
            "signals_received": {},
            "decisions_made": decisions_made,
            "executions": 0,
            "last_decision": last_decision,
        },
        "proposal_pipeline": {
            "generated": 0,
            "backtested": 0,
            "approved": 0,
            "rejected": 0,
            "pr_requests": 0,
            "merged": 0,
        },
        "learning": {
            "trades_closed": 0,
            "trades_graded": 0,
            "ungraded": 0,
            "observations": observations,
        },
    }


async def build_live_snapshot(*, trace_limit: int = 20) -> dict[str, Any]:
    """Assemble the Cognitive snapshot from live agent data (best-effort)."""
    store = get_runtime_store()
    redis_store = get_redis_store()

    decisions: list[dict[str, Any]] = []
    if redis_store is not None:
        try:
            decisions = await redis_store.list_decisions(trace_limit)
        except Exception:
            log_structured("warning", "cognitive_live_decisions_failed", exc_info=True)

    grades = store.get_grades(200)
    reflections = store.get_reflections(trace_limit)
    events = store.get_events(trace_limit)

    try:
        weights_payload = await get_ic_weights_payload()
        weights = weights_payload.get(FieldName.WEIGHTS) or weights_payload.get(
            FieldName.IC_WEIGHTS
        )
        weights = weights if isinstance(weights, dict) else {}
    except Exception:
        weights = {}

    try:
        proposals_payload = await list_proposals_payload()
        raw_proposals = proposals_payload.get(FieldName.PROPOSALS) or []
    except Exception:
        raw_proposals = []

    buy_threshold = 0.0
    sell_threshold = 0.0
    decision_payloads = [_to_decision_payload(d, buy_threshold, sell_threshold) for d in decisions]
    agent_grades = _agent_grades(grades)
    observations = [
        {
            "observation": str(r.get(FieldName.SUMMARY) or r.get(FieldName.HYPOTHESIS) or ""),
            "confidence": float(r.get(FieldName.CONFIDENCE) or 0.0),
            "signal": str(r.get(FieldName.SYMBOL) or ""),
            "direction": str(r.get(FieldName.ACTION) or ""),
            "evidence": {},
        }
        for r in reflections
    ]
    traces = [
        {
            "trace_id": d.get(FieldName.TRACE_ID),
            "signals": {"news": None, "tech": None, "macro": None, "risk": None},
            "reasoning": {FieldName.REASONING_SUMMARY: d.get(FieldName.REASONING_SUMMARY)},
            "decision": _to_decision_payload(d, buy_threshold, sell_threshold),
            "risk_gate": None,
            "execution": None,
            "outcome": None,
            "counterfactual": None,
            "grade": None,
            "event_count": 0,
        }
        for d in decisions
        if d.get(FieldName.TRACE_ID)
    ]

    last_decision = str(decisions[0].get(FieldName.ACTION) or "") if decisions else None
    health = _build_health(
        total_events=len(events),
        decisions_made=len(decisions),
        last_decision=last_decision,
        observations=len(observations),
    )

    return {
        "config": {
            "version": 1,
            "weights": weights,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "risk": {},
        },
        "agents_roster": _ROSTER,
        "live_agents": {"news": None, "tech": None, "macro": None, "risk": None},
        "reasoning": decision_payloads,
        "decision": {
            "latest": decision_payloads[0] if decision_payloads else None,
            "recent": decision_payloads,
            "weights": weights,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
        },
        "proposals": _proposal_entries(raw_proposals),
        "challenger": [],
        "learning": {
            "importance": {},
            "agent_grades": agent_grades,
            "observations": observations,
            "trade_grades": [],
            "mean_regret_pct": 0.0,
            "best_action_rate": 0.0,
        },
        "counterfactuals": [],
        "drift": {
            "alerts": [],
            "monitor": {"window": 0, "min_samples": 0, "metrics": {}},
        },
        "evolution": {
            "config_versions": [],
            "proposal_success_rates": {},
            "agent_grades": agent_grades,
        },
        "health": health,
        "traces": traces,
        "event_count": len(events),
    }


async def build_live_events(limit: int = 200) -> list[dict[str, Any]]:
    """Return the recent real event stream in the sim CognitiveEvent shape."""
    store = get_runtime_store()
    events = store.get_events(limit)
    out: list[dict[str, Any]] = []
    for seq, ev in enumerate(reversed(events)):
        out.append(
            {
                "seq": seq,
                "type": str(ev.get(FieldName.TYPE) or ev.get(FieldName.EVENT_TYPE) or "event"),
                "payload": ev,
                "timestamp": ev.get(FieldName.TIMESTAMP) or datetime.now(timezone.utc).isoformat(),
            }
        )
    return out
