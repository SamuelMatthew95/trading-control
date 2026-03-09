# Testing Guide

## Comprehensive Testing Strategy

This guide covers how to test, debug, and monitor the trading system effectively.

## Test Structure

```
tests/
├── test_trading_system.py    # Main test suite
├── conftest.py               # Pytest configuration
└── test_guide.md             # This guide
```

## Running Tests

### Quick Test Run
```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test class
pytest tests/test_trading_system.py::TestStatefulLoggingSystem -v

# Run specific test method
pytest tests/test_trading_system.py::TestStatefulLoggingSystem::test_database_initialization -v
```

### Test Configuration
```bash
# Run with performance timing
pytest tests/ --durations=10

# Run in parallel (if installed)
pytest tests/ -n auto

# Run with detailed output
pytest tests/ -v -s --tb=short
```

## Test Categories

### 1. Unit Tests

Test individual components in isolation:

```python
class TestStatefulLoggingSystem:
    """Test core logging functionality"""
    
    @pytest_asyncio.fixture
    async def temp_db(self):
        """Create isolated test database"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db_manager, logger, test_manager = create_stateful_logging_system(db_path)
        
        yield db_manager, logger, test_manager
        
        # Cleanup
        await test_manager.cleanup_test_data()
        os.unlink(db_path)
    
    async def test_database_initialization(self, temp_db):
        """Test database tables are created correctly"""
        db_manager, _, _ = temp_db
        
        # Verify tables exist
        async with db_manager.get_connection() as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table'
            """)
            tables = [row['name'] for row in cursor.fetchall()]
            
            required_tables = [
                'agent_logs', 'execution_history', 'agent_performance',
                'agents', 'learning_sessions', 'team_formations'
            ]
            
            for table in required_tables:
                assert table in tables, f"Table {table} not created"
```

### 2. Integration Tests

Test how components work together:

```python
class TestIntegration:
    """Test system integration"""
    
    async def test_core_system_integration(self):
        """Test logging + orchestrator integration"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize systems
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            orchestrator = create_professional_orchestrator()
            
            # Test orchestrator execution
            state = await orchestrator.run_trading_cycle()
            
            # Test logging integration
            await logger.log_agent_execution(
                "orchestrator", "cycle_001", "run_cycle",
                {}, {"result": "success"}, True, 200
            )
            
            # Verify integration worked
            assert state["current_phase"] in [
                TradingPhase.MONITORING.value, 
                TradingPhase.ERROR_HANDLING.value
            ]
            
            history = await logger.db.get_execution_history(agent_id="orchestrator")
            assert len(history) >= 1
            assert history[0]["success"] == True
            
        finally:
            os.unlink(db_path)
```

### 3. Error Scenario Tests

Test error handling and recovery:

```python
async def test_error_handling_and_recovery(self):
    """Test that errors are handled gracefully"""
    
    orchestrator = create_professional_orchestrator()
    
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

## Debugging Tests

### 1. Test Isolation

Each test should be completely isolated:

```python
# ✅ Good: Isolated test with cleanup
@pytest_asyncio.fixture
async def isolated_system():
    """Create completely isolated system for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    db_manager, logger, test_manager = create_stateful_logging_system(db_path)
    
    yield db_manager, logger, test_manager
    
    # Guaranteed cleanup
    await test_manager.cleanup_test_data()
    os.unlink(db_path)

# ❌ Bad: Shared state between tests
shared_db = None

@pytest.fixture
def shared_system():
    global shared_db
    if shared_db is None:
        shared_db = create_stateful_logging_system()
    return shared_db
```

### 2. Test Data Management

Use consistent test data:

```python
class TestDataManager:
    """Manages test data for consistency"""
    
    @staticmethod
    def get_test_market_data():
        """Standard test market data"""
        return {
            "AAPL": {"price": 175.43, "volume": 1000000, "change": 1.2},
            "GOOGL": {"price": 140.25, "volume": 600000, "change": -0.5},
            "MSFT": {"price": 380.12, "volume": 800000, "change": 0.8}
        }
    
    @staticmethod
    def get_test_trade():
        """Standard test trade"""
        return {
            "symbol": "AAPL",
            "action": "buy",
            "size": 10000,
            "confidence": 0.85
        }

async def test_with_standard_data(isolated_system):
    """Test using standard test data"""
    _, logger, _ = isolated_system
    
    market_data = TestDataManager.get_test_market_data()
    trade = TestDataManager.get_test_trade()
    
    # Test with consistent data
    await logger.log_agent_execution(
        "test_agent", "exec_001", "analyze_market",
        market_data, {"signals": ["buy"]}, True, 150
    )
```

### 3. Assertion Strategies

Use descriptive assertions:

```python
# ✅ Good: Descriptive assertions with context
async def test_agent_performance_logging(self, temp_db):
    """Test agent performance metrics are logged correctly"""
    _, logger, _ = temp_db
    
    # Log performance metrics
    await logger.log_performance_evaluation("test_agent", {
        "success_rate": 0.92,
        "execution_time": 125.5,
        "collaboration_success": 0.88
    })
    
    # Verify with descriptive assertions
    recorded_metrics = await logger.db.get_performance_metrics(agent_id="test_agent")
    assert len(recorded_metrics) >= 3, f"Expected at least 3 metrics, got {len(recorded_metrics)}"
    
    # Check specific metrics with context
    success_rates = [m["metric_value"] for m in recorded_metrics if m["metric_type"] == "success_rate"]
    assert 0.92 in success_rates, f"Expected success_rate 0.92, got {success_rates}"

# ❌ Bad: Vague assertions
async def test_agent_performance_logging_bad(self, temp_db):
    """Test agent performance metrics"""
    _, logger, _ = temp_db
    
    await logger.log_performance_evaluation("test_agent", {"success_rate": 0.92})
    
    recorded_metrics = await logger.db.get_performance_metrics(agent_id="test_agent")
    assert len(recorded_metrics) >= 3  # Why 3? What metrics?
    assert recorded_metrics[0]["metric_value"] == 0.92  # Which metric?
```

## Performance Testing

### 1. Execution Time Tests

```python
async def test_execution_performance(self, temp_db):
    """Test that operations complete within expected time"""
    _, logger, _ = temp_db
    
    start_time = time.time()
    
    # Perform operation
    await logger.log_agent_execution(
        "test_agent", "exec_001", "test_action",
        {"test": "data"}, {"result": "success"}, True, 100
    )
    
    execution_time = time.time() - start_time
    
    # Assert performance requirement
    assert execution_time < 0.1, f"Operation took {execution_time:.3f}s, expected < 0.1s"
```

### 2. Load Testing

```python
async def test_concurrent_operations(self, temp_db):
    """Test system handles concurrent operations"""
    _, logger, _ = temp_db
    
    # Create multiple concurrent operations
    tasks = []
    for i in range(10):
        task = logger.log_agent_execution(
            f"agent_{i}", f"exec_{i}", "test_action",
            {"iteration": i}, {"result": "success"}, True, 100
        )
        tasks.append(task)
    
    # Execute concurrently
    start_time = time.time()
    await asyncio.gather(*tasks)
    execution_time = time.time() - start_time
    
    # Verify all operations completed
    history = await logger.db.get_execution_history(hours=1)
    assert len(history) >= 10, f"Expected 10 operations, got {len(history)}"
    
    # Verify performance
    assert execution_time < 1.0, f"Concurrent operations took {execution_time:.3f}s"
```

## Error Testing

### 1. Input Validation Tests

```python
async def test_input_validation(self, temp_db):
    """Test that invalid inputs are handled correctly"""
    _, logger, _ = temp_db
    
    # Test with invalid data
    with pytest.raises(ValueError, match="Invalid agent ID"):
        await logger.log_agent_execution(
            "", "exec_001", "test_action",  # Empty agent ID
            {"test": "data"}, {"result": "success"}, True, 100
        )
    
    # Test with missing required fields
    with pytest.raises(TypeError):
        await logger.log_agent_execution(
            "test_agent", None, "test_action",  # None execution_id
            {"test": "data"}, {"result": "success"}, True, 100
        )
```

### 2. Database Error Tests

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

## Monitoring and Observability in Tests

### 1. Test Metrics Collection

```python
async def test_observability_metrics(self, temp_db):
    """Test that observability metrics are collected"""
    db_manager, logger, _ = temp_db
    
    # Perform various operations
    await logger.log_agent_execution("agent_1", "exec_1", "action1", {}, {"result": "success"}, True, 100)
    await logger.log_agent_execution("agent_2", "exec_2", "action2", {}, {"result": "error"}, False, 200)
    await logger.log_performance_evaluation("agent_1", {"success_rate": 0.9})
    
    # Check system summary
    summary = await db_manager.get_system_summary()
    
    # Verify metrics are collected
    assert "agent_status_counts" in summary
    assert "execution_stats_24h" in summary
    assert "performance_averages_24h" in summary
    
    # Verify specific values
    assert summary["execution_stats_24h"]["total_executions"] >= 2
    assert summary["execution_stats_24h"]["successful_executions"] >= 1
```

### 2. Debug Information in Tests

```python
async def test_debug_information(self, temp_db):
    """Test that debug information is available"""
    db_manager, logger, _ = temp_db
    
    # Perform operation
    await logger.log_agent_execution(
        "debug_agent", "debug_exec", "debug_action",
        {"debug": "data"}, {"debug": "result"}, True, 100
    )
    
    # Get detailed history for debugging
    history = await db_manager.get_agent_history("debug_agent", limit=5)
    
    # Print debug information (only in test mode)
    if os.getenv("PYTEST_DEBUG"):
        print("\n=== Debug Information ===")
        for log in history:
            print(f"Event: {log['event_type']}")
            print(f"Status: {log['status']}")
            print(f"Message: {log['message']}")
            print(f"Metadata: {log['metadata']}")
            print("---")
    
    # Verify debug information is available
    assert len(history) >= 1
    assert "metadata" in history[0]
```

## Test Maintenance

### 1. Test Documentation

Each test should have clear documentation:

```python
async def test_agent_execution_logging(self, temp_db):
    """
    Test that agent executions are logged correctly to the database.
    
    This test verifies:
    1. Agent execution creates a record in execution_history table
    2. All required fields are stored correctly
    3. Performance metrics are recorded automatically
    4. Agent status is updated appropriately
    
    Args:
        temp_db: Fixture providing isolated database and logger
    
    Returns:
        None
    
    Raises:
        AssertionError: If logging doesn't work as expected
    """
    _, logger, _ = temp_db
    
    # Test implementation...
```

### 2. Test Data Factories

Use factories for creating test data:

```python
class TestAgentFactory:
    """Factory for creating test agents"""
    
    @staticmethod
    def create_test_agent(agent_id: str = "test_agent") -> Dict[str, Any]:
        """Create a test agent with default values"""
        return {
            "agent_id": agent_id,
            "agent_type": "test",
            "name": f"Test Agent {agent_id}",
            "status": "active",
            "tasks_completed": 0,
            "tasks_failed": 0,
            "current_load": 0,
            "max_concurrent_tasks": 5
        }
    
    @staticmethod
    def create_execution_record(agent_id: str, success: bool = True) -> Dict[str, Any]:
        """Create a test execution record"""
        return {
            "execution_id": f"exec_{uuid.uuid4().hex[:8]}",
            "agent_id": agent_id,
            "action": "test_action",
            "input_data": {"test": "data"},
            "output_data": {"result": "success"} if success else None,
            "success": success,
            "error_message": None if success else "Test error",
            "execution_time_ms": 100,
            "timestamp": datetime.now().isoformat()
        }

async def test_with_factory_data(temp_db):
    """Test using factory-created data"""
    db_manager, logger, _ = temp_db
    
    # Create test data using factory
    agent = TestAgentFactory.create_test_agent("factory_agent")
    execution = TestAgentFactory.create_execution_record("factory_agent", True)
    
    # Use factory data in test
    await db_manager.record_execution(**execution)
    
    # Verify factory data was used correctly
    history = await db_manager.get_execution_history(agent_id="factory_agent")
    assert len(history) >= 1
    assert history[0]["action"] == "test_action"
```

## Continuous Integration

### 1. Pre-commit Hooks

```bash
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest tests/
        language: system
        pass_filenames: false
        always_run: true
      
      - id: black
        name: black
        entry: black
        language: system
        files: ^src/
      
      - id: flake8
        name: flake8
        entry: flake8
        language: system
        files: ^src/
```

### 2. GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install -e .
        python -m pip install pytest pytest-cov black flake8
    
    - name: Run linting
      run: |
        flake8 src/ --max-line-length=88
        black --check src/
    
    - name: Run tests
      run: |
        pytest tests/ --cov=src --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v1
```

This comprehensive testing strategy ensures:
- **Reliability**: Tests catch regressions
- **Maintainability**: Tests are easy to understand and modify
- **Performance**: Tests verify performance requirements
- **Debugging**: Tests provide clear error information
- **Scalability**: Tests support system growth
