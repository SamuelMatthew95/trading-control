# Scalable Architecture Documentation

## Overview

The trading system is designed with a scalable, modular architecture that makes it easy to:
- Test individual components
- Debug issues quickly
- Add new features
- Monitor agent performance
- Understand what's happening in the system

## Architecture Principles

### 1. Clear Separation of Concerns

```
src/
├── core/                    # Fundamental utilities (no business logic)
│   ├── stateful_logging_system.py  # Database persistence, enums, metrics
│   ├── config.py                   # Configuration management
│   ├── logger.py                   # Centralized logging
│   └── main.py                     # Application entry point
├── system/                  # Production orchestration
│   ├── professional_trading_orchestrator.py  # State machine orchestrator
│   ├── production_trading_system.py          # Production API
│   └── claude_code_template.py                # Claude integration
└── trading-*/              # Skills (modular agents)
    ├── trading-market-data/           # Data collection agents
    ├── trading-data-validation/       # Data validation agents
    ├── trading-agent-orchestration/   # Orchestration agents
    ├── trading-system-monitoring/     # Monitoring agents
    └── trading-professional-orchestrator/  # Professional orchestrator skill
```

### 2. Observable Design

Every component is designed to be observable:

#### **Stateful Logging System**
```python
# All events are logged with structured data
await logger.log_agent_execution(
    agent_id="data_analyst",
    execution_id="exec_123",
    action="analyze_market",
    input_data={"symbol": "AAPL"},
    output_data={"signal": "buy"},
    success=True,
    execution_time_ms=150
)

# Easy to query what happened
history = await db.get_agent_history("data_analyst", limit=10)
metrics = await db.get_performance_metrics("data_analyst", metric_type=PerformanceMetric.SUCCESS_RATE)
```

#### **Enum-Based Measurements**
```python
class EventType(Enum):
    AGENT_EXECUTION = "agent_execution"
    MISTAKE_ANALYSIS = "mistake_analysis"
    LEARNING_SESSION = "learning_session"
    TEAM_FORMATION = "team_formation"

class AgentStatus(Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    LEARNING = "learning"
    COLLABORATING = "collaborating"
    ERROR = "error"
    RETIRED = "retired"
```

### 3. Modular Agent Design

Each agent is a self-contained skill:

```
trading-market-data/
├── SKILL.md              # Documentation
├── scripts/
│   ├── __init__.py      # Public API
│   └── market_data.py   # Implementation
└── references/
    └── api-guide.md     # Detailed documentation
```

## Testing Strategy

### 1. Unit Tests for Core Components

```python
class TestStatefulLoggingSystem:
    """Test core logging functionality"""
    
    @pytest_asyncio.fixture
    async def temp_db(self):
        """Isolated test database"""
        db_manager, logger, test_manager = create_stateful_logging_system()
        yield db_manager, logger, test_manager
        # Cleanup automatically
    
    async def test_agent_execution_logging(self, temp_db):
        """Test that agent executions are logged correctly"""
        _, logger, _ = temp_db
        
        await logger.log_agent_execution(
            agent_id="test_agent",
            execution_id="exec_001", 
            action="test_action",
            input_data={"test": "data"},
            success=True,
            execution_time_ms=100
        )
        
        # Verify it was logged
        history = await logger.db.get_execution_history(agent_id="test_agent")
        assert len(history) >= 1
        assert history[0]["success"] == True
```

### 2. Integration Tests for System Components

```python
class TestIntegration:
    """Test how components work together"""
    
    async def test_core_system_integration(self):
        """Test logging + orchestrator integration"""
        db_manager, logger, _ = create_stateful_logging_system()
        orchestrator = create_professional_orchestrator()
        
        # Execute orchestrator cycle
        state = await orchestrator.run_trading_cycle()
        
        # Log the execution
        await logger.log_agent_execution(
            "orchestrator", "cycle_001", "run_cycle",
            {}, {"result": "success"}, True, 200
        )
        
        # Verify both systems worked
        assert state["current_phase"] == TradingPhase.MONITORING.value
        history = await logger.db.get_execution_history(agent_id="orchestrator")
        assert len(history) >= 1
```

### 3. Error Scenario Testing

```python
async def test_error_handling_and_recovery(self):
    """Test that errors are handled gracefully"""
    
    # Simulate error condition
    state = await orchestrator._initialize_state()
    state["error_state"] = "Database connection failed"
    
    # Run error handling
    result = await orchestrator._error_handling_node(state)
    
    # Verify error was handled
    assert result["current_phase"] == TradingPhase.ERROR_HANDLING.value
    assert result["error_state"] is None  # Should be cleared
    assert result["last_action"] == "error_recovery_completed"
```

## Debugging and Monitoring

### 1. Database Queries for Debugging

```python
# Find what an agent did recently
recent_activity = await db.get_agent_history("data_analyst", hours=1)

# Check agent performance trends
performance_trend = await db.get_performance_metrics(
    "data_analyst", 
    metric_type=PerformanceMetric.SUCCESS_RATE,
    hours=24
)

# Get system-wide summary
system_status = await db.get_system_summary()
```

### 2. Error Analysis

```python
# Find recent errors
error_logs = await db.get_agent_history(
    agent_id="risk_controller", 
    hours=24
)
error_logs = [log for log in error_logs if log["log_level"] == "error"]

# Analyze error patterns
error_patterns = {}
for log in error_logs:
    pattern = log["metadata"].get("error_type", "unknown")
    error_patterns[pattern] = error_patterns.get(pattern, 0) + 1
```

