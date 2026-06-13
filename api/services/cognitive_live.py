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
    SOURCE_SIGNAL,
    FieldName,
)
from api.observability import log_structured
from api.runtime_state import get_runtime_store
from api.services.dashboard.learning import get_ic_weights_payload
from api.services.dashboard.prompt_evolution import get_prompt_evolution_payload
from api.services.dashboard.proposals import list_proposals_payload
from api.services.redis_store import get_redis_store

# Map the lowercase agent ``source`` strings written onto grades/events to the
# canonical SCREAMING_SNAKE agent-name constants the roster + health use, so
# grades attach to the right agent card instead of silently dropping.
_SOURCE_TO_AGENT: dict[str, str] = {
    SOURCE_SIGNAL: AGENT_SIGNAL,
    "reasoning_agent": AGENT_REASONING,
    "execution_engine": AGENT_EXECUTION,
    "grade_agent": AGENT_GRADE,
    "ic_updater": AGENT_IC_UPDATER,
    "reflection_agent": AGENT_REFLECTION,
    "strategy_proposer": AGENT_STRATEGY_PROPOSER,
    "notification_agent": AGENT_NOTIFICATION,
}


def _canonical_agent(name: str) -> str:
    """Normalize a grade/event subject or source to a canonical agent name."""
    return _SOURCE_TO_AGENT.get(name, name)


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


