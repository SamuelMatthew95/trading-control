"""
V3 Event-Driven Agent System - Full Implementation

Implements all 8 agents communicating exclusively via Redis Streams:
1. SignalGenerator → signals stream
2. ReasoningAgent → orders stream  
3. ExecutionAgent → executions stream
4. GradeAgent → agent_grades stream
5. ICUpdater → ic_weights stream
6. ReflectionAgent → reflections stream
7. StrategyProposer → proposals stream
8. HistoryAgent → historical_insights stream
9. NotificationAgent → notifications stream
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis

from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.db import AsyncSessionFactory
from api.core.writer.safe_writer import SafeWriter

logger = logging.getLogger(__name__)


class V3AgentConsumer(BaseStreamConsumer):
    """Base V3 agent consumer with traceability and SafeWriter integration."""

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        stream: str,
        consumer_name: str,
        safe_writer: SafeWriter
    ):
        super().__init__(bus, dlq, stream=stream, group=DEFAULT_GROUP, consumer=consumer_name)
        self.redis = redis_client
        self.safe_writer = safe_writer

    async def publish_event(self, target_stream: str, data: Dict[str, Any]) -> None:
        """Publish event to target stream with v3 schema."""
        event_data = {
            **data,
            "schema_version": "v3",
            "msg_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": self.consumer
        }
        
        await self.bus.publish(target_stream, event_data)
        log_structured(
            "info",
            "event_published",
            stream=target_stream,
            msg_id=event_data["msg_id"],
            trace_id=data.get("trace_id"),
            source=self.consumer
        )

    def extract_trace_id(self, data: Dict[str, Any]) -> str:
        """Extract or generate trace_id for end-to-end tracking."""
        trace_id = data.get("trace_id")
        if not trace_id:
            trace_id = str(uuid.uuid4())
            log_structured(
                "warning",
                "generated_trace_id",
                stream=self.stream,
                msg_id=data.get("msg_id"),
                new_trace_id=trace_id
            )
        return trace_id


class SignalGeneratorAgent(V3AgentConsumer):
    """Agent 1: Generates trading signals from market data."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "market_ticks", "signal-generator", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process market tick and generate signal."""
        trace_id = self.extract_trace_id(data)
        
        # Generate signal logic (simplified)
        signal_data = {
            "trace_id": trace_id,
            "symbol": data.get("symbol"),
            "signal_type": "buy" if data.get("price", 0) > 100 else "sell",
            "confidence": 0.85,
            "strategy_id": "momentum_v1",
            "source": "signal_generator",
            "metadata": {
                "price": data.get("price"),
                "volume": data.get("volume"),
                "timestamp": data.get("timestamp")
            }
        }
        
        # Write signal to database
        await self.safe_writer.write_vector_memory(
            msg_id=data["msg_id"],
            stream=self.stream,
            data={
                **signal_data,
                "content_type": "signal",
                "content": json.dumps(signal_data),
                "embedding": [0.1] * 1536  # Placeholder embedding
            }
        )
        
        # Publish to signals stream
        await self.publish_event("signals", signal_data)


class ReasoningAgent(V3AgentConsumer):
    """Agent 2: Processes signals and creates orders."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "signals", "reasoning-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process signal and create order."""
        trace_id = data.get("trace_id")
        
        # Reasoning logic (simplified)
        order_data = {
            "trace_id": trace_id,
            "strategy_id": data.get("strategy_id"),
            "symbol": data.get("symbol"),
            "side": data.get("signal_type"),
            "order_type": "market",
            "quantity": 100,
            "price": None,  # Market order
            "idempotency_key": f"{data.get('symbol')}_{trace_id}",
            "source": "reasoning_agent",
            "metadata": {
                "signal_confidence": data.get("confidence"),
                "reasoning": "Signal processing complete"
            }
        }
        
        # Write order to database
        await self.safe_writer.write_order(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=order_data
        )
        
        # Create agent run record
        agent_run_data = {
            "trace_id": trace_id,
            "agent_id": str(uuid.uuid4()),
            "run_type": "analysis",
            "input_data": data,
            "output_data": order_data,
            "source": "reasoning_agent",
            "trigger_event": "signal_received"
        }
        
        # Publish to orders stream
        await self.publish_event("orders", order_data)


