---
name: deterministic-trading-system
description: Deterministic trading system with no fallbacks, proper learning mechanisms, agent ranking, and automated AI communication protocols. Use when you need reliable trading automation without randomness, with self-improving agents that learn from mistakes and collaborate through formal protocols like "execute agent task with learning" or "check agent rankings and performance".
---

# Deterministic Trading System

Production-grade trading system with deterministic learning, agent ranking, and formal communication protocols. No fallbacks, no randomness, no trace logging - only safe failures and structured learning.

## Architecture Overview

### Deterministic Design Principles
- **No Randomness**: All decisions are deterministic based on data
- **No Fallbacks**: System fails safely without random fallbacks
- **No Trace Logging**: No logging, only structured execution records
- **Safe Failures**: Clear error states without recovery attempts

### Core Components

#### Agent Performance Ranking
```
A+ (Excellent)    ≥ 95% score
A  (Good)          ≥ 85% score
B  (Satisfactory)  ≥ 75% score
C  (Needs Improvement) ≥ 65% score
D  (Unsatisfactory) ≥ 50% score
F  (Failing)       < 50% score
```

#### Learning Mechanisms
- **Learning Signals**: Deterministic signals from execution results
- **Agent Models**: Learned parameters updated based on performance
- **Performance-Based Updates**: Adjust confidence thresholds and timeouts
- **Mistake Analysis**: Pattern recognition in failed executions

#### Communication Protocol
- **Formal Messages**: Structured agent-to-agent communication
- **Priority Queue**: Messages processed by priority (1=highest)
- **Correlation Tracking**: Message tracking and response handling
- **Error Handling**: Failed communications don't crash system

## Quick Start
```python
from deterministic_trading_system import create_deterministic_trading_system

# Create deterministic system
system = create_deterministic_trading_system()

# Execute agent task with learning
result = await system.execute_agent_task("data_analyst", "analyze_market", {
    "symbol": "AAPL",
    "indicators": ["RSI", "MACD"]
})

# Check system status
status = system.get_system_status()
print(f"Top Agent: {status['top_agents'][0]['agent_id']}")
print(f"Success Rate: {status['metrics']['successful_executions'] / status['metrics']['total_executions']:.1%}")
```

## Agent Ranking System

### Performance Metrics
```python
@dataclass(frozen=True)
class AgentMetrics:
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
```

### Ranking Calculation
```python
# Deterministic ranking score
ranking_score = (
    accuracy_score * 0.4 +
    reliability_score * 0.3 +
    efficiency_score * 0.3
)
```

### Performance Tracking
- **Real-time Updates**: Rankings updated after each execution
- **Historical Analysis**: Last 100 executions for current metrics
- **Grade Assignment**: Automatic grade based on performance score
- **Comparative Analysis**: Agents ranked against each other

## Learning Mechanisms

### Learning Signals
```python
@dataclass
class LearningSignal:
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
```

### Deterministic Learning Updates
```python
def calculate_agent_update(agent_id: str) -> Dict[str, Any]:
    # Analyze recent performance
    recent_signals = agent_signals[-100:]
    success_rate = sum(1 for s in recent_signals if s.success) / len(recent_signals)
    
    # Determine learning direction (no randomness)
    if success_rate < 0.6:
        learning_direction = "decrease_confidence"
        adjustment_factor = 0.1
    elif success_rate > 0.9 and avg_execution_time < 1000:
        learning_direction = "increase_confidence"
        adjustment_factor = 0.05
    else:
        learning_direction = "maintain"
        adjustment_factor = 0.0
    
    # Apply deterministic updates
    updates = {}
    if learning_direction == "decrease_confidence":
        updates["confidence_threshold"] = min(0.95, current + adjustment_factor)
        updates["timeout_ms"] = min(10000, current + 1000)
    elif learning_direction == "increase_confidence":
        updates["confidence_threshold"] = max(0.5, current - adjustment_factor)
        updates["timeout_ms"] = max(1000, current - 500)
    
    return updates
```