def _latest_signal_facets(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Most recent SignalGenerator signal as display facets (real indicators)."""
    for ev in events:  # get_events() is newest-first
        if str(ev.get(FieldName.SOURCE) or "") != SOURCE_SIGNAL:
            continue
        data = ev.get(FieldName.DATA)
        if not isinstance(data, dict):
            continue
        return {
            "action": data.get(FieldName.ACTION),
            "confidence": data.get(FieldName.CONFIDENCE),
            "rsi": data.get(FieldName.RSI),
            "pct": data.get(FieldName.PCT),
            "strength": data.get(FieldName.STRENGTH),
        }
    return None


def _live_activity_by_agent(
    events: list[dict[str, Any]], latest_decision: dict[str, Any] | None
) -> dict[str, dict[str, Any] | None]:
    """Latest real activity per agent (keyed by canonical agent name).

    SignalGenerator → latest signal facets; ReasoningAgent → latest decision.
    Other agents have no compact per-event facet to show → ``None`` (their card
    still shows role + health). Honest: only agents with real activity light up.
    """
    return {
        AGENT_SIGNAL: _latest_signal_facets(events),
        AGENT_REASONING: (
            {
                "action": latest_decision.get(FieldName.ACTION),
                "confidence": latest_decision.get(FieldName.SCORE),
                "symbol": latest_decision.get(FieldName.SYMBOL),
            }
            if latest_decision
            else None
        ),
    }


def _to_float(value: Any) -> float | None:
    """Coerce a live numeric field (often a string like ``"66.75"``) to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_decision_payload(d: dict[str, Any], buy: float, sell: float) -> dict[str, Any]:
    """Map a live ReasoningAgent decision → the DecisionPayload shape.

    Carries the REAL cognition the reasoning agent attaches to every decision —
    confidence, the human ``reasoning_summary``, whether the LLM actually ran
    (``llm_succeeded``) vs a rule-based fallback (``downgrade_reason``), and the
    full ``tools_used`` perception chain — so the dashboard can show *why* the
    brain decided, not an empty weighted breakdown the live system never fills.
    """
    confidence = float(d.get(FieldName.CONFIDENCE) or 0.0)
    return {
        "action": str(d.get(FieldName.ACTION) or "hold"),
        "score": confidence,
        "breakdown": {},
        "buy_threshold": buy,
        "sell_threshold": sell,
        "trace_id": d.get(FieldName.TRACE_ID),
        "symbol": d.get(FieldName.SYMBOL),
        "price": _to_float(d.get(FieldName.PRICE)),
        "confidence": confidence,
        "reasoning": d.get(FieldName.REASONING_SUMMARY),
        "reasoning_summary": d.get(FieldName.REASONING_SUMMARY),
        "llm_succeeded": d.get(FieldName.LLM_SUCCEEDED),
        "downgrade_reason": str(d.get(FieldName.DOWNGRADE_REASON) or ""),
        "tools_used": d.get(FieldName.TOOLS_USED) or [],
    }


def _agent_grades(grades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate raw grade_history rows into per-subject AgentGrade entries."""
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for g in grades:
        raw = str(
            g.get(FieldName.SUBJECT) or g.get(FieldName.AGENT) or g.get(FieldName.SOURCE) or ""
        )
        if not raw:
            continue
        by_subject.setdefault(_canonical_agent(raw), []).append(g)
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


def _score_to_letter(score: float) -> str:
    """Band a 0..1 grade score to a letter grade (display only)."""
    if score >= 0.9:
        return "A"
    if score >= 0.8:
        return "B"
    if score >= 0.7:
        return "C"
    if score >= 0.6:
        return "D"
    return "F"


def _proposal_reason(p: dict[str, Any]) -> str:
    """Best-effort human reason from the proposal payload."""
    content = p.get(FieldName.CONTENT)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, dict):
        reason = content.get(FieldName.REASON) or content.get(FieldName.REASONING_SUMMARY)
        if reason:
            return str(reason)
    return str(p.get(FieldName.REASONING_SUMMARY) or p.get(FieldName.BIAS) or "")


def _proposal_entries(raw_proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map dashboard proposals → the sim QueueEntry shape, carrying the real
    grade, confidence and reason so the Proposals tab shows live suggestions."""
    entries: list[dict[str, Any]] = []
    for p in raw_proposals:
        ptype = str(p.get(FieldName.PROPOSAL_TYPE) or p.get(FieldName.ACTION) or "proposal")
        grade_score = p.get(FieldName.GRADE_SCORE)
        proposal_grade = None
        if isinstance(grade_score, (int, float)):
            proposal_grade = {"grade": _score_to_letter(float(grade_score)), "score": grade_score}
        content = p.get(FieldName.CONTENT) if isinstance(p.get(FieldName.CONTENT), dict) else {}
        entries.append(
            {
                "proposal": {
                    "proposal_id": str(p.get(FieldName.ID) or p.get(FieldName.TRACE_ID) or ""),
                    "proposal_type": ptype,
                    "target": str(
                        p.get(FieldName.STRATEGY_NAME)
                        or content.get(FieldName.PARAMETER)
                        or p.get(FieldName.SYMBOL)
                        or "—"
                    ),
                    "old_value": content.get(FieldName.OLD_VALUE, "—"),
                    "new_value": content.get(FieldName.NEW_VALUE, "—"),
                    "change": None,
                    "reason": _proposal_reason(p),
                    "expected_impact": "",
                    "diff": {},
                },
                "status": str(p.get(FieldName.STATUS) or "pending"),
                "verdict": None,
                "delta": None,
                "pull_request": None,
                "proposal_grade": proposal_grade,
                "confidence": p.get(FieldName.CONFIDENCE),
            }
        )
    return entries


# Ordered list of the live agent identities (drives the health roster).
_AGENT_NAMES_ORDERED = [
    AGENT_SIGNAL,
    AGENT_REASONING,
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_REFLECTION,
    AGENT_STRATEGY_PROPOSER,
    AGENT_NOTIFICATION,
]


def _build_agents_health(
    agent_grades: list[dict[str, Any]], decisions_made: int
) -> dict[str, dict[str, Any]]:
    """Per-agent health derived from real activity (grades + decisions).

    An agent is "healthy" when it has produced grades (or, for the reasoning
    agent, decisions) this session; otherwise "idle". No fabricated status.
    """
    samples_by_agent = {g["subject_id"]: g["samples"] for g in agent_grades}
    health: dict[str, dict[str, Any]] = {}
    for name in _AGENT_NAMES_ORDERED:
        events = int(samples_by_agent.get(name, 0))
        if name == AGENT_REASONING:
            events += decisions_made
        health[name] = {
            "status": "healthy" if events > 0 else "idle",
            "events": events,
            "last_seq": 0,
        }
    return health


def _config_versions_from_prompt(
    prompt_payload: dict[str, Any], weights: dict[str, Any]
) -> list[dict[str, Any]]:
    """Map the real prompt-directive active+history into ConfigVersion entries.

    The active directive is the current config version; prior directives form the
    descending history. Each carries the live factor weights so the Evolution tab
    reflects the actual self-evolving config, not a placeholder.
    """
    active = prompt_payload.get(FieldName.ACTIVE)
    history = prompt_payload.get(FieldName.HISTORY) or []
    versions: list[dict[str, Any]] = []

    def _entry(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": int(record.get(FieldName.VERSION, 0)),
            "config": {
                "version": int(record.get(FieldName.VERSION, 0)),
                "weights": weights,
                "buy_threshold": 0.0,
                "sell_threshold": 0.0,
                "risk": {},
                "rationale": str(record.get(FieldName.RATIONALE) or ""),
            },
            "grade": None,
        }

    if isinstance(active, dict):
        versions.append(_entry(active))
    for record in history:
        if isinstance(record, dict):
            versions.append(_entry(record))
    return versions


def _proposal_success_rates(raw_proposals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-proposal-type accept/total stats from the live proposal log."""
    # ptype -> [attempts, successes]; index-based to avoid a FieldName key read.
    counts: dict[str, list[int]] = {}
    for p in raw_proposals:
        ptype = str(p.get(FieldName.PROPOSAL_TYPE) or "proposal")
        bucket = counts.setdefault(ptype, [0, 0])
        bucket[0] += 1
        if bool(p.get(FieldName.APPLIED)) or str(p.get(FieldName.STATUS)) in {
            "approved",
            "applied",
            "merged",
        }:
            bucket[1] += 1
    return {
        ptype: {
            "attempts": attempts,
            "successes": successes,
            "success_rate": round(successes / attempts, 4) if attempts else 0.0,
        }
        for ptype, (attempts, successes) in counts.items()
    }


def _build_health(
    *,
    total_events: int,
    decisions_made: int,
    last_decision: str | None,
    observations: int,
    agents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the CognitiveHealth block inline from live counts (no mutation)."""
    return {
        "event_stream": {"total_events": total_events, "last_seq": 0, "by_type": {}},
        "agents": agents,
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
    # Wider window so signal facets / event counts reflect real activity, not
    # just the last few rows.
    events = store.get_events(200)

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

    # Real self-evolving prompt directive: version + history drive the "Active
    # Config" card and the Config Evolution list (the live config the reasoning
    # agent actually assembles, not a sim placeholder).
    try:
        prompt_payload = await get_prompt_evolution_payload()
    except Exception:
        prompt_payload = {}
    config_version = int(prompt_payload.get(FieldName.VERSION, 0)) or 1
    config_versions = _config_versions_from_prompt(prompt_payload, weights)

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
        agents=_build_agents_health(agent_grades, len(decisions)),
    )

    return {
        "config": {
            "version": config_version,
            "weights": weights,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "risk": {},
        },
        "agents_roster": _ROSTER,
        "live_agents": _live_activity_by_agent(
            events, decision_payloads[0] if decision_payloads else None
        ),
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
            "config_versions": config_versions,
            "proposal_success_rates": _proposal_success_rates(raw_proposals),
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
