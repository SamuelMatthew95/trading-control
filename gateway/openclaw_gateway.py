"""
Gateway Layer - OpenClaw Runtime Interface
Handles communication between Python agents and OpenClaw runtime
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent.interface import AgentInfo, AgentResult, AgentTask, BaseAgent
from observability.langfuse_client import ObservabilityManager


@dataclass(frozen=True)
class OpenClawConfig:
    """OpenClaw runtime configuration"""

    host: str
    port: int
    api_key: str
    timeout_seconds: int = 30
    max_concurrent_tasks: int = 10
    heartbeat_interval: int = 30


class OpenClawGateway:
    """Gateway between Python agents and OpenClaw runtime"""

    def __init__(self, config: OpenClawConfig, observability: ObservabilityManager):
        self.config = config
        self.observability = observability
        self.registered_agents: Dict[str, BaseAgent] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.agent_metrics: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._heartbeat_task = None

    async def start(self) -> None:
        """Start the gateway and register with OpenClaw"""
        self._running = True

        # Register with OpenClaw runtime
        await self._register_with_opencclaw()

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        print(f"OpenClaw Gateway started on {self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the gateway and cleanup"""
        self._running = False

        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        # Cancel all active tasks
        for task_id, task in self.active_tasks.items():
            if not task.done():
                task.cancel()
                print(f" Cancelled task {task_id}")

        # Unregister from OpenClaw
        await self._unregister_from_opencclaw()

        print(" OpenClaw Gateway stopped")

    async def register_agent(self, agent: BaseAgent) -> str:
        """Register agent with OpenClaw runtime"""
        agent_info = agent.get_agent_info()

        # Register locally
        self.registered_agents[agent.agent_id] = agent

        # Register with OpenClaw
        registration_data = {
            "agent_id": agent_info.agent_id,
            "agent_type": agent_info.agent_type.value,
            "name": agent_info.name,
            "description": agent_info.description,
            "version": agent_info.version,
            "capabilities": agent_info.capabilities,
            "supported_task_types": agent_info.supported_task_types,
            "max_concurrent_tasks": agent_info.max_concurrent_tasks,
            "timeout_seconds": agent_info.timeout_seconds,
            "gateway_host": self.config.host,
            "gateway_port": self.config.port,
        }

        # Register with Mission Control
        await self.observability.register_agent_with_mission_control(registration_data)

        # Initialize metrics
        self.agent_metrics[agent.agent_id] = {
            "registered_at": datetime.now(),
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_execution_time_ms": 0.0,
            "last_activity": datetime.now(),
        }

        print(f" Registered agent {agent.agent_id} with OpenClaw")
        return agent.agent_id

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister agent from OpenClaw runtime"""
        if agent_id not in self.registered_agents:
            return False

        # Cancel any active tasks for this agent
        agent_tasks = [
            task_id
            for task_id, task in self.active_tasks.items()
            if task_id.startswith(f"{agent_id}_")
        ]

        for task_id in agent_tasks:
            task = self.active_tasks.pop(task_id, None)
            if task and not task.done():
                task.cancel()

        # Remove from registry
        del self.registered_agents[agent_id]
        del self.agent_metrics[agent_id]

        print(f" Unregistered agent {agent_id} from OpenClaw")
        return True

    async def execute_task(self, agent_id: str, task: AgentTask) -> AgentResult:
        """Execute task through OpenClaw orchestration"""
        if agent_id not in self.registered_agents:
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output_data=None,
                error_message=f"Agent {agent_id} not found",
                metrics={},
                trace_id=None,
                tokens_used=0,
                cost_usd=0.0,
                execution_time_ms=0.0,
                started_at=datetime.now(),
                completed_at=datetime.now(),
            )

        agent = self.registered_agents[agent_id]

        # Validate task
        if not await agent.validate_task(task):
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output_data=None,
                error_message=f"Invalid task: {task.task_type}",
                metrics={},
                trace_id=None,
                tokens_used=0,
                cost_usd=0.0,
                execution_time_ms=0.0,
                started_at=datetime.now(),
                completed_at=datetime.now(),
            )

        # Check if agent can handle more tasks
        if not agent.can_handle_task(task):
            return AgentResult(
                task_id=task.task_id,
                status="failed",
                output_data=None,
                error_message=f"Agent {agent_id} at capacity",
                metrics={},
                trace_id=None,
                tokens_used=0,
                cost_usd=0.0,
                execution_time_ms=0.0,
                started_at=datetime.now(),
                completed_at=datetime.now(),
            )

        # Execute task with observability
        task_id = f"{agent_id}_{task.task_id}"

        async def execute_with_observability():
            return await self.observability.track_agent_execution(
                agent_id, task, agent.execute_task
            )

        # Create and track task
        task_future = asyncio.create_task(execute_with_observability())
        self.active_tasks[task_id] = task_future

        try:
            result = await task_future

            # Update metrics
            self._update_agent_metrics(agent_id, result)

            return result
        except Exception as e:
            # Create error result
            error_result = AgentResult(
                task_id=task.task_id,
                status="failed",
                output_data=None,
                error_message=str(e),
                metrics={},
                trace_id=None,
                tokens_used=0,
                cost_usd=0.0,
                execution_time_ms=0.0,
                started_at=datetime.now(),
                completed_at=datetime.now(),
            )

            self._update_agent_metrics(agent_id, error_result)
            return error_result
        finally:
            # Clean up task tracking
            self.active_tasks.pop(task_id, None)

    async def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Get agent runtime status"""
        if agent_id not in self.registered_agents:
            return {"error": f"Agent {agent_id} not found"}

        agent = self.registered_agents[agent_id]
        metrics = self.agent_metrics.get(agent_id, {})

        # Count active tasks for this agent
        active_tasks = len(
            [
                task_id
                for task_id in self.active_tasks.keys()
                if task_id.startswith(f"{agent_id}_")
            ]
        )

        return {
            "agent_id": agent_id,
            "status": "active",
            "registered_at": metrics.get("registered_at"),
            "active_tasks": active_tasks,
            "max_concurrent_tasks": agent.get_agent_info().max_concurrent_tasks,
            "tasks_completed": metrics.get("tasks_completed", 0),
            "tasks_failed": metrics.get("tasks_failed", 0),
            "last_activity": metrics.get("last_activity"),
            "gateway_host": self.config.host,
            "gateway_port": self.config.port,
        }

    async def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get status of all registered agents"""
        agents = []
        for agent_id in self.registered_agents:
            status = await self.get_agent_status(agent_id)
            agents.append(status)
        return agents

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task"""
        if task_id not in self.active_tasks:
            return False

        task = self.active_tasks[task_id]
        task.cancel()

        # Wait for cancellation
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Clean up
        self.active_tasks.pop(task_id, None)
        print(f" Cancelled task {task_id}")
        return True

    def _update_agent_metrics(self, agent_id: str, result: AgentResult) -> None:
        """Update agent metrics"""
        if agent_id not in self.agent_metrics:
            return

        metrics = self.agent_metrics[agent_id]
        metrics["last_activity"] = datetime.now()

        if result.status == "completed":
            metrics["tasks_completed"] += 1
        elif result.status == "failed":
            metrics["tasks_failed"] += 1

        metrics["total_execution_time_ms"] += result.execution_time_ms

    async def _register_with_opencclaw(self) -> None:
        """Register gateway with OpenClaw runtime"""
        registration_data = {
            "gateway_id": "python_gateway",
            "gateway_version": "1.0.0",
            "host": self.config.host,
            "port": self.config.port,
            "max_concurrent_tasks": self.config.max_concurrent_tasks,
            "supported_agent_types": list(self.registered_agents.keys()),
            "capabilities": [
                "task_execution",
                "agent_management",
                "observability",
                "metrics_collection",
            ],
        }

        # In real implementation, this would make HTTP calls to OpenClaw
        print(f" Registering with OpenClaw: {registration_data}")

    async def _unregister_from_opencclaw(self) -> None:
        """Unregister gateway from OpenClaw runtime"""
        # In real implementation, this would make HTTP calls to OpenClaw
        print(" Unregistering from OpenClaw")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to OpenClaw"""
        while self._running:
            try:
                heartbeat_data = {
                    "gateway_id": "python_gateway",
                    "status": "active",
                    "timestamp": datetime.now().isoformat(),
                    "registered_agents": len(self.registered_agents),
                    "active_tasks": len(self.active_tasks),
                    "metrics": {
                        "total_tasks_completed": sum(
                            m.get("tasks_completed", 0)
                            for m in self.agent_metrics.values()
                        ),
                        "total_tasks_failed": sum(
                            m.get("tasks_failed", 0)
                            for m in self.agent_metrics.values()
                        ),
                    },
                }

                # In real implementation, this would make HTTP calls to OpenClaw
                print(f" Heartbeat: {heartbeat_data}")

                await asyncio.sleep(self.config.heartbeat_interval)

            except Exception as e:
                print(f" Heartbeat error: {e}")
                await asyncio.sleep(5)  # Wait before retry


class OpenClawFactory:
    """Factory for creating OpenClaw gateway instances"""

    @staticmethod
    def create_gateway(
        config: OpenClawConfig, observability: ObservabilityManager
    ) -> OpenClawGateway:
        """Create OpenClaw gateway instance"""
        return OpenClawGateway(config, observability)


# OpenClaw runtime simulation (for development/testing)
class MockOpenClawRuntime:
    """Mock OpenClaw runtime for testing without actual OpenClaw"""

    def __init__(self):
        self.registered_gateways: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, Dict[str, Any]] = {}

    async def register_gateway(self, gateway_data: Dict[str, Any]) -> str:
        """Register a gateway"""
        gateway_id = gateway_data.get("gateway_id", "unknown")
        self.registered_gateways[gateway_id] = gateway_data
        print(f" Mock OpenClaw: Registered gateway {gateway_id}")
        return gateway_id

    async def submit_task(self, gateway_id: str, task_data: Dict[str, Any]) -> str:
        """Submit a task to a gateway"""
        task_id = f"task_{len(self.tasks)}"
        self.tasks[task_id] = {
            "gateway_id": gateway_id,
            "task_data": task_data,
            "status": "submitted",
            "timestamp": datetime.now().isoformat(),
        }
        print(f" Mock OpenClaw: Submitted task {task_id} to gateway {gateway_id}")
        return task_id

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get task status"""
        return self.tasks.get(task_id, {"error": "Task not found"})

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "cancelled"
            print(f" Mock OpenClaw: Cancelled task {task_id}")
            return True
        return False
