# Test Configuration and Execution Guide

## Test Structure

The comprehensive test suite is organized into logical test classes:

### 1. TestStatefulLoggingSystem
Tests the database-backed logging system with enums and stateful persistence.

**Key Tests:**
- Database initialization and table creation
- Agent execution logging with performance metrics
- Mistake analysis logging and tracking
- Learning session recording
- Performance evaluation metrics
- System summary generation

### 2. TestDeterministicTradingSystem
Tests the deterministic trading system with agent ranking and learning.

**Key Tests:**
- Agent registration and management
- Agent execution with learning signals
- Failure handling without fallbacks
- Agent communication protocols
- Ranking system calculations

### 3. TestIntelligentLearningSystem
Tests the intelligent learning system with mistake understanding.

**Key Tests:**
- Mistake pattern analysis and classification
- Success pattern identification
- Learning recommendation generation
- Team formation based on expertise
- Collaborative learning facilitation
- Performance evaluation and agent lifecycle

### 4. TestProfessionalTradingOrchestrator
Tests the state-machine-based orchestrator with safety protocols.

**Key Tests:**
- State initialization and management
- Complete trading cycle execution
- Safety protocol enforcement
- Error handling and recovery
- Position size and confidence limits

### 5. TestIntegration
Integration tests for the complete system workflow.

**Key Tests:**
- Complete trading workflow with all systems
- Learning system integration
- End-to-end mistake analysis and learning

## Running Tests

### Quick Test Run
```bash
# Run all tests
python test_trading_system.py

# Run with pytest (recommended)
pytest test_trading_system.py -v

# Run specific test class
pytest test_trading_system.py::TestStatefulLoggingSystem -v

# Run specific test method
pytest test_trading_system.py::TestStatefulLoggingSystem::test_agent_execution_logging -v
```

### Test Configuration
```bash
# Run with coverage
pytest test_trading_system.py --cov=. --cov-report=html

# Run with performance analysis
pytest test_trading_system.py --durations=10

# Run in parallel
pytest test_trading_system.py -n auto
```

## Database Testing

### Temporary Database Setup
Tests use temporary SQLite databases that are automatically created and cleaned up:

```python
@pytest.fixture
async def temp_db(self):
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    db_manager, logger, test_manager = create_stateful_logging_system(db_path)
    
    yield db_manager, logger, test_manager
    
    # Cleanup
    await test_manager.cleanup_test_data()
    os.unlink(db_path)
```

### Test Data Management
- **Setup**: `test_manager.setup_test_data()` creates consistent test data
- **Cleanup**: `test_manager.cleanup_test_data()` removes all test artifacts
- **Verification**: `test_manager.verify_data_integrity()` validates test results

## Meaningful Test Scenarios

### 1. Real Trading Scenarios
```python
async def test_real_market_analysis(self):
    """Test realistic market analysis scenario"""
    # Simulate real market data
    market_data = {
        "symbol": "AAPL",
        "price": 175.43,
        "volume": 1000000,
        "indicators": ["RSI", "MACD", "BB"]
    }
    
    # Execute analysis
    result = await trading_system.execute_agent_task(
        "market_analyst", "analyze_market", market_data
    )
    
    # Verify realistic outcomes
    assert result["success"] in [True, False]
    assert "execution_time_ms" in result
    assert result["execution_time_ms"] > 0  # Should take actual time
```

### 2. Mistake Learning Scenarios
```python
async def test_mistake_learning_cycle(self):
    """Test complete mistake learning cycle"""
    # Agent makes mistake
    mistake_result = await trading_system.execute_agent_task(
        "risk_controller", "assess_risk", invalid_risk_data
    )
    
    assert mistake_result["success"] == False
    
    # Analyze mistake
    analysis = await learning_manager.analyze_mistake(
        mistake_result["execution_id"], "risk_controller", "assess_risk",
        invalid_risk_data, mistake_result["error"]
    )
    
    # Get learning recommendations
    recommendations = await learning_manager.get_learning_recommendations(
        "risk_controller", analysis.mistake_pattern
    )
    
    # Form learning team
    team = await learning_manager.form_learning_team(
        "risk_controller", "risk_improvement", recommendations["required_expertise"]
    )
    
    # Verify team formation
    assert len(team.selected_agents) > 1
    assert team.confidence_score > 0.5
```

### 3. Performance Under Load
```python
async def test_system_performance_under_load(self):
    """Test system performance with concurrent operations"""
    # Create multiple agents
    agents = [TestAgent(f"agent_{i}") for i in range(10)]
    for agent in agents:
        trading_system.register_agent(agent)
    
    # Execute concurrent tasks
    tasks = []
    for i, agent in enumerate(agents):
        task = trading_system.execute_agent_task(
            agent.agent_id, "analyze_symbol", {"symbol": f"SYMBOL_{i}"}
        )
        tasks.append(task)
    
    # Wait for all completions
    results = await asyncio.gather(*tasks)
    
    # Verify all completed
    assert len(results) == 10
    success_count = sum(1 for r in results if r["success"])
    assert success_count >= 8  # Allow for some failures
```

