"""
Professional Trading Orchestrator using LangGraph
State-machine-based system with Supervisor/Worker architecture
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict

# LangGraph imports (industry standard for stateful orchestration)
try:
    from langgraph.graph import END, StateGraph
    from langgraph.prebuilt import ToolExecutor
except ImportError:
    # Fallback implementation if LangGraph not available
    class StateGraph:
        def __init__(self, state_class):
            self.state_class = state_class
            self.nodes = {}
            self.edges = []

        def add_node(self, name: str, func):
            self.nodes[name] = func

        def add_edge(self, from_node: str, to_node: str):
            self.edges.append((from_node, to_node))

        def add_conditional_edges(self, from_node: str, condition):
            self.edges.append((from_node, "conditional", condition))

        def set_entry_point(self, node: str):
            self.entry_point = node

        def compile(self):
            return self

    END = "END"


class TradingState(TypedDict):
    """
    Single Source of Truth for the trading system
    This state is passed through all nodes and persisted after every step
    """

    # Core market data
    market_data: Dict[str, Any]  # Current prices, order books
    market_timestamp: str  # When market data was last updated

    # Portfolio state
    open_positions: List[Dict[str, Any]]  # What we currently hold
    portfolio_value: float  # Account balance + position value
    available_capital: float  # Capital available for new trades
    total_pnl: float  # Total profit/loss

    # Risk management
    risk_snapshot: Dict[str, Any]  # Current exposure/stop-loss limits
    max_position_size: float  # Maximum position size
    daily_loss_limit: float  # Daily loss limit
    current_daily_loss: float  # Current daily loss

    # Trade execution
    proposed_trade: Optional[Dict[str, Any]]  # Trade currently being considered
    trade_history: List[Dict[str, Any]]  # History of all trades
    pending_orders: List[Dict[str, Any]]  # Orders waiting execution

    # Decision tracking
    decision_log: List[Dict[str, Any]]  # History of why we took specific actions
    current_phase: str  # Current phase in the state machine
    last_action: Optional[str]  # Last action taken
    error_state: Optional[str]  # Any error conditions

    # Learning and analytics
    experience_buffer: List[
        Dict[str, Any]
    ]  # (state, action, reward, next_state) tuples
    performance_metrics: Dict[str, float]  # Sharpe ratio, win rate, etc.
    model_confidence: float  # Current model confidence score

    # System metadata
    orchestrator_id: str  # Unique orchestrator instance ID
    session_id: str  # Current trading session
    last_updated: str  # Timestamp of last state update


class TradingPhase(Enum):
    """State machine phases for the trading system"""

    INITIALIZING = "initializing"
    DATA_COLLECTION = "data_collection"
    ANALYSIS = "analysis"
    RISK_ASSESSMENT = "risk_assessment"
    TRADE_DECISION = "trade_decision"
    EXECUTION = "execution"
    MONITORING = "monitoring"
    ERROR_HANDLING = "error_handling"
    SHUTDOWN = "shutdown"


@dataclass
class SafetyProtocol:
    """
    Hard-coded safety protocols that keep the system alive
    These are NOT learned - they are deterministic safety rules
    """

    max_daily_loss: float = 1000.0  # Never lose more than $1000 per day
    max_position_size: float = 10000.0  # Never allocate more than $10k to one asset
    max_portfolio_risk: float = 0.2  # Never risk more than 20% of portfolio
    min_confidence_threshold: float = 0.7  # Only trade with 70%+ confidence
    emergency_stop: bool = False  # Global emergency stop flag

    def check_trade_safety(
        self, proposed_trade: Dict[str, Any], state: TradingState
    ) -> Literal["approve", "reject", "emergency_stop"]:
        """Check if a proposed trade violates safety protocols"""

        # Emergency stop check
        if self.emergency_stop:
            return "emergency_stop"

        # Daily loss limit check
        if state["current_daily_loss"] >= self.max_daily_loss:
            return "emergency_stop"

        # Position size check
        trade_size = proposed_trade.get("size", 0)
        if trade_size > self.max_position_size:
            return "reject"

        # Portfolio risk check
        portfolio_value = state["portfolio_value"]
        if portfolio_value > 0:
            risk_ratio = trade_size / portfolio_value
            if risk_ratio > self.max_portfolio_risk:
                return "reject"

        # Confidence threshold check
        confidence = proposed_trade.get("confidence", 0)
        if confidence < self.min_confidence_threshold:
            return "reject"

        return "approve"


class SupervisorOrchestrator:
    """
    Central brain of the trading system
    Maintains global state and delegates to specialist worker agents
    """

    def __init__(self):
        self.orchestrator_id = f"supervisor_{uuid.uuid4().hex[:8]}"
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Initialize safety protocols
        self.safety = SafetyProtocol()

        # Initialize worker agents
        self.data_analyst = DataAnalystAgent()
        self.risk_controller = RiskControlAgent()
        self.execution_agent = ExecutionAgent()
        self.monitoring_agent = MonitoringAgent()

        # State persistence
        self.state_storage = StateStorage()

        # Build the state machine graph
        self.graph = self._build_state_graph()

    def _build_state_graph(self) -> StateGraph:
        """Build the LangGraph state machine"""
        workflow = StateGraph(TradingState)

        # Add nodes (worker agents)
        workflow.add_node("data_collection", self._data_collection_node)
        workflow.add_node("analysis", self._analysis_node)
        workflow.add_node("risk_assessment", self._risk_assessment_node)
        workflow.add_node("trade_decision", self._trade_decision_node)
        workflow.add_node("execution", self._execution_node)
        workflow.add_node("monitoring", self._monitoring_node)
        workflow.add_node("error_handling", self._error_handling_node)

        # Define the flow
        workflow.set_entry_point("data_collection")
        workflow.add_edge("data_collection", "analysis")
        workflow.add_edge("analysis", "risk_assessment")
        workflow.add_conditional_edges("risk_assessment", self._risk_decision_router)
        workflow.add_edge("trade_decision", "execution")
        workflow.add_edge("execution", "monitoring")
        workflow.add_edge("monitoring", "data_collection")
        workflow.add_edge("error_handling", "data_collection")

        return workflow.compile()

    async def run_trading_cycle(
        self, initial_state: Optional[TradingState] = None
    ) -> TradingState:
        """Run one complete trading cycle through the state machine"""

        # Initialize or load state
        if initial_state:
            state = initial_state
        else:
            state = await self._initialize_state()

        # Set orchestrator metadata
        state["orchestrator_id"] = self.orchestrator_id
        state["session_id"] = self.session_id
        state["last_updated"] = datetime.now().isoformat()

        try:
            # Run the state machine
            result = await self.graph.ainvoke(state)

            # Persist state after cycle
            await self.state_storage.save_state(result)

            return result

        except Exception as e:
            # Handle errors gracefully
            error_state = await self._handle_system_error(state, str(e))
            await self.state_storage.save_state(error_state)
            return error_state

    async def _initialize_state(self) -> TradingState:
        """Initialize the trading state"""
        return {
            # Core market data
            "market_data": {},
            "market_timestamp": datetime.now().isoformat(),
            # Portfolio state
            "open_positions": [],
            "portfolio_value": 100000.0,  # Starting with $100k
            "available_capital": 100000.0,
            "total_pnl": 0.0,
            # Risk management
            "risk_snapshot": {
                "max_daily_loss": self.safety.max_daily_loss,
                "max_position_size": self.safety.max_position_size,
                "current_risk": 0.0,
            },
            "max_position_size": self.safety.max_position_size,
            "daily_loss_limit": self.safety.max_daily_loss,
            "current_daily_loss": 0.0,
            # Trade execution
            "proposed_trade": None,
            "trade_history": [],
            "pending_orders": [],
            # Decision tracking
            "decision_log": [],
            "current_phase": TradingPhase.INITIALIZING.value,
            "last_action": None,
            "error_state": None,
            # Learning and analytics
            "experience_buffer": [],
            "performance_metrics": {
                "sharpe_ratio": 0.0,
                "win_rate": 0.0,
                "total_trades": 0,
            },
            "model_confidence": 0.5,
            # System metadata
            "orchestrator_id": self.orchestrator_id,
            "session_id": self.session_id,
            "last_updated": datetime.now().isoformat(),
        }

    # State Machine Nodes (Worker Agent Delegation)

    async def _data_collection_node(self, state: TradingState) -> TradingState:
        """Node: Collect market data"""
        state["current_phase"] = TradingPhase.DATA_COLLECTION.value

        try:
            # Delegate to Data Analyst Agent
            market_data = await self.data_analyst.collect_market_data()

            # Update state
            state["market_data"] = market_data
            state["market_timestamp"] = datetime.now().isoformat()
            state["last_action"] = "data_collection_completed"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "data_collection",
                    "action": "collected_market_data",
                    "data_points": len(market_data),
                    "success": True,
                }
            )

        except Exception as e:
            state["error_state"] = f"Data collection failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    async def _analysis_node(self, state: TradingState) -> TradingState:
        """Node: Analyze market data and generate signals"""
        state["current_phase"] = TradingPhase.ANALYSIS.value

        try:
            # Delegate to Data Analyst Agent
            analysis_result = await self.data_analyst.analyze_market_data(
                state["market_data"]
            )

            # Update state with analysis
            if analysis_result.get("signals"):
                state["proposed_trade"] = analysis_result["signals"][
                    0
                ]  # Take top signal
                state["model_confidence"] = analysis_result["signals"][0].get(
                    "confidence", 0.5
                )

            state["last_action"] = "analysis_completed"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "analysis",
                    "action": "market_analysis",
                    "signals_found": len(analysis_result.get("signals", [])),
                    "top_confidence": state["model_confidence"],
                }
            )

        except Exception as e:
            state["error_state"] = f"Analysis failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    async def _risk_assessment_node(self, state: TradingState) -> TradingState:
        """Node: Assess risk of proposed trade"""
        state["current_phase"] = TradingPhase.RISK_ASSESSMENT.value

        try:
            # Delegate to Risk Control Agent
            risk_assessment = await self.risk_controller.assess_trade_risk(
                state["proposed_trade"], state
            )

            # Update risk snapshot
            state["risk_snapshot"] = risk_assessment["risk_snapshot"]
            state["last_action"] = "risk_assessment_completed"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "risk_assessment",
                    "action": "risk_assessment",
                    "risk_score": risk_assessment.get("risk_score", 0),
                    "recommendation": risk_assessment.get("recommendation", "hold"),
                }
            )

        except Exception as e:
            state["error_state"] = f"Risk assessment failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    def _risk_decision_router(self, state: TradingState) -> str:
        """Conditional router: Decide next step based on risk assessment"""

        # Check for errors
        if state["error_state"]:
            return "error_handling"

        # Check if we have a proposed trade
        if not state["proposed_trade"]:
            return "monitoring"  # No trade to consider, go to monitoring

        # Apply safety protocols
        safety_decision = self.safety.check_trade_safety(state["proposed_trade"], state)

        if safety_decision == "emergency_stop":
            return "error_handling"
        elif safety_decision == "reject":
            return "monitoring"  # Trade rejected, go back to monitoring
        else:
            return "trade_decision"  # Trade approved, proceed to decision

    async def _trade_decision_node(self, state: TradingState) -> TradingState:
        """Node: Make final trade decision"""
        state["current_phase"] = TradingPhase.TRADE_DECISION.value

        try:
            # Final decision logic (could be enhanced with ML)
            final_decision = await self._make_final_trade_decision(state)

            if final_decision["execute"]:
                state["proposed_trade"]["final_decision"] = "execute"
                state["proposed_trade"]["decision_time"] = datetime.now().isoformat()
            else:
                state["proposed_trade"] = None  # Cancel the trade

            state["last_action"] = "trade_decision_made"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "trade_decision",
                    "action": "final_decision",
                    "execute": final_decision["execute"],
                    "reasoning": final_decision.get("reasoning", ""),
                }
            )

        except Exception as e:
            state["error_state"] = f"Trade decision failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    async def _execution_node(self, state: TradingState) -> TradingState:
        """Node: Execute approved trades"""
        state["current_phase"] = TradingPhase.EXECUTION.value

        try:
            if state["proposed_trade"]:
                # Delegate to Execution Agent
                execution_result = await self.execution_agent.execute_trade(
                    state["proposed_trade"]
                )

                # Update state with execution result
                if execution_result["success"]:
                    state["trade_history"].append(execution_result["trade"])
                    state["open_positions"].append(execution_result["position"])
                    state["available_capital"] -= execution_result["trade"]["cost"]

                    # Add to experience buffer for learning
                    self._add_experience_to_buffer(state, execution_result)

                state["proposed_trade"] = None  # Clear proposed trade
                state["last_action"] = "execution_completed"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "execution",
                    "action": "trade_execution",
                    "success": execution_result.get("success", False),
                    "trade_id": execution_result.get("trade_id"),
                }
            )

        except Exception as e:
            state["error_state"] = f"Execution failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    async def _monitoring_node(self, state: TradingState) -> TradingState:
        """Node: Monitor positions and system health"""
        state["current_phase"] = TradingPhase.MONITORING.value

        try:
            # Delegate to Monitoring Agent
            monitoring_result = await self.monitoring_agent.monitor_system(state)

            # Update state with monitoring results
            state["portfolio_value"] = monitoring_result["portfolio_value"]
            state["total_pnl"] = monitoring_result["total_pnl"]
            state["performance_metrics"] = monitoring_result["performance_metrics"]

            state["last_action"] = "monitoring_completed"

            # Log decision
            state["decision_log"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": "monitoring",
                    "action": "system_monitoring",
                    "portfolio_value": state["portfolio_value"],
                    "total_pnl": state["total_pnl"],
                }
            )

        except Exception as e:
            state["error_state"] = f"Monitoring failed: {str(e)}"
            state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        return state

    async def _error_handling_node(self, state: TradingState) -> TradingState:
        """Node: Handle system errors"""
        state["current_phase"] = TradingPhase.ERROR_HANDLING.value

        # Log the error
        state["decision_log"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "phase": "error_handling",
                "action": "error_recovery",
                "error": state["error_state"],
                "recovery_action": "restart_cycle",
            }
        )

        # Clear error state and prepare for restart
        state["error_state"] = None
        state["proposed_trade"] = None
        state["last_action"] = "error_recovery_completed"

        return state

    async def _handle_system_error(
        self, state: TradingState, error: str
    ) -> TradingState:
        """Handle system-level errors"""
        state["error_state"] = f"System error: {error}"
        state["current_phase"] = TradingPhase.ERROR_HANDLING.value
        state["last_action"] = "system_error"

        # Trigger emergency stop if needed
        if "critical" in error.lower():
            self.safety.emergency_stop = True

        return state

    async def _make_final_trade_decision(self, state: TradingState) -> Dict[str, Any]:
        """Make final trade decision based on all available information"""

        # Simple decision logic (can be enhanced with ML models)
        confidence = state["model_confidence"]
        risk_score = state["risk_snapshot"].get("current_risk", 0)

        # Decision matrix
        if confidence > 0.8 and risk_score < 0.3:
            return {"execute": True, "reasoning": "High confidence, low risk"}
        elif confidence > 0.7 and risk_score < 0.2:
            return {"execute": True, "reasoning": "Good confidence, very low risk"}
        else:
            return {
                "execute": False,
                "reasoning": "Insufficient confidence or excessive risk",
            }

    def _add_experience_to_buffer(
        self, state: TradingState, execution_result: Dict[str, Any]
    ):
        """Add experience tuple to buffer for learning"""
        experience = {
            "timestamp": datetime.now().isoformat(),
            "state_snapshot": state.copy(),
            "action": "execute_trade",
            "reward": execution_result.get("immediate_pnl", 0),
            "next_state": None,  # Will be filled in next cycle
            "trade_id": execution_result.get("trade_id"),
        }

        state["experience_buffer"].append(experience)

        # Keep buffer size manageable
        if len(state["experience_buffer"]) > 1000:
            state["experience_buffer"] = state["experience_buffer"][-500:]


# Worker Agent Implementations


class DataAnalystAgent:
    """Worker agent: Collects and analyzes market data"""

    async def collect_market_data(self) -> Dict[str, Any]:
        """Collect current market data"""
        # Mock implementation - would connect to real data sources
        return {
            "AAPL": {"price": 175.43, "volume": 1000000, "change": 1.25},
            "MSFT": {"price": 380.12, "volume": 800000, "change": -0.50},
            "GOOGL": {"price": 140.25, "volume": 600000, "change": 0.75},
        }

    async def analyze_market_data(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze market data and generate trading signals"""
        signals = []

        for symbol, data in market_data.items():
            # Simple signal generation (would use sophisticated models)
            if data["change"] > 1.0:
                signals.append(
                    {
                        "symbol": symbol,
                        "action": "buy",
                        "confidence": 0.8,
                        "reasoning": "Positive momentum",
                        "size": 10000,  # $10k position
                    }
                )

        return {"signals": signals}


