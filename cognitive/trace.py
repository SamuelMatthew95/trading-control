"""TRACE VIEW — reconstruct one trade's full chain from the event stream.

Answers "why did we buy?" without grepping logs, by gathering every event that
shares a ``trace_id`` and laying out the canonical chain:

    agent signals -> reasoning -> decision -> risk -> execution
        -> outcome -> attribution -> grade

Because every subsystem emits onto the single stream with the same trace_id,
this is a pure read — if the chain is complete for a trade, the system is wired
end-to-end for that trade.
"""

from __future__ import annotations

from typing import Any

from cognitive.events import EventStream, EventType


def _latest_payload(events: list[Any], kind: EventType) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.kind == kind:
            return event.payload
    return None


def build_trace(stream: EventStream, trace_id: str) -> dict[str, Any]:
    """Assemble the full decision-to-grade chain for one ``trace_id``."""
    events = [event for event in stream if event.trace_id == trace_id]
    decision = _latest_payload(events, EventType.DECISION)
    return {
        "trace_id": trace_id,
        # Config lineage: which config version (and merged proposal) drove this trade.
        "config_version": (decision or {}).get("config_version"),
        "config_proposal_id": (decision or {}).get("config_proposal_id"),
        "signals": {
            "news": _latest_payload(events, EventType.NEWS_SIGNAL),
            "tech": _latest_payload(events, EventType.TECH_SIGNAL),
            "macro": _latest_payload(events, EventType.MACRO_SIGNAL),
            "risk": _latest_payload(events, EventType.RISK_SIGNAL),
        },
        "features": _latest_payload(events, EventType.FEATURES),
        "reasoning": _latest_payload(events, EventType.REASONING),
        "decision": decision,
        "risk_gate": _latest_payload(events, EventType.RISK_GATE),
        "execution": _latest_payload(events, EventType.EXECUTION),
        "outcome": _latest_payload(events, EventType.TRADE_OUTCOME),
        "attribution": _latest_payload(events, EventType.ATTRIBUTION),
        "grade": _latest_payload(events, EventType.GRADE),
        "event_count": len(events),
    }
