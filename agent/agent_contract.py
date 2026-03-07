"""
Agent Interface - Clean Contract for AI Agent System
Defines the contract between agents and orchestration runtime
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentTaskStatus(Enum):
    """Agent task execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AgentType(Enum):
    """Agent type classification"""

    TECHNICAL_ANALYST = "technical_analyst"
    BUSINESS_ANALYST = "business_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    SUPERVISOR = "supervisor"
    VALIDATOR = "validator"


@dataclass(frozen=True)
class AgentTask:
    """Task definition for agent execution"""

    task_id: str
    task_type: str
    input_data: Dict[str, Any]
    priority: int = 1
    timeout_seconds: int = 300
    scheduled_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_agent: Optional[str] = None
    parent_task_id: Optional[str] = None


@dataclass(frozen=True)
class AgentResult:
    """Result from agent execution"""

    task_id: str
    agent_id: str
    success: bool
    output_data: Dict[str, Any]
    confidence: float
    execution_time_ms: int
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentInfo:
    """Agent information and capabilities"""

    agent_id: str
    agent_type: AgentType
    name: str
    description: str
    version: str
    capabilities: List[str]
    max_concurrent_tasks: int = 1
    current_load: int = 0
    status: str = "active"
    last_activity: Optional[datetime] = None


class BaseAgent(ABC):
    """Base interface for all AI agents"""

    def __init__(self, agent_id: str, agent_type: AgentType, name: str):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.name = name
        self.current_tasks: Dict[str, AgentTask] = {}
        self.task_history: List[AgentResult] = []
        self.status = "idle"
        self.last_activity = datetime.now()

    @abstractmethod
    async def execute_task(self, task: AgentTask) -> AgentResult:
        """Execute a task and return result"""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Get list of supported task types"""
        pass

    @abstractmethod
    def can_handle_task(self, task: AgentTask) -> bool:
        """Check if agent can handle the given task"""
        pass

    async def start_task(self, task: AgentTask) -> None:
        """Start executing a task"""
        self.current_tasks[task.task_id] = task
        self.status = "busy"
        self.last_activity = datetime.now()

    async def complete_task(self, task_id: str, result: AgentResult) -> None:
        """Complete a task and store result"""
        if task_id in self.current_tasks:
            del self.current_tasks[task_id]

        self.task_history.append(result)
        self.status = "idle" if not self.current_tasks else "busy"
        self.last_activity = datetime.now()

    def get_info(self) -> AgentInfo:
        """Get agent information"""
        return AgentInfo(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            name=self.name,
            description=self.__doc__ or "AI Agent",
            version="1.0.0",
            capabilities=self.get_capabilities(),
            max_concurrent_tasks=1,
            current_load=len(self.current_tasks),
            status=self.status,
            last_activity=self.last_activity,
        )

    def get_current_load(self) -> int:
        """Get current task load"""
        return len(self.current_tasks)

    def is_available(self) -> bool:
        """Check if agent is available for new tasks"""
        return self.status == "idle" and len(self.current_tasks) == 0


class AgentFactory:
    """Factory for creating agents"""

    _agent_types: Dict[str, type] = {}

    @classmethod
    def register_agent_type(cls, agent_type: str, agent_class: type) -> None:
        """Register an agent type"""
        cls._agent_types[agent_type] = agent_class

    @classmethod
    def create_agent(
        cls, agent_id: str, agent_type: str, name: str, **kwargs
    ) -> BaseAgent:
        """Create an agent instance"""
        if agent_type not in cls._agent_types:
            raise ValueError(f"Unknown agent type: {agent_type}")

        agent_class = cls._agent_types[agent_type]
        return agent_class(
            agent_id=agent_id, agent_type=AgentType(agent_type), name=name, **kwargs
        )

    @classmethod
    def get_available_types(cls) -> List[str]:
        """Get list of available agent types"""
        return list(cls._agent_types.keys())


# ============================================================================
# Clean Agent Registry for Easy Management
# ============================================================================


class AgentRegistry:
    """Registry for managing agents"""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._agents_by_type: Dict[AgentType, List[str]] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent"""
        self._agents[agent.agent_id] = agent

        if agent.agent_type not in self._agents_by_type:
            self._agents_by_type[agent.agent_type] = []

        if agent.agent_id not in self._agents_by_type[agent.agent_type]:
            self._agents_by_type[agent.agent_type].append(agent.agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister an agent"""
        if agent_id in self._agents:
            agent = self._agents[agent_id]

            # Remove from type mapping
            if agent.agent_type in self._agents_by_type:
                if agent_id in self._agents_by_type[agent.agent_type]:
                    self._agents_by_type[agent.agent_type].remove(agent_id)

                if not self._agents_by_type[agent.agent_type]:
                    del self._agents_by_type[agent.agent_type]

            del self._agents[agent_id]

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        """Get an agent by ID"""
        return self._agents.get(agent_id)

    def get_agents_by_type(self, agent_type: AgentType) -> List[BaseAgent]:
        """Get all agents of a specific type"""
        if agent_type not in self._agents_by_type:
            return []

        return [self._agents[agent_id] for agent_id in self._agents_by_type[agent_type]]

    def get_available_agents(self) -> List[BaseAgent]:
        """Get all available agents"""
        return [agent for agent in self._agents.values() if agent.is_available()]

    def get_all_agents(self) -> List[BaseAgent]:
        """Get all registered agents"""
        return list(self._agents.values())

    def get_agent_count(self) -> int:
        """Get total number of registered agents"""
        return len(self._agents)

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        return {
            "total_agents": len(self._agents),
            "agents_by_type": {
                agent_type.value: len(agents)
                for agent_type, agents in self._agents_by_type.items()
            },
            "available_agents": len(self.get_available_agents()),
            "busy_agents": len(
                [a for a in self._agents.values() if not a.is_available()]
            ),
        }


# Global agent registry instance
agent_registry = AgentRegistry()
