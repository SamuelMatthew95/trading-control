"""
Production Trading System with Deterministic Learning
No fallbacks, no randomness, proper agent ranking and self-learning
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Optional, TypedDict, Literal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import uuid
import hashlib


class AgentPerformanceGrade(Enum):
    """Deterministic agent performance grades"""
    EXCELLENT = "A+"
    GOOD = "A"
    SATISFACTORY = "B"
    NEEDS_IMPROVEMENT = "C"
    UNSATISFACTORY = "D"
    FAILING = "F"


@dataclass(frozen=True)
class AgentMetrics:
    """Immutable agent performance metrics"""
    agent_id: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_execution_time_ms: float
    accuracy_score: float
    reliability_score: float
    efficiency_score: float
    grade: AgentPerformanceGrade
    last_updated: str
    
    @classmethod
    def calculate_from_history(cls, agent_id: str, history: List[Dict[str, Any]]) -> 'AgentMetrics':
        """Calculate metrics deterministically from execution history"""
        if not history:
            return cls(
                agent_id=agent_id,
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                average_execution_time_ms=0.0,
                accuracy_score=0.0,
                reliability_score=0.0,
                efficiency_score=0.0,
                grade=AgentPerformanceGrade.FAILING,
                last_updated=datetime.now().isoformat()
            )
        
        total = len(history)
        successful = sum(1 for h in history if h.get("success", False))
        failed = total - successful
        
        # Calculate execution time
        execution_times = [h.get("execution_time_ms", 0) for h in history]
        avg_time = sum(execution_times) / len(execution_times) if execution_times else 0
        
        # Calculate scores (deterministic formulas)
        accuracy_score = successful / total if total > 0 else 0.0
        reliability_score = 1.0 - (failed / total) if total > 0 else 0.0
        efficiency_score = max(0, 1.0 - (avg_time / 10000))  # Normalize against 10s
        
        # Determine grade (deterministic thresholds)
        avg_score = (accuracy_score + reliability_score + efficiency_score) / 3
        
        if avg_score >= 0.95:
            grade = AgentPerformanceGrade.EXCELLENT
        elif avg_score >= 0.85:
            grade = AgentPerformanceGrade.GOOD
        elif avg_score >= 0.75:
            grade = AgentPerformanceGrade.SATISFACTORY
        elif avg_score >= 0.65:
            grade = AgentPerformanceGrade.NEEDS_IMPROVEMENT
        elif avg_score >= 0.5:
            grade = AgentPerformanceGrade.UNSATISFACTORY
        else:
            grade = AgentPerformanceGrade.FAILING
        
        return cls(
            agent_id=agent_id,
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            average_execution_time_ms=avg_time,
            accuracy_score=accuracy_score,
            reliability_score=reliability_score,
            efficiency_score=efficiency_score,
            grade=grade,
            last_updated=datetime.now().isoformat()
        )


@dataclass
class LearningSignal:
    """Deterministic learning signal from execution results"""
    execution_id: str
    agent_id: str
    action: str
    input_hash: str
    output_hash: str
    success: bool
    reward: float
    execution_time_ms: int
    error_type: Optional[str]
    timestamp: str
    
    @classmethod
    def from_execution(cls, execution_id: str, agent_id: str, action: str, 
                      input_data: Dict[str, Any], output_data: Dict[str, Any], 
                      success: bool, execution_time_ms: int, error: Optional[str] = None) -> 'LearningSignal':
        """Create learning signal from execution result"""
        
        # Deterministic hashing
        input_hash = hashlib.sha256(json.dumps(input_data, sort_keys=True).encode()).hexdigest()[:16]
        output_hash = hashlib.sha256(json.dumps(output_data, sort_keys=True).encode()).hexdigest()[:16]
        
        # Calculate reward (deterministic formula)
        reward = 0.0
        if success:
            reward = 1.0 - (execution_time_ms / 10000)  # Time bonus
            if "profit" in output_data:
                reward += min(output_data["profit"] / 1000, 1.0)  # Profit bonus (capped)
        else:
            reward = -1.0  # Fixed penalty for failure
        
        return cls(
            execution_id=execution_id,
            agent_id=agent_id,
            action=action,
            input_hash=input_hash,
            output_hash=output_hash,
            success=success,
            reward=reward,
            execution_time_ms=execution_time_ms,
            error_type=error,
            timestamp=datetime.now().isoformat()
        )


class AgentCommunicationProtocol:
    """Formal protocol for agent-to-agent communication"""
    
    @dataclass(frozen=True)
    class Message:
        """Immutable agent message"""
        sender_id: str
        receiver_id: str
        message_type: str
        payload: Dict[str, Any]
        priority: int  # 1=highest, 10=lowest
        correlation_id: str
        timestamp: str
        requires_response: bool = False
        
        @classmethod
        def create(cls, sender_id: str, receiver_id: str, message_type: str, 
                  payload: Dict[str, Any], priority: int = 5, 
                  correlation_id: Optional[str] = None) -> 'AgentCommunicationProtocol.Message':
            """Create message with deterministic correlation ID"""
            if correlation_id is None:
                correlation_id = hashlib.sha256(f"{sender_id}{receiver_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
            
            return cls(
                sender_id=sender_id,
                receiver_id=receiver_id,
                message_type=message_type,
                payload=payload,
                priority=priority,
                correlation_id=correlation_id,
                timestamp=datetime.now().isoformat()
            )
    
    def __init__(self):
        self.message_queue: List[AgentCommunicationProtocol.Message] = []
        self.message_handlers: Dict[str, callable] = {}
        self.communication_log: List[Dict[str, Any]] = []
    
    def register_handler(self, message_type: str, handler: callable):
        """Register message handler"""
        self.message_handlers[message_type] = handler
    
    def send_message(self, message: AgentCommunicationProtocol.Message):
        """Queue message for delivery"""
        self.message_queue.append(message)
        # Sort by priority (lower number = higher priority)
        self.message_queue.sort(key=lambda m: m.priority)
        
        # Log communication
        self.communication_log.append({
            "timestamp": message.timestamp,
            "sender": message.sender_id,
            "receiver": message.receiver_id,
            "type": message.message_type,
            "correlation_id": message.correlation_id,
            "action": "message_queued"
        })
    
    async def process_messages(self) -> List[Dict[str, Any]]:
        """Process all queued messages"""
        results = []
        
        while self.message_queue:
            message = self.message_queue.pop(0)
            
            try:
                if message.message_type in self.message_handlers:
                    handler = self.message_handlers[message.message_type]
                    result = await handler(message)
                    
                    results.append({
                        "success": True,
                        "message_id": message.correlation_id,
                        "result": result,
                        "processed_at": datetime.now().isoformat()
                    })
                    
                    # Log successful processing
                    self.communication_log.append({
                        "timestamp": datetime.now().isoformat(),
                        "sender": message.sender_id,
                        "receiver": message.receiver_id,
                        "type": message.message_type,
                        "correlation_id": message.correlation_id,
                        "action": "message_processed",
                        "result": "success"
                    })
                else:
                    results.append({
                        "success": False,
                        "message_id": message.correlation_id,
                        "error": f"No handler for message type: {message.message_type}",
                        "processed_at": datetime.now().isoformat()
                    })
                    
                    # Log failed processing
                    self.communication_log.append({
                        "timestamp": datetime.now().isoformat(),
                        "sender": message.sender_id,
                        "receiver": message.receiver_id,
                        "type": message.message_type,
                        "correlation_id": message.correlation_id,
                        "action": "message_failed",
                        "result": "no_handler"
                    })
                    
            except Exception as e:
                results.append({
                    "success": False,
                    "message_id": message.correlation_id,
                    "error": str(e),
                    "processed_at": datetime.now().isoformat()
                })
                
                # Log error
                self.communication_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "sender": message.sender_id,
                    "receiver": message.receiver_id,
                    "type": message.message_type,
                    "correlation_id": message.correlation_id,
                    "action": "message_error",
                    "error": str(e)
                })
        
        return results


class LearningManager:
    """Deterministic learning manager without randomness"""
    
    def __init__(self):
        self.learning_signals: List[LearningSignal] = []
        self.agent_models: Dict[str, Dict[str, Any]] = {}
        self.learning_updates: List[Dict[str, Any]] = []
    
    def add_learning_signal(self, signal: LearningSignal):
        """Add learning signal from execution"""
        self.learning_signals.append(signal)
        
        # Keep buffer manageable
        if len(self.learning_signals) > 10000:
            self.learning_signals = self.learning_signals[-5000:]
    
    def calculate_agent_update(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Calculate deterministic learning update for agent"""
        agent_signals = [s for s in self.learning_signals if s.agent_id == agent_id]
        
        if len(agent_signals) < 10:  # Need minimum data for learning
            return None
        
        # Calculate performance metrics
        recent_signals = agent_signals[-100:]  # Last 100 signals
        success_rate = sum(1 for s in recent_signals if s.success) / len(recent_signals)
        avg_reward = sum(s.reward for s in recent_signals) / len(recent_signals)
        avg_execution_time = sum(s.execution_time_ms for s in recent_signals) / len(recent_signals)
        
        # Determine learning direction (deterministic)
        if success_rate < 0.6:
            learning_direction = "decrease_confidence"
            adjustment_factor = 0.1
        elif success_rate > 0.9 and avg_execution_time < 1000:
            learning_direction = "increase_confidence"
            adjustment_factor = 0.05
        else:
            learning_direction = "maintain"
            adjustment_factor = 0.0
        
        # Calculate parameter updates
        current_model = self.agent_models.get(agent_id, {
            "confidence_threshold": 0.7,
            "timeout_ms": 5000,
            "retry_count": 2,
            "risk_tolerance": 0.5
        })
        
        updates = {}
        
        if learning_direction == "decrease_confidence":
            updates["confidence_threshold"] = min(0.95, current_model["confidence_threshold"] + adjustment_factor)
            updates["timeout_ms"] = min(10000, current_model["timeout_ms"] + 1000)
        elif learning_direction == "increase_confidence":
            updates["confidence_threshold"] = max(0.5, current_model["confidence_threshold"] - adjustment_factor)
            updates["timeout_ms"] = max(1000, current_model["timeout_ms"] - 500)
        
        # Record learning update
        update_record = {
            "agent_id": agent_id,
            "timestamp": datetime.now().isoformat(),
            "learning_direction": learning_direction,
            "success_rate": success_rate,
            "avg_reward": avg_reward,
            "avg_execution_time": avg_execution_time,
            "updates": updates,
            "signal_count": len(recent_signals)
        }
        
        self.learning_updates.append(update_record)
        self.agent_models[agent_id] = {**current_model, **updates}
        
        return update_record
    
    def get_agent_model(self, agent_id: str) -> Dict[str, Any]:
        """Get current learned model for agent"""
        return self.agent_models.get(agent_id, {
            "confidence_threshold": 0.7,
            "timeout_ms": 5000,
            "retry_count": 2,
            "risk_tolerance": 0.5
        })


