# State Machine Design

## LangGraph Implementation

The professional trading orchestrator uses LangGraph to implement a deterministic state machine that ensures reliable, traceable trading operations.

### State Graph Structure

```python
workflow = StateGraph(TradingState)

# Nodes (Worker Agents)
workflow.add_node("data_collection", self._data_collection_node)
workflow.add_node("analysis", self._analysis_node)
workflow.add_node("risk_assessment", self._risk_assessment_node)
workflow.add_node("trade_decision", self._trade_decision_node)
workflow.add_node("execution", self._execution_node)
workflow.add_node("monitoring", self._monitoring_node)
workflow.add_node("error_handling", self._error_handling_node)

# Edges (State Transitions)
workflow.set_entry_point("data_collection")
workflow.add_edge("data_collection", "analysis")
workflow.add_edge("analysis", "risk_assessment")
workflow.add_conditional_edges("risk_assessment", self._risk_decision_router)
workflow.add_edge("trade_decision", "execution")
workflow.add_edge("execution", "monitoring")
workflow.add_edge("monitoring", "data_collection")  # Cycle back
workflow.add_edge("error_handling", "data_collection")  # Recovery
```

### Node Implementation Pattern

Each node follows a consistent pattern:

1. **Phase Identification**: Set current phase in state
2. **Worker Delegation**: Call appropriate worker agent
3. **State Update**: Update state with worker results
4. **Decision Logging**: Record all decisions with timestamps
5. **Error Handling**: Graceful error handling with state recovery

```python
async def _analysis_node(self, state: TradingState) -> TradingState:
    """Node: Analyze market data and generate signals"""
    state["current_phase"] = TradingPhase.ANALYSIS.value
    
    try:
        # Delegate to Data Analyst Agent
        analysis_result = await self.data_analyst.analyze_market_data(state["market_data"])
        
        # Update state
        if analysis_result.get("signals"):
            state["proposed_trade"] = analysis_result["signals"][0]
            state["model_confidence"] = analysis_result["signals"][0].get("confidence", 0.5)
        
        state["last_action"] = "analysis_completed"
        
        # Log decision
        state["decision_log"].append({
            "timestamp": datetime.now().isoformat(),
            "phase": "analysis",
            "action": "market_analysis",
            "signals_found": len(analysis_result.get("signals", [])),
            "top_confidence": state["model_confidence"]
        })
        
    except Exception as e:
        state["error_state"] = f"Analysis failed: {str(e)}"
        state["current_phase"] = TradingPhase.ERROR_HANDLING.value
    
    return state
```

### Conditional Routing

The state machine uses conditional routing to make decisions:

```python
def _risk_decision_router(self, state: TradingState) -> str:
    """Conditional router: Decide next step based on risk assessment"""
    
    # Check for errors
    if state["error_state"]:
        return "error_handling"
    
    # Check if we have a proposed trade
    if not state["proposed_trade"]:
        return "monitoring"
    
    # Apply safety protocols
    safety_decision = self.safety.check_trade_safety(state["proposed_trade"], state)
    
    if safety_decision == "emergency_stop":
        return "error_handling"
    elif safety_decision == "reject":
        return "monitoring"
    else:
        return "trade_decision"
```

## State Management

### TradingState Structure

The state object is the Single Source of Truth:

```python
class TradingState(TypedDict):
    # Core market data
    market_data: Dict[str, Any]
    market_timestamp: str
    
    # Portfolio state
    open_positions: List[Dict[str, Any]]
    portfolio_value: float
    available_capital: float
    total_pnl: float
    
    # Risk management
    risk_snapshot: Dict[str, Any]
    max_position_size: float
    daily_loss_limit: float
    current_daily_loss: float
    
    # Trade execution
    proposed_trade: Optional[Dict[str, Any]]
    trade_history: List[Dict[str, Any]]
    pending_orders: List[Dict[str, Any]]
    
    # Decision tracking
    decision_log: List[Dict[str, Any]]
    current_phase: str
    last_action: Optional[str]
    error_state: Optional[str]
    
    # Learning and analytics
    experience_buffer: List[Dict[str, Any]]
    performance_metrics: Dict[str, float]
    model_confidence: float
    
    # System metadata
    orchestrator_id: str
    session_id: str
    last_updated: str
```

### State Persistence

State is automatically persisted after each cycle:

```python
class StateStorage:
    def __init__(self):
        self.storage_file = "trading_state.json"
    
    async def save_state(self, state: TradingState):
        """Save state to persistent storage"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            print(f"Failed to save state: {e}")
    
    async def load_state(self) -> Optional[TradingState]:
        """Load state from persistent storage"""
        try:
            with open(self.storage_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"Failed to load state: {e}")
            return None
```

## Error Handling and Recovery

### Error States

The state machine handles errors gracefully:

1. **Detection**: Each node catches exceptions and sets error_state
2. **Routing**: Conditional router detects errors and routes to error_handling
3. **Recovery**: Error handling node clears errors and restarts cycle
4. **Logging**: All errors are logged in decision_log

### Emergency Procedures

```python
async def _handle_system_error(self, state: TradingState, error: str) -> TradingState:
    """Handle system-level errors"""
    state["error_state"] = f"System error: {error}"
    state["current_phase"] = TradingPhase.ERROR_HANDLING.value
    state["last_action"] = "system_error"
    
    # Trigger emergency stop if needed
    if "critical" in error.lower():
        self.safety.emergency_stop = True
    
    return state
```

## Performance Optimization

### State Machine Efficiency

- **Deterministic Execution**: Same input always produces same output
- **Minimal State Overhead**: Only essential data stored in state
- **Efficient Persistence**: JSON serialization with compression
- **Memory Management**: Experience buffer size limited to prevent bloat

### Concurrent Execution

While the state machine itself is single-threaded for consistency, worker agents can execute concurrently:

```python
async def _data_collection_node(self, state: TradingState) -> TradingState:
    """Node: Collect market data"""
    
    # Collect data from multiple sources concurrently
    tasks = [
        self.data_analyst.collect_market_data(),
        self.data_analyst.collect_sentiment_data(),
        self.data_analyst.collect_economic_data()
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results and update state
    # ...
```

## Testing and Validation

### State Machine Testing

```python
async def test_state_machine_flow():
    """Test complete state machine flow"""
    orchestrator = create_professional_orchestrator()
    
    # Mock market data
    initial_state = await orchestrator._initialize_state()
    initial_state["market_data"] = {"AAPL": {"price": 175.43, "change": 2.5}}
    
    # Run cycle
    final_state = await orchestrator.run_trading_cycle(initial_state)
    
    # Validate state transitions
    assert final_state["current_phase"] == TradingPhase.MONITORING.value
    assert final_state["last_action"] == "monitoring_completed"
    assert len(final_state["decision_log"]) > 0
```

### Safety Protocol Testing

```python
async def test_emergency_stop():
    """Test emergency stop functionality"""
    orchestrator = create_professional_orchestrator()
    
    # Trigger emergency stop
    orchestrator.safety.emergency_stop = True
    
    # Run cycle
    state = await orchestrator.run_trading_cycle()
    
    # Should reject all trades
    assert state["proposed_trade"] is None
    assert any("emergency" in log["action"].lower() for log in state["decision_log"])
```

This state machine design ensures reliable, deterministic trading operations with proper error handling and recovery mechanisms.