### 3. Performance Monitoring

```python
# Get agent rankings
top_agents = ranking_system.get_top_agents(5)

# Check learning progress
learning_progress = database.get_agent_learning_progress("data_analyst")

# Monitor team effectiveness
team_performance = await db.get_team_performance_metrics(team_id="team_001")
```

## Scalability Features

### 1. Horizontal Scalability

```python
# Multiple orchestrator instances can run
orchestrator1 = create_professional_orchestrator()
orchestrator2 = create_professional_orchestrator()

# Each with its own state storage
orchestrator1.state_storage = StateStorage("orchestrator1_state.json")
orchestrator2.state_storage = StateStorage("orchestrator2_state.json")
```

### 2. Database Scalability

```python
# SQLite for development, PostgreSQL for production
if settings.environment == "production":
    db_manager = PostgreSQLDatabaseManager(settings.database_url)
else:
    db_manager = DatabaseManager(":memory:")

# Same interface, different backend
await db_manager.log_agent_execution(...)
await db_manager.get_agent_history(...)
```

### 3. Agent Scalability

```python
# Agents are stateless workers
class DataAnalysisAgent:
    """Stateless agent - can be scaled horizontally"""
    
    def __init__(self):
        self.agent_id = None  # Set per instance
        # No internal state
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # Stateless processing
        return {"result": "processed", "agent_id": self.agent_id}

# Can run multiple instances
agents = [DataAnalysisAgent() for _ in range(10)]
for i, agent in enumerate(agents):
    agent.agent_id = f"data_analyst_{i}"
```

## Future Extensibility

### 1. Adding New Agents

```python
# 1. Create new skill folder
mkdir trading-new-feature/

# 2. Add implementation
# trading-new-feature/scripts/new_agent.py
class NewFeatureAgent:
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # Implementation
        pass

# 3. Add documentation
# trading-new-feature/SKILL.md
# trading-new-feature/references/usage.md

# 4. Import and use
from trading-new-feature.scripts import NewFeatureAgent
```

### 2. Adding New Metrics

```python
# 1. Add to PerformanceMetric enum
class PerformanceMetric(Enum):
    SUCCESS_RATE = "success_rate"
    EXECUTION_TIME = "execution_time"
    NEW_METRIC = "new_metric"  # Add new metric

# 2. Update logging
await logger.db.record_performance_metric(
    agent_id="agent_001",
    metric_type=PerformanceMetric.NEW_METRIC,
    metric_value=0.85
)

# 3. Add to tests
async def test_new_metric_logging(self):
    await logger.log_performance_evaluation("agent_001", {
        "new_metric": 0.85
    })
    
    metrics = await logger.db.get_performance_metrics(
        "agent_001", PerformanceMetric.NEW_METRIC
    )
    assert len(metrics) >= 1
```

### 3. Adding New Event Types

```python
# 1. Add to EventType enum
class EventType(Enum):
    AGENT_EXECUTION = "agent_execution"
    NEW_EVENT_TYPE = "new_event_type"  # Add new event

# 2. Update logging
await logger.db.log_agent_event(
    agent_id="agent_001",
    event_type=EventType.NEW_EVENT_TYPE,
    log_level=LogLevel.INFO,
    status=AgentStatus.ACTIVE,
    message="New event occurred"
)
```

## Best Practices

### 1. Error Handling

```python
# ✅ Good: Specific exceptions with context
try:
    result = await agent.execute(input_data)
except DataValidationError as e:
    logger.error(f"Data validation failed: {e}")
    await logger.log_mistake_analysis(...)
except ExecutionError as e:
    logger.error(f"Execution failed: {e}")
    await logger.log_mistake_analysis(...)

# ❌ Bad: Generic exception handling
try:
    result = await agent.execute(input_data)
except Exception as e:
    print(f"Something went wrong: {e}")  # Lost context
```

### 2. Logging

```python
# ✅ Good: Structured logging with context
await logger.log_agent_execution(
    agent_id="data_analyst",
    execution_id=f"exec_{uuid.uuid4().hex[:8]}",
    action="analyze_market",
    input_data={"symbol": "AAPL", "indicators": ["RSI", "MACD"]},
    output_data={"signal": "buy", "confidence": 0.85},
    success=True,
    execution_time_ms=150
)

# ❌ Bad: Unstructured logging
print(f"Agent {agent_id} analyzed {symbol} and got {signal}")
```

### 3. Testing

```python
# ✅ Good: Isolated tests with fixtures
@pytest_asyncio.fixture
async def test_agent():
    agent = TestAgent("test_agent_001")
    yield agent
    # Cleanup handled automatically

async def test_agent_execution(test_agent):
    result = await test_agent.execute({"test": "data"})
    assert result["success"] == True

# ❌ Bad: Tests with side effects
def test_agent_execution():
    agent = TestAgent("test_agent_001")
    result = agent.execute({"test": "data"})
    assert result["success"] == True
    # No cleanup, potential side effects
```

This architecture ensures the system is:
- **Testable**: Each component can be tested in isolation
- **Debuggable**: Clear logging and state tracking
- **Scalable**: Modular design supports horizontal scaling
- **Maintainable**: Clear separation of concerns
- **Observable**: All actions are logged and traceable