class ExecutionAgent(V3AgentConsumer):
    """Agent 3: Executes orders and creates executions."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "orders", "execution-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process order and create execution."""
        trace_id = data.get("trace_id")
        
        # Execution logic (simplified - immediate fill)
        execution_data = {
            "trace_id": trace_id,
            "strategy_id": data.get("strategy_id"),
            "symbol": data.get("symbol"),
            "order_id": str(uuid.uuid4()),  # Would be actual order ID
            "filled_quantity": data.get("quantity"),
            "filled_price": 101.50,  # Simulated fill price
            "commission": 0.50,
            "new_quantity": data.get("quantity"),
            "new_avg_cost": 101.50,
            "market_value": data.get("quantity") * 101.50,
            "unrealized_pnl": 0.0,
            "source": "execution_agent",
            "metadata": {
                "execution_time": datetime.now(timezone.utc).isoformat(),
                "exchange": "SIMULATED"
            }
        }
        
        # Write execution to database
        await self.safe_writer.write_execution(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=execution_data
        )
        
        # Publish to executions stream
        await self.publish_event("executions", execution_data)


class GradeAgent(V3AgentConsumer):
    """Agent 4: Grades trade performance."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "trade_performance", "grade-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process trade performance and create grades."""
        trace_id = data.get("trace_id")
        
        # Grade calculation logic (simplified)
        pnl = data.get("pnl", 0)
        score = min(max(pnl * 10, 0), 10)  # Convert PnL to 0-10 score
        
        grade_data = {
            "trace_id": trace_id,
            "agent_id": str(uuid.uuid4()),
            "agent_run_id": str(uuid.uuid4()),
            "grade_type": "overall",
            "score": score,
            "metrics": {
                "pnl": pnl,
                "pnl_percent": data.get("pnl_percent", 0),
                "holding_period": data.get("holding_period_minutes", 0),
                "sharpe_ratio": data.get("sharpe_ratio", 0)
            },
            "feedback": f"Trade scored {score}/10 based on PnL of ${pnl}",
            "source": "grade_agent"
        }
        
        # Write grade to database
        await self.safe_writer.write_agent_grade(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=grade_data
        )
        
        # Publish to agent_grades stream
        await self.publish_event("agent_grades", grade_data)


class ICUpdaterAgent(V3AgentConsumer):
    """Agent 5: Updates Information Coefficient weights."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "trade_performance", "ic-updater", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process trade performance and update IC weights."""
        trace_id = data.get("trace_id")
        
        # IC calculation logic (simplified)
        ic_value = data.get("pnl_percent", 0) / 100.0  # Simple IC proxy
        weight = min(max(ic_value, 0), 1)  # Normalize to 0-1
        
        ic_data = {
            "trace_id": trace_id,
            "factor_name": "momentum",
            "ic_value": ic_value,
            "weight": weight,
            "factor_id": str(uuid.uuid4()),
            "source": "ic_updater",
            "metadata": {
                "trade_id": data.get("trade_id"),
                "calculation_method": "simple_pnl_proxy",
                "update_time": datetime.now(timezone.utc).isoformat()
            }
        }
        
        # Write IC weight to database
        await self.safe_writer.write_ic_weight(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=ic_data
        )
        
        # Publish to ic_weights stream
        await self.publish_event("ic_weights", ic_data)


class ReflectionAgent(V3AgentConsumer):
    """Agent 6: Reflects on performance and generates insights."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "trade_performance", "reflection-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process trade performance and generate reflections."""
        trace_id = data.get("trace_id")
        
        # Reflection logic (simplified)
        pnl = data.get("pnl", 0)
        if pnl > 0:
            insight = f"Profitable trade (${pnl}) indicates strategy working well"
        else:
            insight = f"Losing trade (${pnl}) suggests strategy adjustment needed"
        
        reflection_data = {
            "trace_id": trace_id,
            "agent_id": str(uuid.uuid4()),
            "reflection_type": "trade_analysis",
            "insights": insight,
            "embedding": [0.2] * 1536,  # Placeholder embedding
            "strategy_id": data.get("strategy_id"),
            "source": "reflection_agent",
            "metadata": {
                "trade_id": data.get("trade_id"),
                "reflection_time": datetime.now(timezone.utc).isoformat(),
                "sentiment": "positive" if pnl > 0 else "negative"
            }
        }
        
        # Write reflection to database
        await self.safe_writer.write_reflection_output(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=reflection_data
        )
        
        # Publish to reflections stream
        await self.publish_event("reflections", reflection_data)


class StrategyProposerAgent(V3AgentConsumer):
    """Agent 7: Proposes strategy improvements."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "reflections", "strategy-proposer", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process reflections and propose strategy changes."""
        trace_id = data.get("trace_id")
        
        # Strategy proposal logic (simplified)
        sentiment = data.get("metadata", {}).get("sentiment", "neutral")
        if sentiment == "negative":
            proposal = "Consider reducing position size or adjusting entry criteria"
            proposal_type = "risk_management"
        elif sentiment == "positive":
            proposal = "Consider increasing position size or expanding to similar symbols"
            proposal_type = "scale_up"
        else:
            proposal = "Monitor current strategy parameters"
            proposal_type = "monitor"
        
        proposal_data = {
            "trace_id": trace_id,
            "proposal_type": proposal_type,
            "content": proposal,
            "strategy_id": data.get("strategy_id"),
            "confidence": 0.7,
            "source": "strategy_proposer",
            "metadata": {
                "based_on_reflection": data.get("insights"),
                "proposal_time": datetime.now(timezone.utc).isoformat(),
                "implementation_priority": "medium"
            }
        }
        
        # Write proposal to database
        await self.safe_writer.write_strategy_proposal(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=proposal_data
        )
        
        # Publish to proposals stream
        await self.publish_event("proposals", proposal_data)


