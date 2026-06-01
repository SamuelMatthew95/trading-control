"""COGNITIVE HEALTH — wiring dashboard derived purely from the event stream.

Not infrastructure health (CPU/Redis) — *cognitive* health: are the agents
emitting, is the decision pipeline producing decisions, is the proposal pipeline
flowing from generated -> backtested -> approved -> merged, and are all closed
trades graded? Every number here is a pure read of the stream, so the health
view can never disagree with what actually happened.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from cognitive.events import EventStream, EventType

# Agent sources we expect to see emitting (matches cognitive/agents.py + proposal).
_SIGNAL_SOURCES = ("news_agent", "technical_agent", "macro_agent", "risk_agent")


def assess_health(stream: EventStream) -> dict[str, Any]:
    """Summarize cognitive wiring health from the stream alone."""
    events = list(stream)
    by_type: Counter[str] = Counter(event.kind.value for event in events)
    last_seq = events[-1].seq if events else -1

    # --- Agent health: latest emission per agent source ---------------------
    latest_by_source: dict[str, int] = {}
    counts_by_source: Counter[str] = Counter()
    for event in events:
        if event.source:
            counts_by_source[event.source] += 1
            latest_by_source[event.source] = event.seq
    agents = {
        source: {
            "status": "healthy" if counts_by_source.get(source) else "idle",
            "events": counts_by_source.get(source, 0),
            "last_seq": latest_by_source.get(source, -1),
        }
        for source in (*_SIGNAL_SOURCES, "reasoning_agent", "proposal_agent")
    }

    # --- Proposal pipeline funnel ------------------------------------------
    approved = sum(
        1
        for event in events
        if event.kind == EventType.CHALLENGER_VERDICT and event.payload.get("approved") is True
    )
    rejected = sum(
        1
        for event in events
        if event.kind == EventType.CHALLENGER_VERDICT and event.payload.get("approved") is False
    )

    # --- Learning: are all closed trades graded? ---------------------------
    trade_outcomes = by_type.get(EventType.TRADE_OUTCOME.value, 0)
    graded_trades = sum(
        1
        for event in events
        if event.kind == EventType.GRADE and event.payload.get("subject") == "trade"
    )

    last_decision = None
    for event in reversed(events):
        if event.kind == EventType.DECISION:
            last_decision = event.payload.get("action")
            break

    return {
        "event_stream": {
            "total_events": len(events),
            "last_seq": last_seq,
            "by_type": dict(by_type),
        },
        "agents": agents,
        "decision": {
            "signals_received": {
                "news": by_type.get(EventType.NEWS_SIGNAL.value, 0),
                "tech": by_type.get(EventType.TECH_SIGNAL.value, 0),
                "macro": by_type.get(EventType.MACRO_SIGNAL.value, 0),
                "risk": by_type.get(EventType.RISK_SIGNAL.value, 0),
            },
            "decisions_made": by_type.get(EventType.DECISION.value, 0),
            "executions": by_type.get(EventType.EXECUTION.value, 0),
            "last_decision": last_decision,
        },
        "proposal_pipeline": {
            "generated": by_type.get(EventType.PROPOSAL.value, 0),
            "backtested": by_type.get(EventType.BACKTEST_RESULT.value, 0),
            "approved": approved,
            "rejected": rejected,
            "pr_requests": by_type.get(EventType.PR_REQUEST.value, 0),
            "merged": by_type.get(EventType.CONFIG_VERSION.value, 0),
        },
        "backtest": {
            "runs": by_type.get(EventType.BACKTEST_RESULT.value, 0),
        },
        "learning": {
            "trades_closed": trade_outcomes,
            "trades_graded": graded_trades,
            "ungraded": max(0, trade_outcomes - graded_trades),
            "observations": by_type.get(EventType.OBSERVATION.value, 0),
        },
    }
