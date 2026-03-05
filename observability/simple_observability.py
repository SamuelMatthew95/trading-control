"""
Simple Observability - Clean Event Tracking for OpenClaw
Easy to maintain and extend with clear data structures
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from logger import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    """Event types for observability"""

    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    SIGNAL_GENERATED = "signal_generated"
    CYCLE_STARTED = "cycle_started"
    CYCLE_COMPLETED = "cycle_completed"
    ERROR_OCCURRED = "error_occurred"


@dataclass(frozen=True)
class ObservabilityEvent:
    """Simple event for tracking"""

    event_id: str
    event_type: EventType
    timestamp: datetime
    source: str  # agent_id, orchestrator, etc.
    data: Dict[str, Any]
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "data": self.data,
            "trace_id": self.trace_id,
        }


class SimpleObservability:
    """Simple observability system for OpenClaw"""

    def __init__(self):
        self.events: List[ObservabilityEvent] = []
        self.max_events = 10000  # Keep last 10k events
        self.event_handlers: List[callable] = []

    def track_event(
        self,
        event_type: EventType,
        source: str,
        data: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> None:
        """Track an event"""
        event = ObservabilityEvent(
            event_id=f"{event_type.value}_{source}_{int(datetime.now().timestamp())}",
            event_type=event_type,
            timestamp=datetime.now(),
            source=source,
            data=data,
            trace_id=trace_id,
        )

        self.events.append(event)

        # Keep only recent events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events :]

        # Log the event
        logger.debug(f"Event: {event_type.value} from {source}")

        # Call handlers
        for handler in self.event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")

    def get_events_by_source(
        self, source: str, limit: int = 100
    ) -> List[ObservabilityEvent]:
        """Get events from a specific source"""
        source_events = [e for e in self.events if e.source == source]
        return source_events[-limit:] if source_events else []

    def get_events_by_type(
        self, event_type: EventType, limit: int = 100
    ) -> List[ObservabilityEvent]:
        """Get events of a specific type"""
        type_events = [e for e in self.events if e.event_type == event_type]
        return type_events[-limit:] if type_events else []

    def get_events_by_trace(self, trace_id: str) -> List[ObservabilityEvent]:
        """Get all events for a specific trace"""
        return [e for e in self.events if e.trace_id == trace_id]

    def get_recent_events(self, limit: int = 100) -> List[ObservabilityEvent]:
        """Get recent events"""
        return self.events[-limit:] if self.events else []

    def get_stats(self) -> Dict[str, Any]:
        """Get observability statistics"""
        event_counts = {}
        for event in self.events:
            event_counts[event.event_type.value] = (
                event_counts.get(event.event_type.value, 0) + 1
            )

        source_counts = {}
        for event in self.events:
            source_counts[event.source] = source_counts.get(event.source, 0) + 1

        return {
            "total_events": len(self.events),
            "event_types": event_counts,
            "sources": source_counts,
            "max_events": self.max_events,
            "handlers": len(self.event_handlers),
        }

    def add_event_handler(self, handler: callable) -> None:
        """Add an event handler"""
        self.event_handlers.append(handler)

    def remove_event_handler(self, handler: callable) -> None:
        """Remove an event handler"""
        if handler in self.event_handlers:
            self.event_handlers.remove(handler)

    def clear_events(self) -> None:
        """Clear all events"""
        self.events.clear()
        logger.info("Observability events cleared")


# ============================================================================
# Agent-Specific Observability
# ============================================================================


class AgentObservability:
    """Observability specific to agents"""

    def __init__(self, observability: SimpleObservability):
        self.obs = observability

    def track_agent_started(self, agent_id: str, task_id: str, task_type: str) -> None:
        """Track agent starting a task"""
        self.obs.track_event(
            EventType.AGENT_STARTED,
            agent_id,
            {"task_id": task_id, "task_type": task_type, "status": "started"},
        )

    def track_agent_completed(
        self,
        agent_id: str,
        task_id: str,
        result: Dict[str, Any],
        execution_time_ms: int,
    ) -> None:
        """Track agent completing a task"""
        self.obs.track_event(
            EventType.AGENT_COMPLETED,
            agent_id,
            {
                "task_id": task_id,
                "result": result,
                "execution_time_ms": execution_time_ms,
                "status": "completed",
            },
        )

    def track_agent_failed(self, agent_id: str, task_id: str, error: str) -> None:
        """Track agent failing a task"""
        self.obs.track_event(
            EventType.AGENT_FAILED,
            agent_id,
            {"task_id": task_id, "error": error, "status": "failed"},
        )


# ============================================================================
# Orchestrator Observability
# ============================================================================


class OrchestratorObservability:
    """Observability specific to orchestrator"""

    def __init__(self, observability: SimpleObservability):
        self.obs = observability

    def track_cycle_started(self, cycle_id: str, symbols: List[str]) -> None:
        """Track orchestration cycle starting"""
        self.obs.track_event(
            EventType.CYCLE_STARTED,
            "orchestrator",
            {"cycle_id": cycle_id, "symbols": symbols, "status": "started"},
            trace_id=cycle_id,
        )

    def track_cycle_completed(
        self, cycle_id: str, signals_generated: int, tasks_executed: int
    ) -> None:
        """Track orchestration cycle completion"""
        self.obs.track_event(
            EventType.CYCLE_COMPLETED,
            "orchestrator",
            {
                "cycle_id": cycle_id,
                "signals_generated": signals_generated,
                "tasks_executed": tasks_executed,
                "status": "completed",
            },
            trace_id=cycle_id,
        )

    def track_signal_generated(self, signal: Dict[str, Any]) -> None:
        """Track signal generation"""
        self.obs.track_event(
            EventType.SIGNAL_GENERATED,
            "orchestrator",
            {"signal": signal, "status": "generated"},
        )


# ============================================================================
# Global Observability Instance
# ============================================================================

# Simple global instance
_observability: Optional[SimpleObservability] = None


def get_observability() -> SimpleObservability:
    """Get global observability instance"""
    global _observability
    if _observability is None:
        _observability = SimpleObservability()
    return _observability


def get_agent_observability() -> AgentObservability:
    """Get agent observability instance"""
    return AgentObservability(get_observability())


def get_orchestrator_observability() -> OrchestratorObservability:
    """Get orchestrator observability instance"""
    return OrchestratorObservability(get_observability())


# ============================================================================
# Simple Event Handlers
# ============================================================================


def console_event_handler(event: ObservabilityEvent) -> None:
    """Simple console event handler"""
    print(f"[{event.timestamp}] {event.event_type.value}: {event.source}")


def file_event_handler(
    event: ObservabilityEvent, file_path: str = "observability.log"
) -> None:
    """Simple file event handler"""
    try:
        with open(file_path, "a") as f:
            f.write(f"{json.dumps(event.to_dict())}\n")
    except Exception as e:
        logger.error(f"Failed to write event to file: {e}")


# Auto-register console handler for debugging
get_observability().add_event_handler(console_event_handler)