class RiskControlAgent:
    """Worker agent: Manages risk assessment and control"""

    async def assess_trade_risk(
        self, proposed_trade: Dict[str, Any], state: TradingState
    ) -> Dict[str, Any]:
        """Assess risk of proposed trade"""

        # Calculate risk metrics
        portfolio_value = state["portfolio_value"]
        trade_size = proposed_trade.get("size", 0)
        current_positions = len(state["open_positions"])

        risk_score = (trade_size / portfolio_value) * 0.5 + (
            current_positions / 10
        ) * 0.3

        risk_snapshot = {
            "current_risk": risk_score,
            "portfolio_exposure": (
                trade_size / portfolio_value if portfolio_value > 0 else 0
            ),
            "position_count": current_positions,
            "daily_pnl": state["total_pnl"],
        }

        recommendation = "approve" if risk_score < 0.3 else "reject"

        return {
            "risk_score": risk_score,
            "risk_snapshot": risk_snapshot,
            "recommendation": recommendation,
        }


class ExecutionAgent:
    """Worker agent: Handles trade execution"""

    async def execute_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the proposed trade"""

        trade_id = f"trade_{uuid.uuid4().hex[:8]}"

        # Mock execution (would connect to real broker)
        execution_result = {
            "success": True,
            "trade_id": trade_id,
            "trade": {
                **trade,
                "trade_id": trade_id,
                "executed_at": datetime.now().isoformat(),
                "executed_price": 175.43,  # Mock price
                "cost": trade.get("size", 0),
            },
            "position": {
                "symbol": trade.get("symbol"),
                "size": trade.get("size", 0),
                "entry_price": 175.43,
                "trade_id": trade_id,
                "opened_at": datetime.now().isoformat(),
            },
            "immediate_pnl": 0,  # Would be calculated from price movement
        }

        return execution_result


class MonitoringAgent:
    """Worker agent: Monitors system health and portfolio performance"""

    async def monitor_system(self, state: TradingState) -> Dict[str, Any]:
        """Monitor system and portfolio"""

        # Calculate portfolio metrics
        portfolio_value = state["portfolio_value"]
        total_pnl = state["total_pnl"]

        # Performance metrics (simplified)
        performance_metrics = {
            "sharpe_ratio": 1.5,  # Mock calculation
            "win_rate": 0.65,
            "total_trades": len(state["trade_history"]),
            "daily_return": total_pnl / portfolio_value if portfolio_value > 0 else 0,
        }

        return {
            "portfolio_value": portfolio_value,
            "total_pnl": total_pnl,
            "performance_metrics": performance_metrics,
            "system_health": "healthy",
        }


class StateStorage:
    """Handles state persistence and recovery"""

    def __init__(self):
        self.storage_file = "trading_state.json"

    async def save_state(self, state: TradingState):
        """Save state to persistent storage"""
        try:
            with open(self.storage_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            print(f"Failed to save state: {e}")

    async def load_state(self) -> Optional[TradingState]:
        """Load state from persistent storage"""
        try:
            with open(self.storage_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"Failed to load state: {e}")
            return None


# Factory function
def create_professional_orchestrator() -> SupervisorOrchestrator:
    """Create a professional trading orchestrator"""
    return SupervisorOrchestrator()
