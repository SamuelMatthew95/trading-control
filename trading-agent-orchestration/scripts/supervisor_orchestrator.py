"""
Production-Grade Supervisor Orchestrator
Implements deterministic workflow with 5-agent ceiling
Intelligence lives here, agents are dumb workers
"""

from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import json

from ..agents.market_data_agent import MarketDataAgent, MarketDataInput, MarketDataOutput
from ..agents.data_validation_agent import DataValidationAgent, ValidationInput, ValidationOutput
from ..agents.technical_analysis_agent import TechnicalAnalysisAgent, TechnicalAnalysisInput, TechnicalAnalysisOutput


class WorkflowState(Enum):
    """Deterministic workflow states"""
    INITIATED = "initiated"
    DATA_COLLECTION = "data_collection"
    DATA_VALIDATION = "data_validation"
    ANALYSIS = "analysis"
    SIGNAL_GENERATION = "signal_generation"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentTaskStatus(Enum):
    """Agent task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    """Structured agent task definition"""
    task_id: str
    agent_id: str
    input_data: Dict[str, Any]
    status: AgentTaskStatus = AgentTaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    execution_time_ms: Optional[int] = None


@dataclass
class WorkflowTrace:
    """Complete workflow trace for observability"""
    workflow_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    state: WorkflowState = WorkflowState.INITIATED
    tasks: List[AgentTask] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    state_transitions: List[Dict[str, Any]] = field(default_factory=list)
    final_result: Optional[Dict[str, Any]] = None


class SupervisorOrchestrator:
    """
    Production-grade supervisor orchestrator
    Implements deterministic workflows with stateless agents
    """
    
    def __init__(self):
        self.orchestrator_id = f"supervisor_{uuid.uuid4().hex[:8]}"
        self.version = "2.0.0"
        
        # Initialize stateless agents (worker pool)
        self.agents = {
            "market_data": MarketDataAgent(),
            "data_validation": DataValidationAgent(),
            "technical_analysis": TechnicalAnalysisAgent()
        }
        
        # Workflow state tracking
        self.active_workflows: Dict[str, WorkflowTrace] = {}
        self.workflow_history: List[WorkflowTrace] = []
        
        # 5-agent ceiling enforcement
        self.max_concurrent_agents = 5
        self.agent_usage_counts = {agent_id: 0 for agent_id in self.agents.keys()}
    
    async def execute_trading_analysis(self, symbol: str, analysis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute complete trading analysis workflow
        This is where the intelligence lives - deterministic decision making
        """
        workflow_id = f"workflow_{uuid.uuid4().hex[:8]}"
        trace = WorkflowTrace(workflow_id=workflow_id, start_time=datetime.now())
        self.active_workflows[workflow_id] = trace
        
        try:
            # Step 1: Data Collection
            await self._transition_state(trace, WorkflowState.DATA_COLLECTION)
            market_data_task = await self._execute_agent_task(
                "market_data",
                {"symbol": symbol, "data_sources": analysis_config.get("data_sources", ["alpha_vantage", "yahoo_finance"])},
                trace
            )
            
            if not market_data_task.result:
                raise ValueError("Market data collection failed")
            
            # Step 2: Data Validation
            await self._transition_state(trace, WorkflowState.DATA_VALIDATION)
            validation_task = await self._execute_agent_task(
                "data_validation",
                {"data": market_data_task.result, "source": "market_data"},
                trace
            )
            
            # Decision: Proceed only if data is valid
            if not validation_task.result.get("is_valid", False):
                await self._record_decision(trace, {
                    "decision": "abort_workflow",
                    "reason": "data_validation_failed",
                    "errors": validation_task.result.get("errors", [])
                })
                raise ValueError("Data validation failed")
            
            # Step 3: Technical Analysis
            await self._transition_state(trace, WorkflowState.ANALYSIS)
            
            # Prepare price data for technical analysis
            price_data = self._prepare_price_data(symbol, market_data_task.result)
            
            analysis_task = await self._execute_agent_task(
                "technical_analysis",
                {
                    "symbol": symbol,
                    "price_data": price_data,
                    "indicators": analysis_config.get("indicators", ["RSI", "MACD", "BB"]),
                    "time_period": analysis_config.get("time_period", 14)
                },
                trace
            )
            
            # Step 4: Signal Generation
            await self._transition_state(trace, WorkflowState.SIGNAL_GENERATION)
            final_signal = self._generate_final_signal(validation_task.result, analysis_task.result)
            
            await self._record_decision(trace, {
                "decision": "generate_signal",
                "final_signal": final_signal,
                "confidence": self._calculate_signal_confidence(validation_task.result, analysis_task.result)
            })
            
            # Complete workflow
            await self._transition_state(trace, WorkflowState.COMPLETED)
            trace.final_result = {
                "symbol": symbol,
                "signal": final_signal,
                "market_data": market_data_task.result,
                "validation": validation_task.result,
                "analysis": analysis_task.result,
                "workflow_id": workflow_id,
                "execution_time_ms": self._calculate_workflow_time(trace)
            }
            
            return trace.final_result
            
        except Exception as e:
            await self._transition_state(trace, WorkflowState.FAILED)
            trace.final_result = {
                "error": str(e),
                "workflow_id": workflow_id,
                "failed_at": trace.state.value
            }
            raise
        
        finally:
            # Cleanup and history tracking
            trace.end_time = datetime.now()
            self.workflow_history.append(trace)
            if workflow_id in self.active_workflows:
                del self.active_workflows[workflow_id]
    
    async def _execute_agent_task(self, agent_id: str, input_data: Dict[str, Any], trace: WorkflowTrace) -> AgentTask:
        """Execute agent task with full observability"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = AgentTask(task_id=task_id, agent_id=agent_id, input_data=input_data)
        trace.tasks.append(task)
        
        try:
            # Check agent ceiling
            if self.agent_usage_counts[agent_id] >= self.max_concurrent_agents:
                raise ValueError(f"Agent {agent_id} at capacity ceiling")
            
            # Update task status
            task.status = AgentTaskStatus.RUNNING
            task.start_time = datetime.now()
            self.agent_usage_counts[agent_id] += 1
            
            # Execute agent (stateless worker)
            agent = self.agents[agent_id]
            
            if agent_id == "market_data":
                result = await agent.execute(MarketDataInput(**input_data))
                task.result = result.dict()
            elif agent_id == "data_validation":
                result = await agent.execute(ValidationInput(**input_data))
                task.result = result.dict()
            elif agent_id == "technical_analysis":
                result = await agent.execute(TechnicalAnalysisInput(**input_data))
                task.result = result.dict()
            
            # Complete task
            task.status = AgentTaskStatus.COMPLETED
            task.end_time = datetime.now()
            task.execution_time_ms = int((task.end_time - task.start_time).total_seconds() * 1000)
            
            return task
            
        except Exception as e:
            task.status = AgentTaskStatus.FAILED
            task.error = str(e)
            task.end_time = datetime.now()
            raise
        
        finally:
            # Update agent usage
            if agent_id in self.agent_usage_counts:
                self.agent_usage_counts[agent_id] = max(0, self.agent_usage_counts[agent_id] - 1)
    
    def _prepare_price_data(self, symbol: str, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Prepare price data for technical analysis"""
        # In a real implementation, this would fetch historical data
        # For now, create mock data based on current price
        current_price = market_data.get("price", 100.0)
        
        price_data = []
        for i in range(100):  # 100 days of mock data
            price = current_price * (1 + (i - 50) * 0.001)  # Small variations
            price_data.append({
                "date": f"2024-01-{i+1:02d}",
                "open": price * 0.999,
                "high": price * 1.001,
                "low": price * 0.998,
                "close": price,
                "volume": 1000000 + i * 1000
            })
        
        return price_data
    
    def _generate_final_signal(self, validation_result: Dict[str, Any], analysis_result: Dict[str, Any]) -> str:
        """Generate final trading signal - deterministic logic"""
        # Base signal on technical analysis
        overall_signal = analysis_result.get("overall_signal", "hold")
        
        # Adjust based on data quality
        quality_score = validation_result.get("quality_score", 100)
        if quality_score < 70:
            # Downgrade signal if data quality is poor
            if overall_signal in ["strong_buy", "buy"]:
                overall_signal = "hold"
            elif overall_signal in ["strong_sell", "sell"]:
                overall_signal = "hold"
        
        return overall_signal
    
    def _calculate_signal_confidence(self, validation_result: Dict[str, Any], analysis_result: Dict[str, Any]) -> float:
        """Calculate signal confidence - deterministic formula"""
        quality_score = validation_result.get("quality_score", 100) / 100.0
        
        # Get average confidence from indicators
        indicators = analysis_result.get("indicators", [])
        if indicators:
            avg_indicator_confidence = sum(ind.get("confidence", 0) for ind in indicators) / len(indicators)
        else:
            avg_indicator_confidence = 0.5
        
        # Weighted average
        confidence = (quality_score * 0.4) + (avg_indicator_confidence * 0.6)
        return round(confidence, 3)
    
    def _calculate_workflow_time(self, trace: WorkflowTrace) -> int:
        """Calculate total workflow execution time"""
        if trace.end_time and trace.start_time:
            return int((trace.end_time - trace.start_time).total_seconds() * 1000)
        return 0
    
    async def _transition_state(self, trace: WorkflowTrace, new_state: WorkflowState):
        """Record state transition for observability"""
        old_state = trace.state
        trace.state = new_state
        
        trace.state_transitions.append({
            "timestamp": datetime.now().isoformat(),
            "from_state": old_state.value,
            "to_state": new_state.value,
            "workflow_id": trace.workflow_id
        })
    
    async def _record_decision(self, trace: WorkflowTrace, decision: Dict[str, Any]):
        """Record decision for observability"""
        decision["timestamp"] = datetime.now().isoformat()
        decision["workflow_id"] = trace.workflow_id
        trace.decisions.append(decision)
    
    def get_workflow_trace(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get complete workflow trace for debugging"""
        if workflow_id in self.active_workflows:
            trace = self.active_workflows[workflow_id]
        else:
            trace = next((t for t in self.workflow_history if t.workflow_id == workflow_id), None)
        
        if trace:
            return {
                "workflow_id": trace.workflow_id,
                "start_time": trace.start_time.isoformat(),
                "end_time": trace.end_time.isoformat() if trace.end_time else None,
                "state": trace.state.value,
                "tasks": [
                    {
                        "task_id": task.task_id,
                        "agent_id": task.agent_id,
                        "status": task.status.value,
                        "input_data": task.input_data,
                        "result": task.result,
                        "error": task.error,
                        "start_time": task.start_time.isoformat() if task.start_time else None,
                        "end_time": task.end_time.isoformat() if task.end_time else None,
                        "execution_time_ms": task.execution_time_ms
                    }
                    for task in trace.tasks
                ],
                "decisions": trace.decisions,
                "state_transitions": trace.state_transitions,
                "final_result": trace.final_result
            }
        return None
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get system status for monitoring"""
        return {
            "orchestrator_id": self.orchestrator_id,
            "version": self.version,
            "active_workflows": len(self.active_workflows),
            "completed_workflows": len(self.workflow_history),
            "agent_usage": self.agent_usage_counts,
            "max_concurrent_agents": self.max_concurrent_agents,
            "available_agents": {
                agent_id: self.max_concurrent_agents - count
                for agent_id, count in self.agent_usage_counts.items()
            }
        }