### Model Parameter Updates
- **Confidence Threshold**: Adjusted based on success rate
- **Timeout Settings**: Adapted based on execution performance
- **Risk Tolerance**: Modified based on error patterns
- **Retry Logic**: Updated based on failure analysis

## Agent Communication Protocol

### Message Structure
```python
@dataclass(frozen=True)
class Message:
    sender_id: str
    receiver_id: str
    message_type: str
    payload: Dict[str, Any]
    priority: int  # 1=highest, 10=lowest
    correlation_id: str
    timestamp: str
    requires_response: bool = False
```

### Communication Types
- **Performance Query**: Agents request performance data from peers
- **Learning Update**: Manager sends learning updates to agents
- **Collaboration Request**: Agents request assistance from peers
- **Best Practice Sharing**: Agents share successful strategies

### Message Processing
```python
async def process_messages(self) -> List[Dict[str, Any]]:
    results = []
    
    while self.message_queue:
        message = self.message_queue.pop(0)
        
        try:
            if message.message_type in self.message_handlers:
                handler = self.message_handlers[message.message_type]
                result = await handler(message)
                results.append({"success": True, "result": result})
            else:
                results.append({"success": False, "error": "No handler"})
        except Exception as e:
            results.append({"success": False, "error": str(e)})
    
    return results
```

## Self-Improving Agents

### Base Agent Capabilities
```python
class SelfImprovingAgent:
    async def execute_with_learning(self, action: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # Execute action
        result = await self._execute_action(action, input_data, model)
        
        # Record execution
        self.ranking_system.record_execution(self.agent_id, execution_result)
        
        # Create learning signal
        learning_signal = LearningSignal.from_execution(...)
        self.learning_manager.add_learning_signal(learning_signal)
        
        # Check for learning updates
        learning_update = self.learning_manager.calculate_agent_update(self.agent_id)
        if learning_update:
            await self._apply_learning_updates(learning_update)
        
        return result
```

### Collaboration Handlers
- **Performance Query**: Share performance metrics with peers
- **Learning Update**: Apply learning updates from manager
- **Collaboration Request**: Assist other agents with tasks
- **Best Practice Sharing**: Share successful strategies

### Mistake Analysis
```python
def _get_error_patterns(self) -> List[Dict[str, Any]]:
    history = self.ranking_system.execution_history.get(self.agent_id, [])
    errors = [h for h in history if not h.get("success", False)]
    
    # Analyze error patterns (deterministic)
    error_types = {}
    for error in errors:
        error_type = error.get("error_type", "unknown")
        error_types[error_type] = error_types.get(error_type, 0) + 1
    
    return [
        {"error_type": error_type, "count": count}
        for error_type, count in error_types.items()
    ]
```

## Usage Examples

### Basic Agent Execution
```python
# Execute task with learning
result = await system.execute_agent_task("data_analyst", "analyze_market", {
    "symbol": "AAPL",
    "indicators": ["RSI", "MACD"]
})

if result["success"]:
    print(f"Analysis completed: {result['result']}")
    print(f"Agent rank: #{result['agent_rank']}")
else:
    print(f"Execution failed: {result['error']}")
```

### Agent Performance Analysis
```python
# Get top performing agents
top_agents = system.ranking_system.get_top_agents(5)

for agent in top_agents:
    print(f"{agent['agent_id']}: Grade {agent['grade']}, Score {agent['ranking_score']:.2f}")

# Get specific agent metrics
metrics = system.ranking_system.agent_metrics.get("data_analyst")
if metrics:
    print(f"Accuracy: {metrics.accuracy_score:.1%}")
    print(f"Reliability: {metrics.reliability_score:.1%}")
    print(f"Efficiency: {metrics.efficiency_score:.1%}")
```

### Learning Analysis
```python
# Get learning updates
learning_updates = system.learning_manager.learning_updates[-10:]

for update in learning_updates:
    print(f"Agent: {update['agent_id']}")
    print(f"Direction: {update['learning_direction']}")
    print(f"Success Rate: {update['success_rate']:.1%}")
    print(f"Updates: {update['updates']}")
```

