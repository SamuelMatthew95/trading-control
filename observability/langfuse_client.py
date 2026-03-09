"""
Observability Layer - Langfuse Integration and Event Emission
Handles all tracing, evaluation, and Mission Control communication
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from langfuse import Langfuse as LangfuseClientBase
from models import AgentId, TaskId

from agent.interface import AgentResult, AgentTask, AgentTaskStatus
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
    """Structured event for Mission Control"""

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


class LangfuseObservability:
    """Langfuse tracing and evaluation wrapper"""

    def __init__(self, public_key: str, secret_key: str, host: str):
        self.client = LangfuseClientBase(
            public_key=public_key, secret_key=secret_key, host=host
        )
        self.active_traces: Dict[TraceId, Any] = {}

    def create_trace(
        self, agent_id: AgentId, task_type: str, input_data: Dict[str, Any]
    ) -> TraceId:
        """Create Langfuse trace for agent execution"""
        trace_id = f"trace_{agent_id}_{uuid.uuid4().hex[:8]}"

        trace = self.client.trace(
            name=f"{agent_id}_{task_type}",
            input=input_data,
            id=trace_id,
            tags={
                "agent_id": agent_id,
                "task_type": task_type,
                "environment": "production",
            },
        )

        self.active_traces[trace_id] = trace
        return trace_id

    def trace_llm_call(
        self,
        trace_id: TraceId,
        call_name: str,
        model: str,
        input_data: Dict[str, Any],
        output_data: Any,
    ) -> Any:
        """Wrap LLM call with tracing"""
        generation_name = f"{call_name}_{model}"

        span = self.active_traces[trace_id].generation(
            name=generation_name, model=model, input=input_data, output=output_data
        )

        # Log token usage if available
        if hasattr(span, "usage") and span.usage:
            usage = span.usage
            return {
                "output": output_data,
                "tokens_used": usage.input_tokens + usage.output_tokens,
                "model": model,
                "generation_id": span.id,
            }

        return {"output": output_data}

    def complete_trace(self, trace_id: TraceId, result: AgentResult) -> None:
        """Complete Langfuse trace with result data"""
        if trace_id not in self.active_traces:
            return

        trace = self.active_traces[trace_id]

        # Update trace with result
        trace.update(
            output=result.output_data,
            status=(
                "completed" if result.status == AgentTaskStatus.COMPLETED else "failed"
            ),
            usage={
                "input_tokens": result.tokens_used // 2,  # Estimate
                "output_tokens": result.tokens_used // 2,
                "total_tokens": result.tokens_used,
            },
        )

        # Add evaluation if available
        if result.output_data:
            try:
                # Simple quality evaluation based on status and confidence
                quality_score = self._evaluate_result_quality(result)
                trace.update(
                    usage={
                        "input_tokens": result.tokens_used // 2,
                        "output_tokens": result.tokens_used // 2,
                        "total_tokens": result.tokens_used,
                    },
                    score=quality_score,
                )
            except Exception:
                pass  # Evaluation failures shouldn't break tracing

        # Remove from active traces
        del self.active_traces[trace_id]

    def _evaluate_result_quality(self, result: AgentResult) -> float:
        """Simple quality evaluation based on result characteristics"""
        if result.status == AgentTaskStatus.COMPLETED:
            base_score = 0.8
            if result.confidence > 0.8:
                base_score += 0.2
        elif result.status == AgentTaskStatus.FAILED:
            base_score = 0.2
            if result.error_message:
                base_score -= 0.1
        else:
            base_score = 0.5

        # Adjust for execution time (faster is better)
        if result.execution_time_ms < 1000:  # < 1 second
            base_score += 0.1
        elif result.execution_time_ms > 30000:  # > 30 seconds
            base_score -= 0.1

        return max(0.0, min(1.0, base_score))

    def get_trace_url(self, trace_id: TraceId) -> Optional[str]:
        """Get Langfuse trace URL for viewing"""
        try:
            return self.client.get_trace_url(trace_id)
        except Exception:
            return None


class MissionControlClient:
    """Client for Mission Control communication and event emission"""

    def __init__(self, host: str, api_key: str, batch_size: int = 100):
        self.host = host
        self.api_key = api_key
        self.batch_size = batch_size
        self.event_queue: List[AgentEvent] = []
        self.session = None

    async def emit_agent_event(self, event: AgentEvent) -> None:
        """Send structured event to Mission Control"""
        self.event_queue.append(event)

        # Auto-batch events
        if len(self.event_queue) >= self.batch_size:
            await self._flush_events()

    async def _flush_events(self) -> None:
        """Flush event queue to Mission Control"""
        if not self.event_queue:
            return

        try:
            # In a real implementation, this would make HTTP calls
            # For now, we'll just log the events
            for event in self.event_queue:
                print(f"Mission Control Event: {event.to_dict()}")

            self.event_queue.clear()
        except Exception as e:
            print(f"Failed to emit events to Mission Control: {e}")

    async def update_agent_status(
        self, agent_id: AgentId, status: Dict[str, Any]
    ) -> None:
        """Update agent status in Mission Control"""
        # In real implementation, this would make HTTP calls
        print(f"Mission Control Status Update: {agent_id} -> {status}")

    async def get_agent_metrics(self, agent_id: AgentId) -> Dict[str, Any]:
        """Get agent metrics from Mission Control"""
        # In real implementation, this would make HTTP calls
        return {
            "agent_id": agent_id,
            "status": "active",
            "last_seen": datetime.now().isoformat(),
            "mission_control_metrics": {},
        }

    async def register_agent(self, agent_info: Dict[str, Any]) -> str:
        """Register agent with Mission Control"""
        # In real implementation, this would make HTTP calls
        print(f"Mission Control Registration: {agent_info}")
        return agent_info.get("agent_id", "unknown")


class ObservabilityManager:
    """Central manager for all observability components"""

    def __init__(
        self, langfuse_config: Dict[str, str], mission_control_config: Dict[str, str]
    ):
        self.langfuse = LangfuseObservability(
            public_key=langfuse_config["public_key"],
            secret_key=langfuse_config["secret_key"],
            host=langfuse_config["host"],
        )
        self.mission_control = MissionControlClient(
            host=mission_control_config["host"],
            api_key=mission_control_config["api_key"],
            batch_size=int(mission_control_config.get("batch_size", 100)),
        )

    async def track_agent_execution(
        self, agent_id: AgentId, task: AgentTask, execution_func
    ) -> AgentResult:
        """Track complete agent execution with observability"""
        # Create trace
        trace_id = self.langfuse.create_trace(agent_id, task.task_type, task.input_data)

        # Update timestamps
        timestamps = {"task_created": task.created_at, "task_started": datetime.now()}

        # Emit start event
        start_event = AgentEvent(
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
            timestamps=timestamps,
        )
        await self.mission_control.emit_agent_event(start_event)

        try:
            # Execute the task with tracing
            result = await execution_func(task)

            # Update timestamps
            timestamps["task_completed"] = datetime.now()

            # Complete trace
            self.langfuse.complete_trace(trace_id, result)

            # Update result with trace info
            result_with_trace = AgentResult(
                task_id=result.task_id,
                status=result.status,
                output_data=result.output_data,
                error_message=result.error_message,
                metrics=result.metrics,
                trace_id=trace_id,
                tokens_used=result.tokens_used,
                cost_usd=result.cost_usd,
                execution_time_ms=result.execution_time_ms,
                started_at=result.started_at,
                completed_at=datetime.now(),
            )

            # Emit completion event
            completion_event = AgentEvent(
                event_id=f"event_{uuid.uuid4().hex[:8]}",
                agent_id=agent_id,
                task_id=task.task_id,
                task_type=task.task_type,
                status=(
                    EventStatus.COMPLETED
                    if result.status == AgentTaskStatus.COMPLETED
                    else EventStatus.FAILED
                ),
                decision=(
                    result.output_data.get("decision") if result.output_data else None
                ),
                confidence=(
                    result.output_data.get("confidence", 0.0)
                    if result.output_data
                    else 0.0
                ),
                summary=(
                    result.output_data.get("summary", f"Task {result.status.value}")
                    if result.output_data
                    else f"Task {result.status.value}"
                ),
                tokens_used=result.tokens_used,
                cost_usd=result.cost_usd,
                langfuse_trace_id=trace_id,
                timestamps=timestamps,
                metadata=result.metrics,
            )
            await self.mission_control.emit_agent_event(completion_event)

            return result_with_trace

        except Exception as e:
            # Update timestamps
            timestamps["task_failed"] = datetime.now()

            # Complete trace with error
            error_result = AgentResult(
                task_id=task.task_id,
                status=AgentTaskStatus.FAILED,
                output_data=None,
                error_message=str(e),
                metrics={},
                trace_id=trace_id,
                tokens_used=0,
                cost_usd=0.0,
                execution_time_ms=0.0,
                started_at=task.created_at,
                completed_at=datetime.now(),
            )
            self.langfuse.complete_trace(trace_id, error_result)

            # Emit error event
            error_event = AgentEvent(
                event_id=f"event_{uuid.uuid4().hex[:8]}",
                agent_id=agent_id,
                task_id=task.task_id,
                task_type=task.task_type,
                status=EventStatus.FAILED,
                decision=None,
                confidence=0.0,
                summary=f"Task failed: {str(e)}",
                tokens_used=0,
                cost_usd=0.0,
                langfuse_trace_id=trace_id,
                timestamps=timestamps,
                metadata={"error": str(e)},
            )
            await self.mission_control.emit_agent_event(error_event)

            return error_result

    async def register_agent_with_mission_control(
        self, agent_info: Dict[str, Any]
    ) -> str:
        """Register agent with Mission Control"""
        return await self.mission_control.register_agent(agent_info)

    def get_langfuse_trace_url(self, trace_id: TraceId) -> Optional[str]:
        """Get Langfuse trace URL"""
        return self.langfuse.get_trace_url(trace_id)

    async def flush_events(self) -> None:
        """Flush any pending events"""
        await self.mission_control._flush_events()

    def get_active_traces_count(self) -> int:
        """Get count of active Langfuse traces"""
        return len(self.langfuse.active_traces)
