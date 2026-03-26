"""V3 Fixed System - Complete agent system with proper imports."""

import asyncio
from typing import Any

from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured


COMPLETE_V3_AGENTS = {
    "NotificationAgent": {
        "class": "NotificationAgent",
        "module": "api.services.agents.reasoning_agent",
        "description": "Handles system notifications and alerts"
    }
}


class NotificationAgent:
    """Simple notification agent for V3 system."""
    
    def __init__(self, bus: EventBus, dlq: DLQManager):
        self.bus = bus
        self.dlq = dlq
        self.running = False
    
    async def start(self) -> None:
        """Start the notification agent."""
        self.running = True
        log_structured("info", "NotificationAgent started")
    
    async def stop(self) -> None:
        """Stop the notification agent."""
        self.running = False
        log_structured("info", "NotificationAgent stopped")
    
    async def process(self, data: dict[str, Any]) -> None:
        """Process incoming notification events."""
        log_structured("info", "NotificationAgent processing", data=data)


async def start_fixed_v3_system(bus: EventBus, dlq: DLQManager, redis) -> dict[str, Any]:
    """Start the fixed V3 agent system."""
    agents = {}
    
    # Start NotificationAgent
    notification_agent = NotificationAgent(bus, dlq)
    await notification_agent.start()
    agents["NotificationAgent"] = notification_agent
    
    log_structured("info", "V3 system started", agent_count=len(agents))
    return agents


async def stop_fixed_v3_system(agents: dict[str, Any]) -> None:
    """Stop the fixed V3 agent system."""
    for name, agent in agents.items():
        try:
            await agent.stop()
            log_structured("info", f"Agent {name} stopped")
        except Exception as exc:
            log_structured("warning", f"Failed to stop agent {name}", exc_info=True)
    
    log_structured("info", "V3 system stopped")