class HistoryAgent(V3AgentConsumer):
    """Agent 8: Analyzes historical patterns and provides insights."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "trade_performance", "history-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process trade performance and generate historical insights."""
        trace_id = data.get("trace_id")
        
        # Historical analysis logic (simplified)
        symbol = data.get("symbol")
        insight = f"Historical pattern for {symbol}: similar trades show {data.get('pnl_percent', 0):.2f}% average return"
        
        history_data = {
            "trace_id": trace_id,
            "insight_type": "historical_pattern",
            "content": insight,
            "symbol": symbol,
            "timeframe": "30d",
            "sample_size": 100,
            "avg_return": data.get("pnl_percent", 0),
            "embedding": [0.3] * 1536,  # Placeholder embedding
            "source": "history_agent",
            "metadata": {
                "analysis_time": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.8,
                "data_source": "trade_history"
            }
        }
        
        # Write historical insight to database
        await self.safe_writer.write_vector_memory(
            msg_id=data["msg_id"],
            stream=self.stream,
            data={
                **history_data,
                "content_type": "historical_insight"
            }
        )
        
        # Publish to historical_insights stream
        await self.publish_event("historical_insights", history_data)


class NotificationAgent(V3AgentConsumer):
    """Agent 9: Sends notifications for important events."""

    def __init__(self, bus: EventBus, dlq: DLQManager, redis_client: Redis):
        super().__init__(bus, dlq, redis_client, "*", "notification-agent", SafeWriter(AsyncSessionFactory))

    async def process(self, data: Dict[str, Any]) -> None:
        """Process events and send notifications."""
        trace_id = data.get("trace_id")
        
        # Notification logic (simplified - notify on significant events)
        notification_type = "info"
        message = f"Event processed in {self.stream}"
        
        # Check for significant events
        if self.stream == "trade_performance":
            pnl = data.get("pnl", 0)
            if abs(pnl) > 1000:  # Large PnL
                notification_type = "alert"
                message = f"Large trade PnL: ${pnl:.2f}"
        elif self.stream == "agent_grades":
            score = data.get("score", 0)
            if score < 3:  # Low score
                notification_type = "warning"
                message = f"Low agent grade: {score}/10"
        elif self.stream == "proposals":
            proposal_type = data.get("proposal_type")
            if proposal_type == "risk_management":
                notification_type = "warning"
                message = "Risk management proposal generated"
        
        notification_data = {
            "trace_id": trace_id,
            "notification_type": notification_type,
            "message": message,
            "notification_id": str(uuid.uuid4()),
            "source": "notification_agent",
            "metadata": {
                "original_stream": self.stream,
                "priority": "high" if notification_type == "alert" else "medium",
                "notification_time": datetime.now(timezone.utc).isoformat()
            }
        }
        
        # Write notification to database
        await self.safe_writer.write_notification(
            msg_id=data["msg_id"],
            stream=self.stream,
            data=notification_data
        )
        
        # Publish to notifications stream
        await self.publish_event("notifications", notification_data)


# Agent Registry for easy system startup
V3_AGENTS = [
    SignalGeneratorAgent,
    ReasoningAgent,
    ExecutionAgent,
    GradeAgent,
    ICUpdaterAgent,
    ReflectionAgent,
    StrategyProposerAgent,
    HistoryAgent,
    NotificationAgent
]


async def start_v3_agent_system(bus: EventBus, dlq: DLQManager, redis_client: Redis) -> List[V3AgentConsumer]:
    """Start all V3 agents."""
    agents = []
    for agent_class in V3_AGENTS:
        agent = agent_class(bus, dlq, redis_client)
        await agent.start()
        agents.append(agent)
        log_structured("info", "v3_agent_started", agent=agent.__class__.__name__)
    
    log_structured("info", "v3_agent_system_started", agent_count=len(agents))
    return agents


async def stop_v3_agent_system(agents: List[V3AgentConsumer]) -> None:
    """Stop all V3 agents."""
    for agent in agents:
        await agent.stop()
        log_structured("info", "v3_agent_stopped", agent=agent.__class__.__name__)
    
    log_structured("info", "v3_agent_system_stopped")
