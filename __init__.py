"""
Simple Observability Package - Clean Event Tracking
Easy to maintain observability for OpenClaw system
"""

from simple_observability import (
    AgentObservability,
    EventType,
    ObservabilityEvent,
    OrchestratorObservability,
    SimpleObservability,
    get_agent_observability,
    get_observability,
    get_orchestrator_observability,
)

__all__ = [
    "SimpleObservability",
    "ObservabilityEvent",
    "EventType",
    "AgentObservability",
    "OrchestratorObservability",
    "get_observability",
    "get_agent_observability",
    "get_orchestrator_observability",
]