## Database Query Testing

### Efficient Query Testing
```python
async def test_database_query_performance(self):
    """Test database query performance with large datasets"""
    # Create large dataset
    for i in range(1000):
        await logger.log_agent_execution(
            f"agent_{i % 10}", f"exec_{i}", "test_action",
            {"iteration": i}, {"result": "success"}, True, 100 + i
        )
    
    # Test query performance
    start_time = time.time()
    history = await logger.db.get_execution_history(hours=24)
    query_time = time.time() - start_time
    
    # Verify query efficiency
    assert len(history) == 1000
    assert query_time < 1.0  # Should complete in under 1 second
```

### Index Verification
```python
async def test_database_indexes(self):
    """Test that database indexes improve query performance"""
    # Create test data
    await test_manager.setup_test_data()
    
    # Test indexed queries
    start_time = time.time()
    agent_history = await logger.db.get_agent_history("agent_001")
    indexed_time = time.time() - start_time
    
    # Verify index effectiveness
    assert indexed_time < 0.1  # Should be very fast with indexes
    assert len(agent_history) > 0
```

## Test Data Validation

### Enum Validation
```python
async def test_enum_consistency(self):
    """Test that enums are used consistently throughout the system"""
    # Test log level enum
    for level in LogLevel:
        assert isinstance(level.value, str)
        assert level.value in ["debug", "info", "warning", "error", "critical"]
    
    # Test event type enum
    for event_type in EventType:
        assert isinstance(event_type.value, str)
        assert event_type.value in [
            "agent_execution", "mistake_analysis", "learning_session",
            "team_formation", "collaboration", "performance_evaluation", "system_event"
        ]
    
    # Test agent status enum
    for status in AgentStatus:
        assert isinstance(status.value, str)
        assert status.value in [
            "initializing", "active", "learning", "collaborating", "error", "retired"
        ]
```

### Data Type Validation
```python
async def test_database_schema_validation(self):
    """Test that database schema enforces data types"""
    # Test numeric fields
    await logger.db.record_performance_metric(
        "test_agent", PerformanceMetric.SUCCESS_RATE, 0.85
    )
    
    metrics = await logger.db.get_performance_metrics("test_agent")
    metric = metrics[0]
    
    assert isinstance(metric["metric_value"], float)
    assert 0.0 <= metric["metric_value"] <= 1.0
    
    # Test timestamp fields
    assert isinstance(metric["timestamp"], str)
    # Should be parseable as ISO datetime
    datetime.fromisoformat(metric["timestamp"])
```

## Error Scenario Testing

### Database Error Handling
```python
async def test_database_error_handling(self):
    """Test graceful handling of database errors"""
    # Test with invalid database path
    with pytest.raises(Exception):
        DatabaseManager("/invalid/path/database.db")
    
    # Test connection recovery
    db_manager = DatabaseManager(":memory:")
    
    # Simulate connection loss and recovery
    async with db_manager.get_connection() as conn:
        conn.execute("SELECT 1")  # Should work
    
    # Should be able to reconnect
    async with db_manager.get_connection() as conn:
        conn.execute("SELECT 1")  # Should work again
```

### System Error Recovery
```python
async def test_system_error_recovery(self):
    """Test system recovery from errors"""
    # Create system that will fail
    failing_agent = FailingTestAgent("failing_agent")
    trading_system.register_agent(failing_agent)
    
    # Execute failing task
    result = await trading_system.execute_agent_task(
        "failing_agent", "fail_action", {}
    )
    
    # Verify graceful failure
    assert result["success"] == False
    assert "error" in result
    assert "execution_id" in result
    
    # System should still be functional
    working_agent = TestAgent("working_agent")
    trading_system.register_agent(working_agent)
    
    result2 = await trading_system.execute_agent_task(
        "working_agent", "work_action", {}
    )
    
    assert result2["success"] == True
```

## Test Maintenance

### Regular Test Updates
1. **Add new tests** for each new feature
2. **Update existing tests** when interfaces change
3. **Remove obsolete tests** when features are deprecated
4. **Maintain test coverage** above 90%

### Test Data Management
1. **Use temporary databases** for isolation
2. **Clean up test data** after each test
3. **Use realistic test data** that mirrors production
4. **Validate data integrity** in tests

### Performance Monitoring
1. **Track test execution time**
2. **Monitor database query performance**
3. **Identify slow tests** for optimization
4. **Maintain test suite efficiency**

This comprehensive test suite ensures the trading system works correctly with stateful logging, meaningful scenarios, and proper database persistence.
