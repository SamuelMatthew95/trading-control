"""
Structured Events for Mission Control Communication
Defines the contract between agents and Mission Control
"""

from __future__ import annotations

import os

# Import agent types
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from models import TaskId

from agent.interface import AgentResult, AgentTask, AgentTaskStatus, AgentId
from agent import Agent
from tools import TraceId


class EventStatus(Enum):
    """Event status for Mission Control"""

    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentEvent:
    """Structured event for Mission Control communication"""

    event_id: str
    agent_id: AgentId
    task_id: TaskId
    task_type: str
    status: EventStatus
    decision: Optional[str]
    confidence: float
    summary: str
    tokens_used: int
    cost_usd: float
    langfuse_trace_id: TraceId
    timestamps: Dict[str, datetime] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "event_type": "agent_execution",
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "decision": self.decision,
            "confidence": self.confidence,
            "summary": self.summary,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "langfuse_trace_id": self.langfuse_trace_id,
            "timestamps": {k: v.isoformat() for k, v in self.timestamps.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def create_start_event(
        cls, agent_id: AgentId, task: AgentTask, trace_id: TraceId
    ) -> "AgentEvent":
        """Create a task start event"""
        return AgentEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status=EventStatus.STARTED,
            decision=None,
            confidence=0.0,
            summary=f"Starting task: {task.task_type}",
            tokens_used=0,
            cost_usd=0.0,
            langfuse_trace_id=trace_id,
            timestamps={
                "task_created": task.created_at.isoformat(),
                "task_started": datetime.now().isoformat(),
            },
            metadata={"priority": task.priority, "timeout": task.timeout_seconds},
        )

    @classmethod
    def create_completion_event(
        cls,
        agent_id: AgentId,
        task: AgentTask,
        result: AgentResult,
        trace_id: TraceId,
    ) -> "AgentEvent":
        """Create a task completion event"""
        status_map = {
            "completed": EventStatus.COMPLETED,
            "failed": EventStatus.FAILED,
            "cancelled": EventStatus.CANCELLED,
            "timeout": EventStatus.FAILED,
        }

        status = status_map.get(result.status.value, EventStatus.FAILED)

        confidence = 0.0
        decision = None
        summary = f"Task {result.status.value}"

        # Extract confidence and decision from output data if available
        if result.output_data:
            confidence = result.output_data.get("confidence", 0.0)
            decision = result.output_data.get("decision")
            summary = result.output_data.get("summary", summary)

        return AgentEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            decision=decision,
            confidence=confidence,
            summary=summary,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            langfuse_trace_id=trace_id,
            timestamps={
                "task_created": task.created_at.isoformat(),
                "task_started": result.started_at.isoformat(),
                "task_completed": (
                    result.completed_at.isoformat() if result.completed_at else None
                ),
            },
            metadata={
                "execution_time_ms": result.execution_time_ms,
                "error_message": result.error_message,
            },
        )

    @classmethod
    def create_error_event(
        cls,
        agent_id: AgentId,
        task: AgentTask,
        error: Exception,
        trace_id: TraceId,
    ) -> "AgentEvent":
        """Create an error event"""
        return AgentEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status=EventStatus.FAILED,
            decision=None,
            confidence=0.0,
            summary=f"Task failed: {str(error)}",
            tokens_used=0,
            cost_usd=0.0,
            langfuse_trace_id=trace_id,
            timestamps={
                "task_created": task.created_at.isoformat(),
                "task_started": datetime.now().isoformat(),
                "task_failed": datetime.now().isoformat(),
            },
            metadata={"error_type": type(error).__name__, "error_message": str(error)},
        )

    @classmethod
    def create_registration_event(
        cls, agent_id: AgentId, agent_info: Dict[str, Any]
    ) -> "AgentEvent":
        """Create an agent registration event"""
        return AgentEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id,
            task_id="registration",
            task_type="agent_registration",
            status=EventStatus.COMPLETED,
            decision=None,
            confidence=1.0,
            summary=f"Agent registered: {agent_info.get('name', 'Unknown')}",
            tokens_used=0,
            cost_usd=0.0,
            langfuse_trace_id="registration",
            timestamps={"registration": datetime.now().isoformat()},
            metadata=agent_info,
        )

    @classmethod
    def create_status_update_event(
        cls, agent_id: AgentId, status: Dict[str, Any]
    ) -> "AgentEvent":
        """Create a status update event"""
        return AgentEvent(
            event_id=f"event_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id,
            task_id="status_update",
            task_type="status_update",
            status=EventStatus.COMPLETED,
            decision=None,
            confidence=1.0,
            summary=f"Status updated: {status.get('status', 'unknown')}",
            tokens_used=0,
            cost_usd=0.0,
            langfuse_trace_id="status_update",
            timestamps={"status_updated": datetime.now().isoformat()},
            metadata=status,
        )


