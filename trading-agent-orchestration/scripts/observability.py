"""
Production-Grade Observability System
Trace-based debugging and monitoring for agent workflows
"""

from __future__ import annotations
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid


class TraceLevel(Enum):
    """Trace severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(Enum):
    """Trace event types"""
    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    AGENT_TASK_START = "agent_task_start"
    AGENT_TASK_END = "agent_task_end"
    DECISION_POINT = "decision_point"
    STATE_TRANSITION = "state_transition"
    ERROR_OCCURRED = "error_occurred"
    PERFORMANCE_METRIC = "performance_metric"


@dataclass
class TraceEvent:
    """Individual trace event"""
    event_id: str
    timestamp: datetime
    event_type: EventType
    level: TraceLevel
    workflow_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['level'] = self.level.value
        return result


@dataclass
class WorkflowTrace:
    """Complete workflow trace with all events"""
    workflow_id: str
    correlation_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    events: List[TraceEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_event(self, event: TraceEvent):
        """Add event to trace"""
        self.events.append(event)
    
    def get_events_by_type(self, event_type: EventType) -> List[TraceEvent]:
        """Get events by type"""
        return [e for e in self.events if e.event_type == event_type]
    
    def get_events_by_agent(self, agent_id: str) -> List[TraceEvent]:
        """Get events for specific agent"""
        return [e for e in self.events if e.agent_id == agent_id]
    
    def calculate_duration(self) -> Optional[timedelta]:
        """Calculate workflow duration"""
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['start_time'] = self.start_time.isoformat()
        result['end_time'] = self.end_time.isoformat() if self.end_time else None
        result['events'] = [e.to_dict() for e in self.events]
        return result


class ObservabilitySystem:
    """
    Production-grade observability system
    Provides trace-based debugging and monitoring
    """
    
    def __init__(self, max_traces: int = 10000, max_events_per_trace: int = 1000):
        self.system_id = f"obs_{uuid.uuid4().hex[:8]}"
        self.max_traces = max_traces
        self.max_events_per_trace = max_events_per_trace
        
        # Trace storage
        self.active_traces: Dict[str, WorkflowTrace] = {}
        self.completed_traces: List[WorkflowTrace] = []
        
        # Performance metrics
        self.performance_metrics: Dict[str, Any] = {
            "total_workflows": 0,
            "successful_workflows": 0,
            "failed_workflows": 0,
            "average_duration_ms": 0,
            "agent_performance": {},
            "error_rates": {}
        }
        
        # Event streaming
        self.event_subscribers: List[callable] = []
    
    def start_workflow_trace(self, workflow_id: str, metadata: Dict[str, Any] = None) -> str:
        """Start tracing a workflow"""
        correlation_id = uuid.uuid4().hex
        trace = WorkflowTrace(
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            start_time=datetime.now(),
            metadata=metadata or {}
        )
        
        self.active_traces[workflow_id] = trace
        
        # Add workflow start event
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.WORKFLOW_START,
            level=TraceLevel.INFO,
            payload={"metadata": metadata or {}}
        )
        
        return correlation_id
    
    def end_workflow_trace(self, workflow_id: str, success: bool = True, error: str = None):
        """End workflow tracing"""
        if workflow_id not in self.active_traces:
            return
        
        trace = self.active_traces[workflow_id]
        trace.end_time = datetime.now()
        
        # Add workflow end event
        payload = {"success": success}
        if error:
            payload["error"] = error
        
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.WORKFLOW_END,
            level=TraceLevel.INFO if success else TraceLevel.ERROR,
            payload=payload
        )
        
        # Move to completed traces
        self.completed_traces.append(trace)
        del self.active_traces[workflow_id]
        
        # Update performance metrics
        self._update_performance_metrics(trace)
        
        # Cleanup old traces
        self._cleanup_traces()
    
    def add_trace_event(self, workflow_id: str, event_type: EventType, level: TraceLevel, 
                       agent_id: str = None, task_id: str = None, payload: Dict[str, Any] = None):
        """Add trace event"""
        event = TraceEvent(
            event_id=uuid.uuid4().hex,
            timestamp=datetime.now(),
            event_type=event_type,
            level=level,
            workflow_id=workflow_id,
            agent_id=agent_id,
            task_id=task_id,
            payload=payload or {}
        )
        
        # Add to active trace
        if workflow_id in self.active_traces:
            self.active_traces[workflow_id].add_event(event)
            
            # Enforce event limit per trace
            if len(self.active_traces[workflow_id].events) > self.max_events_per_trace:
                self.active_traces[workflow_id].events.pop(0)
        
        # Stream to subscribers
        self._stream_event(event)
    
    def trace_agent_task(self, workflow_id: str, agent_id: str, task_id: str, 
                         input_data: Dict[str, Any], result: Dict[str, Any] = None, 
                         error: str = None, execution_time_ms: int = None):
        """Trace agent task execution"""
        # Task start event
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.AGENT_TASK_START,
            level=TraceLevel.INFO,
            agent_id=agent_id,
            task_id=task_id,
            payload={
                "input_data": input_data,
                "input_size": len(json.dumps(input_data))
            }
        )
        
        # Task end event
        payload = {
            "execution_time_ms": execution_time_ms,
            "output_size": len(json.dumps(result)) if result else 0
        }
        
        if result:
            payload["result"] = result
        if error:
            payload["error"] = error
        
        level = TraceLevel.INFO if not error else TraceLevel.ERROR
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.AGENT_TASK_END,
            level=level,
            agent_id=agent_id,
            task_id=task_id,
            payload=payload
        )
    
    def trace_decision(self, workflow_id: str, decision: str, reasoning: str, 
                       confidence: float = None, alternatives: List[str] = None):
        """Trace decision point"""
        payload = {
            "decision": decision,
            "reasoning": reasoning
        }
        
        if confidence is not None:
            payload["confidence"] = confidence
        if alternatives:
            payload["alternatives"] = alternatives
        
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.DECISION_POINT,
            level=TraceLevel.INFO,
            payload=payload
        )
    
    def trace_performance_metric(self, workflow_id: str, metric_name: str, value: float, 
                                unit: str = None, tags: Dict[str, str] = None):
        """Trace performance metric"""
        payload = {
            "metric_name": metric_name,
            "value": value
        }
        
        if unit:
            payload["unit"] = unit
        if tags:
            payload["tags"] = tags
        
        self.add_trace_event(
            workflow_id=workflow_id,
            event_type=EventType.PERFORMANCE_METRIC,
            level=TraceLevel.DEBUG,
            payload=payload
        )
    
    def get_workflow_trace(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get complete workflow trace"""
        trace = None
        
        if workflow_id in self.active_traces:
            trace = self.active_traces[workflow_id]
        else:
            trace = next((t for t in self.completed_traces if t.workflow_id == workflow_id), None)
        
        return trace.to_dict() if trace else None
    
    def search_traces(self, workflow_id: str = None, agent_id: str = None, 
                      event_type: EventType = None, level: TraceLevel = None,
                      start_time: datetime = None, end_time: datetime = None,
                      limit: int = 100) -> List[Dict[str, Any]]:
        """Search traces with filters"""
        all_traces = list(self.active_traces.values()) + self.completed_traces
        
        filtered_traces = []
        for trace in all_traces:
            # Filter by workflow ID
            if workflow_id and trace.workflow_id != workflow_id:
                continue
            
            # Filter by time range
            if start_time and trace.start_time < start_time:
                continue
            if end_time and trace.end_time and trace.end_time > end_time:
                continue
            
            # Filter by events
            events = trace.events
            if agent_id:
                events = [e for e in events if e.agent_id == agent_id]
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            if level:
                events = [e for e in events if e.level == level]
            
            if events:  # Only include if has matching events
                trace_dict = trace.to_dict()
                trace_dict['filtered_events'] = [e.to_dict() for e in events]
                filtered_traces.append(trace_dict)
        
        return filtered_traces[:limit]
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get system performance metrics"""
        return self.performance_metrics.copy()
    
    def get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        """Get specific agent performance metrics"""
        return self.performance_metrics.get("agent_performance", {}).get(agent_id, {})
    
    def subscribe_to_events(self, callback: callable):
        """Subscribe to event streaming"""
        self.event_subscribers.append(callback)
    
    def unsubscribe_from_events(self, callback: callable):
        """Unsubscribe from event streaming"""
        if callback in self.event_subscribers:
            self.event_subscribers.remove(callback)
    
    def _stream_event(self, event: TraceEvent):
        """Stream event to subscribers"""
        for callback in self.event_subscribers:
            try:
                callback(event.to_dict())
            except Exception as e:
                # Log error but don't fail the streaming
                print(f"Event streaming error: {e}")
    
    def _update_performance_metrics(self, trace: WorkflowTrace):
        """Update performance metrics"""
        self.performance_metrics["total_workflows"] += 1
        
        if trace.end_time:
            duration = trace.calculate_duration()
            if duration:
                duration_ms = duration.total_seconds() * 1000
                
                # Update average duration
                total = self.performance_metrics["total_workflows"]
                current_avg = self.performance_metrics["average_duration_ms"]
                self.performance_metrics["average_duration_ms"] = (
                    (current_avg * (total - 1) + duration_ms) / total
                )
            
            # Check if workflow was successful
            workflow_end_events = trace.get_events_by_type(EventType.WORKFLOW_END)
            if workflow_end_events:
                success = workflow_end_events[0].payload.get("success", True)
                if success:
                    self.performance_metrics["successful_workflows"] += 1
                else:
                    self.performance_metrics["failed_workflows"] += 1
        
        # Update agent performance
        agent_performance = {}
        for event in trace.events:
            if event.event_type == EventType.AGENT_TASK_END and event.agent_id:
                agent_id = event.agent_id
                if agent_id not in agent_performance:
                    agent_performance[agent_id] = {
                        "total_tasks": 0,
                        "successful_tasks": 0,
                        "failed_tasks": 0,
                        "average_execution_time_ms": 0
                    }
                
                agent_perf = agent_performance[agent_id]
                agent_perf["total_tasks"] += 1
                
                execution_time = event.payload.get("execution_time_ms")
                if execution_time:
                    total = agent_perf["total_tasks"]
                    current_avg = agent_perf["average_execution_time_ms"]
                    agent_perf["average_execution_time_ms"] = (
                        (current_avg * (total - 1) + execution_time) / total
                    )
                
                if event.level == TraceLevel.ERROR:
                    agent_perf["failed_tasks"] += 1
                else:
                    agent_perf["successful_tasks"] += 1
        
        self.performance_metrics["agent_performance"].update(agent_performance)
    
    def _cleanup_traces(self):
        """Cleanup old traces to prevent memory leaks"""
        # Remove oldest completed traces if over limit
        if len(self.completed_traces) > self.max_traces:
            excess = len(self.completed_traces) - self.max_traces
            self.completed_traces = self.completed_traces[excess:]


# Global observability instance
observability_system = ObservabilitySystem()