class AgentRankingSystem:
    """Deterministic agent ranking system"""
    
    def __init__(self):
        self.agent_metrics: Dict[str, AgentMetrics] = {}
        self.execution_history: Dict[str, List[Dict[str, Any]]] = {}
        self.rankings: List[Dict[str, Any]] = []
    
    def record_execution(self, agent_id: str, execution_result: Dict[str, Any]):
        """Record agent execution for ranking"""
        if agent_id not in self.execution_history:
            self.execution_history[agent_id] = []
        
        self.execution_history[agent_id].append(execution_result)
        
        # Keep history manageable
        if len(self.execution_history[agent_id]) > 1000:
            self.execution_history[agent_id] = self.execution_history[agent_id][-500:]
        
        # Update metrics
        self.agent_metrics[agent_id] = AgentMetrics.calculate_from_history(
            agent_id, 
            self.execution_history[agent_id]
        )
        
        # Update rankings
        self._update_rankings()
    
    def _update_rankings(self):
        """Update agent rankings deterministically"""
        agents = []
        
        for agent_id, metrics in self.agent_metrics.items():
            # Calculate ranking score (deterministic formula)
            ranking_score = (
                metrics.accuracy_score * 0.4 +
                metrics.reliability_score * 0.3 +
                metrics.efficiency_score * 0.3
            )
            
            agents.append({
                "agent_id": agent_id,
                "grade": metrics.grade,
                "ranking_score": ranking_score,
                "accuracy_score": metrics.accuracy_score,
                "reliability_score": metrics.reliability_score,
                "efficiency_score": metrics.efficiency_score,
                "total_executions": metrics.total_executions,
                "last_updated": metrics.last_updated
            })
        
        # Sort by ranking score (descending)
        self.rankings = sorted(agents, key=lambda a: a["ranking_score"], reverse=True)
    
    def get_top_agents(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get top performing agents"""
        return self.rankings[:count]
    
    def get_agent_rank(self, agent_id: str) -> Optional[int]:
        """Get agent's rank in the system"""
        for i, agent in enumerate(self.rankings):
            if agent["agent_id"] == agent_id:
                return i + 1
        return None
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary of all agents"""
        if not self.rankings:
            return {"total_agents": 0, "average_score": 0.0}
        
        total_agents = len(self.rankings)
        average_score = sum(a["ranking_score"] for a in self.rankings) / total_agents
        
        grade_distribution = {}
        for agent in self.rankings:
            grade = agent["grade"].value
            grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
        
        return {
            "total_agents": total_agents,
            "average_score": average_score,
            "grade_distribution": grade_distribution,
            "top_performer": self.rankings[0] if self.rankings else None,
            "last_updated": datetime.now().isoformat()
        }


class SelfImprovingAgent:
    """Base class for self-improving agents"""
    
    def __init__(self, agent_id: str, communication_protocol: AgentCommunicationProtocol,
                 learning_manager: LearningManager, ranking_system: AgentRankingSystem):
        self.agent_id = agent_id
        self.communication_protocol = communication_protocol
        self.learning_manager = learning_manager
        self.ranking_system = ranking_system
        self.execution_count = 0
        
        # Register communication handlers
        self._register_communication_handlers()
    
    def _register_communication_handlers(self):
        """Register communication message handlers"""
        self.communication_protocol.register_handler(
            "performance_query",
            self._handle_performance_query
        )
        self.communication_protocol.register_handler(
            "learning_update",
            self._handle_learning_update
        )
        self.communication_protocol.register_handler(
            "collaboration_request",
            self._handle_collaboration_request
        )
    
    async def _handle_performance_query(self, message: AgentCommunicationProtocol.Message) -> Dict[str, Any]:
        """Handle performance query from other agents"""
        metrics = self.ranking_system.agent_metrics.get(self.agent_id)
        
        if metrics:
            return {
                "agent_id": self.agent_id,
                "grade": metrics.grade.value,
                "accuracy_score": metrics.accuracy_score,
                "reliability_score": metrics.reliability_score,
                "efficiency_score": metrics.efficiency_score,
                "total_executions": metrics.total_executions
            }
        else:
            return {
                "agent_id": self.agent_id,
                "error": "No performance data available"
            }
    
    async def _handle_learning_update(self, message: AgentCommunicationProtocol.Message) -> Dict[str, Any]:
        """Handle learning update from manager"""
        update_data = message.payload
        
        # Apply learning updates
        current_model = self.learning_manager.get_agent_model(self.agent_id)
        updated_model = {**current_model, **update_data.get("updates", {})}
        
        # Update agent configuration
        self._apply_learning_updates(updated_model)
        
        return {
            "agent_id": self.agent_id,
            "updates_applied": True,
            "new_model": updated_model
        }
    
    async def _handle_collaboration_request(self, message: AgentCommunicationProtocol.Message) -> Dict[str, Any]:
        """Handle collaboration request from other agents"""
        collaboration_type = message.payload.get("type", "query")
        
        if collaboration_type == "query":
            return await self._handle_collaboration_query(message.payload)
        elif collaboration_type == "assist":
            return await self._handle_collaboration_assist(message.payload)
        else:
            return {
                "agent_id": self.agent_id,
                "error": f"Unknown collaboration type: {collaboration_type}"
            }
    
    async def _handle_collaboration_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle collaboration query"""
        query_type = payload.get("query_type")
        
        if query_type == "best_practice":
            return {
                "agent_id": self.agent_id,
                "best_practice": self._get_best_practice(),
                "success_rate": self._get_success_rate()
            }
        elif query_type == "error_pattern":
            return {
                "agent_id": self.agent_id,
                "error_patterns": self._get_error_patterns()
            }
        else:
            return {
                "agent_id": self.agent_id,
                "error": f"Unknown query type: {query_type}"
            }
    
    async def _handle_collaboration_assist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle collaboration assistance request"""
        task = payload.get("task")
        
        if self._can_assist_with_task(task):
            assistance = self._provide_assistance(task)
            return {
                "agent_id": self.agent_id,
                "can_assist": True,
                "assistance": assistance
            }
        else:
            return {
                "agent_id": self.agent_id,
                "can_assist": False,
                "reason": "Task outside agent capabilities"
            }
    
    def _apply_learning_updates(self, updated_model: Dict[str, Any]):
        """Apply learning updates to agent configuration"""
        # To be implemented by specific agents
        pass
    
    def _get_best_practice(self) -> Dict[str, Any]:
        """Get agent's best practices"""
        # To be implemented by specific agents
        return {}
    
    def _get_success_rate(self) -> float:
        """Get agent's success rate"""
        metrics = self.ranking_system.agent_metrics.get(self.agent_id)
        return metrics.accuracy_score if metrics else 0.0
    
    def _get_error_patterns(self) -> List[Dict[str, Any]]:
        """Get agent's error patterns"""
        history = self.ranking_system.execution_history.get(self.agent_id, [])
        errors = [h for h in history if not h.get("success", False)]
        
        # Analyze error patterns
        error_types = {}
        for error in errors:
            error_type = error.get("error_type", "unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return [
            {"error_type": error_type, "count": count}
            for error_type, count in error_types.items()
        ]
    
    def _can_assist_with_task(self, task: str) -> bool:
        """Check if agent can assist with task"""
        # To be implemented by specific agents
        return False
    
    def _provide_assistance(self, task: str) -> Dict[str, Any]:
        """Provide assistance for task"""
        # To be implemented by specific agents
        return {}
    
    async def execute_with_learning(self, action: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action with learning and ranking"""
        execution_id = f"exec_{self.agent_id}_{uuid.uuid4().hex[:8]}"
        start_time = datetime.now()
        
        try:
            # Get learned model parameters
            model = self.learning_manager.get_agent_model(self.agent_id)
            
            # Execute action
            result = await self._execute_action(action, input_data, model)
            
            # Calculate execution time
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Record execution result
            execution_result = {
                "execution_id": execution_id,
                "agent_id": self.agent_id,
                "action": action,
                "success": True,
                "result": result,
                "execution_time_ms": execution_time_ms,
                "timestamp": start_time.isoformat()
            }
            
            # Update ranking system
            self.ranking_system.record_execution(self.agent_id, execution_result)
            
            # Create learning signal
            learning_signal = LearningSignal.from_execution(
                execution_id, self.agent_id, action, input_data, result, True, execution_time_ms
            )
            
            # Add to learning manager
            self.learning_manager.add_learning_signal(learning_signal)
            
            # Check for learning updates
            learning_update = self.learning_manager.calculate_agent_update(self.agent_id)
            if learning_update:
                # Send learning update to self
                message = AgentCommunicationProtocol.Message.create(
                    "learning_manager",
                    self.agent_id,
                    "learning_update",
                    learning_update,
                    priority=1
                )
                await self.communication_protocol.process_messages()
            
            self.execution_count += 1
            
            return {
                "success": True,
                "result": result,
                "execution_id": execution_id,
                "execution_time_ms": execution_time_ms,
                "agent_rank": self.ranking_system.get_agent_rank(self.agent_id)
            }
            
        except Exception as e:
            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Record failed execution
            execution_result = {
                "execution_id": execution_id,
                "agent_id": self.agent_id,
                "action": action,
                "success": False,
                "error": str(e),
                "execution_time_ms": execution_time_ms,
                "timestamp": start_time.isoformat()
            }
            
            # Update ranking system
            self.ranking_system.record_execution(self.agent_id, execution_result)
            
            # Create learning signal for failure
            learning_signal = LearningSignal.from_execution(
                execution_id, self.agent_id, action, input_data, {}, False, execution_time_ms, str(e)
            )
            
            # Add to learning manager
            self.learning_manager.add_learning_signal(learning_signal)
            
            # No fallback - fail safely
            return {
                "success": False,
                "error": str(e),
                "execution_id": execution_id,
                "execution_time_ms": execution_time_ms,
                "agent_rank": self.ranking_system.get_agent_rank(self.agent_id)
            }
    
    async def _execute_action(self, action: str, input_data: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        """Execute specific action (to be implemented by subclasses)"""
        raise NotImplementedError("Subclasses must implement _execute_action")


class DeterministicTradingSystem:
    """Main system with deterministic learning and agent communication"""
    
    def __init__(self):
        self.system_id = f"deterministic_trading_{uuid.uuid4().hex[:8]}"
        
        # Initialize components
        self.communication_protocol = AgentCommunicationProtocol()
        self.learning_manager = LearningManager()
        self.ranking_system = AgentRankingSystem()
        
        # Initialize agents
        self.agents: Dict[str, SelfImprovingAgent] = {}
        
        # System metrics
        self.system_metrics = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "learning_updates": 0,
            "communications_processed": 0
        }
    
    def register_agent(self, agent: SelfImprovingAgent):
        """Register agent with the system"""
        self.agents[agent.agent_id] = agent
    
    async def execute_agent_task(self, agent_id: str, action: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task through specific agent"""
        if agent_id not in self.agents:
            return {
                "success": False,
                "error": f"Agent {agent_id} not found"
            }
        
        agent = self.agents[agent_id]
        result = await agent.execute_with_learning(action, input_data)
        
        # Update system metrics
        self.system_metrics["total_executions"] += 1
        if result["success"]:
            self.system_metrics["successful_executions"] += 1
        else:
            self.system_metrics["failed_executions"] += 1
        
        return result
    
    async def process_agent_communications(self) -> Dict[str, Any]:
        """Process all agent communications"""
        results = await self.communication_protocol.process_messages()
        
        self.system_metrics["communications_processed"] += len(results)
        
        return {
            "processed_messages": len(results),
            "results": results,
            "queue_size": len(self.communication_protocol.message_queue)
        }
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "system_id": self.system_id,
            "metrics": self.system_metrics,
            "agent_count": len(self.agents),
            "ranking_summary": self.ranking_system.get_performance_summary(),
            "learning_signals_count": len(self.learning_manager.learning_signals),
            "learning_updates_count": len(self.learning_manager.learning_updates),
            "communication_log_size": len(self.communication_protocol.communication_log),
            "top_agents": self.ranking_system.get_top_agents(5),
            "timestamp": datetime.now().isoformat()
        }


# Factory function
def create_deterministic_trading_system() -> DeterministicTradingSystem:
    """Create deterministic trading system"""
    return DeterministicTradingSystem()