class SystemEvent:
    """System-level events for Mission Control"""

    @dataclass(frozen=True)
    class SystemEvent:
        event_id: str
        event_type: str
        status: EventStatus
        message: str
        timestamp: datetime
        metadata: Dict[str, Any] = field(default_factory=dict)

        def to_dict(self) -> Dict[str, Any]:
            return {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "status": self.status.value,
                "message": self.message,
                "timestamp": self.timestamp.isoformat(),
                "metadata": self.metadata,
            }


class EventBatch:
    """Batch of events for efficient transmission"""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.events: List[Union[AgentEvent, SystemEvent]] = []
        self.last_flush = datetime.now()

    def add_event(self, event: Union[AgentEvent, SystemEvent]) -> None:
        """Add event to batch"""
        self.events.append(event)

        # Auto-batch if needed
        if len(self.events) >= self.max_size:
            self.flush_events()

    def flush_events(self) -> List[Union[AgentEvent, SystemEvent]]:
        """Flush all events and return them"""
        events = self.events.copy()
        self.events.clear()
        self.last_flush = datetime.now()
        return events

    def should_flush(self) -> bool:
        """Check if events should be flushed"""
        return (
            len(self.events) >= self.max_size
            or (datetime.now() - self.last_flush).total_seconds() >= 10
        )


class EventValidator:
    """Validator for event data"""

    @staticmethod
    def validate_agent_event(event: AgentEvent) -> bool:
        """Validate agent event data"""
        if not event.event_id:
            return False
        if not event.agent_id:
            return False
        if not event.task_id:
            return False
        if not event.task_type:
            return False
        if not event.status:
            return False
        if not event.langfuse_trace_id:
            return False
        if event.confidence < 0.0 or event.confidence > 1.0:
            return False
        if event.tokens_used < 0:
            return False
        if event.cost_usd < 0.0:
            return False
        return True

    @staticmethod
    def validate_system_event(event: SystemEvent) -> bool:
        """Validate system event data"""
        if not event.event_id:
            return False
        if not event.event_type:
            return False
        if not event.status:
            return False
        if not event.message:
            return False
        return True


class EventSerializer:
    """Serializer for event data"""

    @staticmethod
    def serialize_event(event: Union[AgentEvent, SystemEvent]) -> Dict[str, Any]:
        """Serialize event to dictionary"""
        if isinstance(event, AgentEvent):
            return event.to_dict()
        elif isinstance(event, SystemEvent):
            return event.to_dict()
        else:
            raise ValueError(f"Unknown event type: {type(event)}")

    @staticmethod
    def deserialize_event(data: Dict[str, Any]) -> Union[AgentEvent, SystemEvent]:
        """Deserialize event from dictionary"""
        event_type = data.get("event_type")

        if event_type == "agent_execution":
            return AgentEvent(
                event_id=data["event_id"],
                agent_id=data["agent_id"],
                task_id=data["task_id"],
                task_type=data["task_type"],
                status=EventStatus(data["status"]),
                decision=data.get("decision"),
                confidence=data["confidence"],
                summary=data["summary"],
                tokens_used=data["tokens_used"],
                cost_usd=data["cost_usd"],
                langfuse_trace_id=data["langfuse_trace_id"],
                timestamps={
                    k: datetime.fromisoformat(v)
                    for k, v in data.get("timestamps", {}).items()
                },
                metadata=data.get("metadata", {}),
            )
        elif event_type == "system":
            return SystemEvent(
                event_id=data["event_id"],
                event_type=data["event_type"],
                status=EventStatus(data["status"]),
                message=data["message"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                metadata=data.get("metadata", {}),
            )
        else:
            raise ValueError(f"Unknown event type: {event_type}")


# Event types for categorization
class EventType:
    """Event type constants"""

    AGENT_EXECUTION = "agent_execution"
    AGENT_REGISTRATION = "agent_registration"
    STATUS_UPDATE = "status_update"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    ERROR_OCCURRED = "error_occurred"
    ALERT_TRIGGERED = "alert_triggered"


# Event priority levels
class EventPriority:
    """Event priority for batching"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4
