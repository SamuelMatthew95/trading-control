---
name: professional-trading-orchestrator
description: Professional state-machine-based trading orchestrator using LangGraph with Supervisor/Worker architecture. Use when you need production-grade trading automation with proper state management, safety protocols, and risk control like "run trading cycle" or "analyze market with risk assessment".
---

# Professional Trading Orchestrator

Production-grade state-machine-based trading system using LangGraph for professional orchestration with proper state management and safety protocols.

## Architecture Overview

### State Machine Design
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Data Collection │───▶│    Analysis     │───▶│ Risk Assessment │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Monitoring    │◀───│    Execution    │◀───│ Trade Decision  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌─────────────────┐
│ Error Handling  │◀───│   (Loop Back)   │
└─────────────────┘    └─────────────────┘
```

### Supervisor/Worker Pattern

#### Supervisor (Central Brain)
- **State Management**: Single Source of Truth for all trading data
- **Workflow Orchestration**: Routes events to specialist agents
- **Safety Enforcement**: Hard-coded risk protocols and emergency stops
- **Decision Logging**: Complete audit trail of all trading decisions

#### Worker Agents (Specialized Tools)
- **Data Analyst**: Market data collection → sentiment/signal scores
- **Risk Controller**: Proposed trade → portfolio exposure → Approve/Reject
- **Execution Agent**: Approved trade → broker execution → confirmation
- **Monitoring Agent**: Portfolio tracking → performance metrics → health checks

## Quick Start
```python
from professional_trading_orchestrator import create_professional_orchestrator

# Create professional orchestrator
orchestrator = create_professional_orchestrator()

# Run trading cycle
state = await orchestrator.run_trading_cycle()

print(f"Portfolio Value: ${state['portfolio_value']:,.2f}")
print(f"Current Phase: {state['current_phase']}")
print(f"Last Action: {state['last_action']}")
```

## State Management

### TradingState (Single Source of Truth)
```python
class TradingState(TypedDict):
    # Core market data
    market_data: Dict[str, Any]              # Current prices, order books
    market_timestamp: str                    # When market data was last updated
    
    # Portfolio state
    open_positions: List[Dict[str, Any]]     # What we currently hold
    portfolio_value: float                   # Account balance + position value
    available_capital: float                 # Capital available for new trades
    total_pnl: float                         # Total profit/loss
    
    # Risk management
    risk_snapshot: Dict[str, Any]            # Current exposure/stop-loss limits
    max_position_size: float                 # Maximum position size
    daily_loss_limit: float                  # Daily loss limit
    current_daily_loss: float                # Current daily loss
    
    # Trade execution
    proposed_trade: Optional[Dict[str, Any]] # Trade currently being considered
    trade_history: List[Dict[str, Any]]      # History of all trades
    pending_orders: List[Dict[str, Any]]     # Orders waiting execution
    
    # Decision tracking
    decision_log: List[Dict[str, Any]]        # History of why we took specific actions
    current_phase: str                       # Current phase in the state machine
    last_action: Optional[str]               # Last action taken
    error_state: Optional[str]               # Any error conditions
    
    # Learning and analytics
    experience_buffer: List[Dict[str, Any]]  # (state, action, reward, next_state) tuples
    performance_metrics: Dict[str, float]    # Sharpe ratio, win rate, etc.
    model_confidence: float                  # Current model confidence score
```

### State Persistence
- **Automatic Persistence**: State saved after every cycle
- **Recovery Capability**: System can restart from any saved state
- **Audit Trail**: Complete history of all state transitions

## Safety Protocols

### Hard-Coded Risk Management (Not Learned)
```python
class SafetyProtocol:
    max_daily_loss: float = 1000.0           # Never lose more than $1000 per day
    max_position_size: float = 10000.0      # Never allocate more than $10k to one asset
    max_portfolio_risk: float = 0.2         # Never risk more than 20% of portfolio
    min_confidence_threshold: float = 0.7    # Only trade with 70%+ confidence
    emergency_stop: bool = False             # Global emergency stop flag
```

### Safety Checks
1. **Daily Loss Limit**: Automatic stop if daily loss exceeds $1000
2. **Position Size Limits**: Maximum $10k per single position
3. **Portfolio Risk**: Never risk more than 20% of total portfolio
4. **Confidence Threshold**: Only execute trades with 70%+ confidence
5. **Emergency Stop**: Global kill switch for critical situations

## Learning and Analytics

### Experience Replay Buffer
```python
experience_buffer = [
    {
        "timestamp": "2024-01-15T10:00:00",
        "state_snapshot": {...},
        "action": "execute_trade",
        "reward": 150.25,
        "next_state": {...},
        "trade_id": "trade_abc123"
    }
]
```

### Performance Metrics
- **Sharpe Ratio**: Risk-adjusted returns
- **Win Rate**: Percentage of profitable trades
- **Daily Return**: Daily portfolio performance
- **Risk Score**: Current portfolio risk exposure

## Usage Examples

### Basic Trading Cycle
```python
# Initialize orchestrator
orchestrator = create_professional_orchestrator()