### Agent Communication
```python
# Send performance query
message = AgentCommunicationProtocol.Message.create(
    "manager",
    "data_analyst",
    "performance_query",
    {"detailed": True},
    priority=2
)

system.communication_protocol.send_message(message)
results = await system.process_agent_communications()
```

## System Monitoring

### Performance Metrics
```python
status = system.get_system_status()

print(f"Total Executions: {status['metrics']['total_executions']}")
print(f"Success Rate: {status['metrics']['successful_executions'] / status['metrics']['total_executions']:.1%}")
print(f"Agent Count: {status['agent_count']}")
print(f"Average Score: {status['ranking_summary']['average_score']:.2f}")
```

### Agent Rankings
```python
# Get current rankings
rankings = system.ranking_system.rankings

for i, agent in enumerate(rankings[:10]):
    print(f"#{i+1}: {agent['agent_id']} - Grade {agent['grade']} - Score {agent['ranking_score']:.2f}")
```

### Learning Progress
```python
# Get learning progress
learning_signals = system.learning_manager.learning_signals
recent_signals = learning_signals[-100:]

success_rate = sum(1 for s in recent_signals if s.success) / len(recent_signals)
avg_reward = sum(s.reward for s in recent_signals) / len(recent_signals)

print(f"Recent Success Rate: {success_rate:.1%}")
print(f"Average Reward: {avg_reward:.2f}")
```

## Safety and Reliability

### Safe Failure Modes
- **No Random Fallbacks**: System doesn't attempt random recovery
- **Clear Error States**: All errors are clearly reported
- **No Trace Logging**: No performance-impacting logging
- **Deterministic Behavior**: Same input always produces same output

### Error Handling
```python
try:
    result = await system.execute_agent_task("agent_id", "action", input_data)
except Exception as e:
    # System fails safely - no fallbacks
    return {
        "success": False,
        "error": str(e),
        "system_state": "failed"
    }
```

### Performance Guarantees
- **Deterministic Execution**: No randomness in decision making
- **Bounded Execution**: All operations have time limits
- **Memory Management**: Bounded memory usage for all components
- **Scalable Design**: System scales with agent count

## Integration with Existing Systems

### Replace Legacy Components
```python
# Old approach (with fallbacks and randomness)
try:
    result = legacy_system.analyze(data)
except Exception:
    result = fallback_analysis(data)  # Random fallback

# New deterministic approach
result = await system.execute_agent_task("data_analyst", "analyze", data)
if not result["success"]:
    # Handle failure deterministically
    return {"status": "failed", "error": result["error"]}
```

### Production Deployment
```python
# Create system instance
system = create_deterministic_trading_system()

# Register agents
system.register_agent(DataAnalystAgent("data_analyst", ...))
system.register_agent(RiskControlAgent("risk_control", ...))

# Run continuous execution
while True:
    # Execute tasks
    result = await system.execute_agent_task("data_analyst", "analyze", market_data)
    
    # Process communications
    await system.process_agent_communications()
    
    # Monitor performance
    status = system.get_system_status()
    if status["metrics"]["success_rate"] < 0.8:
        # Handle low performance deterministically
        await handle_low_performance(status)
    
    await asyncio.sleep(60)  # Wait between cycles
```

## Best Practices

### Agent Development
- **Implement _execute_action**: Core execution logic
- **Handle Learning Updates**: Apply parameter changes
- **Share Best Practices**: Communicate successful strategies
- **Analyze Mistakes**: Identify and share error patterns

### System Management
- **Monitor Rankings**: Track agent performance over time
- **Analyze Learning**: Review learning signal patterns
- **Handle Communications**: Process messages efficiently
- **Maintain Safety**: Never introduce randomness or fallbacks

### Performance Optimization
- **Bounded Resources**: Limit memory and CPU usage
- **Efficient Communication**: Use message priorities effectively
- **Learning Rate**: Balance learning speed with stability
- **Agent Selection**: Use top-ranked agents for critical tasks

---
*See [references/learning-algorithms.md](references/learning-algorithms.md) for detailed learning mechanisms and [references/communication-protocols.md](references/communication-protocols.md) for agent communication specifications.*
