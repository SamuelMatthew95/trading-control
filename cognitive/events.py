"""SYSTEM_EVENT_STREAM — the single source of truth for the cognitive brain.

Every subsystem (agents, feature aggregation, the deterministic decision
engine, risk, execution, learning/grading, proposals, challenger, backtest gate,
gitops) emits a structured :class:`Event` onto one ordered, append-only stream.
Nothing computes durable state off-stream: the observability layer is a pure
read of this log, so "what happened" is always fully reconstructable.

Determinism: timestamps are *injected* by the caller (never read from the wall
clock here) and ``seq`` is the append index, so an identical sequence of inputs
produces a byte-identical stream. This is what makes the whole brain
reproducible — a hard requirement of the system.

This package lives outside ``api/`` on purpose (like ``backtest/``): it is the
deterministic decision core, not request-path code, so it is exempt from the
FieldName guardrail ceremony that governs the live service. It depends on no
Redis, no DB, and no network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 fallback
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of StrEnum for Python 3.10 (mirrors api/constants.py)."""


class EventType(StrEnum):
    """Every kind of fact that can appear on the system event stream.

    The values double as the ``"type"`` field of an agent payload, so they match
    the structured-output contracts in the system spec exactly (e.g. a News Agent
    emits ``{"type": "news_signal", ...}``).
    """

    # 1. Market data ingestion
    MARKET_TICK = "market_tick"

    # 2. Multi-agent AI layer (cognitive specialists — advisory only)
    NEWS_SIGNAL = "news_signal"
    TECH_SIGNAL = "tech_signal"
    MACRO_SIGNAL = "macro_signal"
    RISK_SIGNAL = "risk_signal"
    REASONING = "reasoning"

    # 5./6. Feature aggregation + deterministic decision engine
    FEATURES = "features"
    DECISION = "decision"

    # 7./8. Risk engine + execution engine
    RISK_GATE = "risk_gate"
    EXECUTION = "execution"

    # 9. Learning + grading engine
    TRADE_OUTCOME = "trade_outcome"
    ATTRIBUTION = "attribution"
    GRADE = "grade"
    OBSERVATION = "observation"

    # 3./4. Proposal engine + challenger + backtest gate + gitops
    PROPOSAL = "proposal"
    CHALLENGER_VERDICT = "challenger_verdict"
    BACKTEST_RESULT = "backtest_result"
    PR_REQUEST = "pr_request"
    CONFIG_VERSION = "config_version"


@dataclass(frozen=True)
class Event:
    """One immutable fact on the stream.

    ``kind`` (not ``type``) avoids shadowing the builtin in dataclass fields; the
    serialized form re-exposes it as ``"type"`` to match the payload contracts.
    """

    seq: int
    kind: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    source: str = ""
    ts: str = ""  # ISO-8601, injected for determinism

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view; ``kind`` is surfaced as ``type`` for the UI/API."""
        return {
            "seq": self.seq,
            "type": self.kind.value,
            "payload": self.payload,
            "trace_id": self.trace_id,
            "source": self.source,
            "ts": self.ts,
        }


Subscriber = Callable[[Event], None]


class EventStream:
    """Ordered, append-only event log — the binding layer of the whole system.

    Append with :meth:`emit`; read with :meth:`events` / :meth:`latest` /
    :meth:`snapshot`. Subscribers (e.g. a mirror to the live Redis bus) are
    notified synchronously in append order so production wiring stays a pure
    side-effect of the same single write path — there is no second source of
    truth to drift from.
    """

    def __init__(self, max_events: int | None = None) -> None:
        self._events: list[Event] = []
        self._subscribers: list[Subscriber] = []
        self._max_events = max_events
        self._emitted = 0  # monotonic; survives retention eviction
        self._dropped = 0

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    @property
    def dropped(self) -> int:
        """Number of oldest events evicted by the retention cap."""
        return self._dropped

    @property
    def emitted(self) -> int:
        """Total events ever emitted, including any evicted by retention."""
        return self._emitted

    def subscribe(self, subscriber: Subscriber) -> None:
        """Register a sink notified on every future emit (e.g. Redis mirror)."""
        self._subscribers.append(subscriber)

    def emit(
        self,
        kind: EventType,
        payload: dict[str, Any] | None = None,
        *,
        trace_id: str = "",
        source: str = "",
        ts: str = "",
    ) -> Event:
        """Append one event and fan out to subscribers; returns the stored Event.

        ``seq`` is a monotonic counter (not the list index), so it stays stable
        and unique even after the retention cap evicts the oldest events.
        """
        event = Event(
            seq=self._emitted,
            kind=kind,
            payload=dict(payload or {}),
            trace_id=trace_id,
            source=source,
            ts=ts,
        )
        self._emitted += 1
        self._events.append(event)
        if self._max_events is not None and len(self._events) > self._max_events:
            self._events.pop(0)
            self._dropped += 1
        for subscriber in self._subscribers:
            subscriber(event)
        return event

    def events(self, *, kind: EventType | None = None, limit: int | None = None) -> list[Event]:
        """Return events (optionally of one ``kind``), newest-trimmed to ``limit``."""
        items = self._events if kind is None else [e for e in self._events if e.kind == kind]
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return list(items)

    def latest(self, kind: EventType) -> Event | None:
        """Most recent event of ``kind``, or ``None`` if the stream has none."""
        for event in reversed(self._events):
            if event.kind == kind:
                return event
        return None

    def snapshot(self) -> list[dict[str, Any]]:
        """Full JSON-ready mirror of the stream — the read-only UI source."""
        return [event.as_dict() for event in self._events]