# Run continuous trading cycles
while True:
    try:
        state = await orchestrator.run_trading_cycle()
        
        # Monitor results
        print(f"Phase: {state['current_phase']}")
        print(f"Portfolio: ${state['portfolio_value']:,.2f}")
        print(f"P&L: ${state['total_pnl']:,.2f}")
        
        # Check for emergency conditions
        if orchestrator.safety.emergency_stop:
            print("Emergency stop triggered!")
            break
            
        await asyncio.sleep(60)  # Wait 1 minute between cycles
        
    except KeyboardInterrupt:
        print("Trading stopped by user")
        break
```

### State Analysis
```python
# Load and analyze trading state
state = await orchestrator.state_storage.load_state()

# Recent decisions
recent_decisions = state["decision_log"][-10:]
for decision in recent_decisions:
    print(f"{decision['timestamp']}: {decision['action']} - {decision.get('reasoning', '')}")

# Performance metrics
metrics = state["performance_metrics"]
print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
print(f"Win Rate: {metrics['win_rate']:.1%}")
print(f"Total Trades: {metrics['total_trades']}")
```

### Risk Monitoring
```python
# Check current risk exposure
risk_snapshot = state["risk_snapshot"]
print(f"Current Risk: {risk_snapshot['current_risk']:.2f}")
print(f"Portfolio Exposure: {risk_snapshot['portfolio_exposure']:.1%}")

# Safety protocol status
safety = orchestrator.safety
print(f"Emergency Stop: {safety.emergency_stop}")
print(f"Daily Loss: ${state['current_daily_loss']:.2f} / ${safety.max_daily_loss}")
```

## Integration with Existing System

### Replace Legacy Orchestrator
```python
# Old approach
from trading_agent_orchestration.scripts.supervisor_orchestrator import SupervisorOrchestrator

# New professional approach
from professional_trading_orchestrator import create_professional_orchestrator

# The new system provides:
# - Proper state management
# - Safety protocols
# - Learning capabilities
# - Professional error handling
```

### Claude Code Integration
```python
# Can be called from Claude Code integration
async def handle_professional_trading_command(params):
    orchestrator = create_professional_orchestrator()
    state = await orchestrator.run_trading_cycle()
    
    return {
        "status": "success",
        "portfolio_value": state["portfolio_value"],
        "current_phase": state["current_phase"],
        "last_action": state["last_action"],
        "decision_count": len(state["decision_log"])
    }
```

## Production Deployment

### Environment Setup
```bash
# Required dependencies
pip install langgraph  # State machine orchestration
pip install redis     # State persistence (optional)
pip install psycopg2  # Database for state storage
```

### Configuration
```python
# Production configuration
orchestrator = create_professional_orchestrator()

# Configure safety protocols
orchestrator.safety.max_daily_loss = 5000.0  # Higher for production
orchestrator.safety.max_position_size = 50000.0
orchestrator.safety.emergency_stop = False
```

### Monitoring and Alerting
```python
# Monitor system health
async def monitor_orchestrator():
    while True:
        state = await orchestrator.state_storage.load_state()
        
        # Check for issues
        if state.get("error_state"):
            await send_alert(f"Trading system error: {state['error_state']}")
        
        if state["current_daily_loss"] > orchestrator.safety.max_daily_loss * 0.8:
            await send_alert("Approaching daily loss limit")
        
        await asyncio.sleep(300)  # Check every 5 minutes
```

## Performance Characteristics

### State Machine Efficiency
- **Cycle Time**: <100ms for complete trading cycle
- **State Persistence**: <10ms for state save/load
- **Memory Usage**: <100MB for state and buffers
- **Scalability**: Handles 1000+ positions efficiently

### Safety and Reliability
- **Error Recovery**: Automatic recovery from all error states
- **State Consistency**: ACID-compliant state management
- **Audit Trail**: Complete decision logging with timestamps
- **Emergency Response**: <50ms emergency stop response

## Best Practices

### State Management
1. **Always persist state** after every cycle
2. **Monitor state size** to prevent memory bloat
3. **Validate state integrity** on load
4. **Backup state regularly** for disaster recovery

### Safety Protocols
1. **Never disable safety checks** in production
2. **Monitor emergency conditions** continuously
3. **Test safety protocols** regularly
4. **Document all safety rules** clearly

### Learning and Analytics
1. **Review experience buffer** weekly
2. **Analyze decision patterns** monthly
3. **Update confidence thresholds** based on performance
4. **Backtest strategy changes** before deployment

---
*See [references/state-machine-design.md](references/state-machine-design.md) for detailed state machine implementation and [references/safety-protocols.md](references/safety-protocols.md) for comprehensive safety guidelines.*
