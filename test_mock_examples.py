"""
Practical examples of using the mock setup in real pytest tests.

This file demonstrates how to integrate the mock setup into existing
pytest test patterns, including monkeypatching and common test scenarios.
"""

import pytest
from tests.test_mocks import (
    FakeResult,
    FakeSession,
    FakeSessionFactory,
    TestAgentRun,
    create_test_agent_run
)


# ============================================================================
# EXAMPLE 1: Basic Service Testing with FakeSession
# ============================================================================

def example_service_test(monkeypatch):
    """
    Example: Testing a service that uses database sessions.
    
    This pattern shows how to monkeypatch the session factory and
    verify database operations without a real database.
    """
    
    # Setup query handler that simulates database responses
    def query_handler(sql, params):
        if "SELECT COUNT" in sql:
            return FakeResult(scalar=5)  # Simulate count query
        elif "INSERT INTO agent_runs" in sql:
            return FakeResult(scalar=1)  # Simulate insert success
        elif "SELECT * FROM agent_runs" in sql:
            return FakeResult(
                rows=[
                    {
                        "id": "run_123",
                        "strategy_id": "momentum_v1",
                        "symbol": "AAPL",
                        "trace_id": "trace_456"
                    }
                ]
            )
        return FakeResult()
    
    # Create mock session and factory
    session = FakeSession(query_handler)
    factory = FakeSessionFactory(session)
    
    # Monkeypatch the database session factory
    monkeypatch.setattr('api.database.AsyncSessionFactory', factory)
    
    # Now test your service - it will use FakeSession instead of real database
    # from my_module import MyService
    # service = MyService()
    # result = await service.get_run_count()
    # assert result == 5
    # assert len(session.executed) > 0  # Verify DB was called


# ============================================================================
# EXAMPLE 2: Testing with AgentRun Backward Compatibility
# ============================================================================

def example_agent_run_test():
    """
    Example: Testing code that expects legacy AgentRun fields.
    
    This shows how to use TestAgentRun to maintain compatibility
    with existing test code that uses legacy fields.
    """
    
    # Old test pattern (what existing tests expect)
    run = TestAgentRun(
        task_id="consensus:run-2",
        decision_json='{"action": "buy", "confidence": 0.8}',
        trace_json='[{"step": "analyze", "result": "bullish"}]',
        trace_id="trace_123"
    )
    
    # Access legacy fields (existing test code)
    assert run.task_id == "consensus:run-2"
    assert run.decision_json == '{"action": "buy", "confidence": 0.8}'
    assert run.trace_json == '[{"step": "analyze", "result": "bullish"}]'
    
    # Access production fields (new test code)
    assert run.trace_id == "trace_123"
    
    # Factory function approach (recommended for new tests)
    run2 = create_test_agent_run(
        task_id="factory_test",
        decision_json='{"action": "sell"}',
        trace_json='[]',
        trace_id="trace_789",
        strategy_id="mean_reversion",
        symbol="MSFT",
        action="sell",
        confidence=0.7
    )
    
    # Both legacy and production fields work
    assert run2.task_id == "factory_test"
    assert run2.strategy_id == "mean_reversion"
    assert run2.symbol == "MSFT"


# ============================================================================
# EXAMPLE 3: Async Transaction Testing
# ============================================================================

@pytest.mark.asyncio
async def example_transaction_test():
    """
    Example: Testing async transaction patterns.
    
    This shows how to test code that uses async with session.begin()
    transaction patterns.
    """
    
    # Setup handler for transaction testing
    def transaction_handler(sql, params):
        if "INSERT" in sql:
            return FakeResult(scalar=1)
        elif "SELECT" in sql:
            return FakeResult(rows=[{"id": 1, "value": "test"}])
        return FakeResult()
    
    session = FakeSession(transaction_handler)
    
    # Test transaction context manager
    async with session.begin():
        # Simulate database operations within transaction
        result1 = await session.execute("INSERT INTO test_table (name) VALUES (?)", 
                                       {"name": "test"})
        assert result1.scalar() == 1
        
        result2 = await session.execute("SELECT * FROM test_table WHERE name = ?", 
                                       {"name": "test"})
        rows = result2.all()
        assert len(rows) == 1
        assert rows[0]["value"] == "test"
    
    # Verify transaction was properly handled
    assert len(session.executed) == 2
    assert not session._in_transaction  # Transaction should be closed


# ============================================================================
# EXAMPLE 4: Complex Query Handler
# ============================================================================

def example_complex_handler():
    """
    Example: Complex query handler for sophisticated testing.
    
    This shows how to create a handler that responds differently
    based on SQL patterns and parameters.
    """
    
    def complex_query_handler(sql, params):
        """Handler that simulates a realistic database."""
        
        sql_lower = sql.lower()
        
        # Handle different query types
        if "count" in sql_lower and "agent_runs" in sql_lower:
            return FakeResult(scalar=42)  # Return count of agent runs
        
        elif "select" in sql_lower and "agent_runs" in sql_lower:
            # Return different results based on parameters
            if params and params.get("strategy_id") == "momentum_v1":
                return FakeResult(
                    rows=[
                        {
                            "id": "run_1",
                            "strategy_id": "momentum_v1",
                            "symbol": "AAPL",
                            "action": "buy",
                            "confidence": 0.8
                        }
                    ]
                )
            else:
                return FakeResult(rows=[])  # No results for other strategies
        
        elif "insert" in sql_lower and "agent_runs" in sql_lower:
            # Simulate successful insert
            return FakeResult(scalar=1)
        
        elif "update" in sql_lower:
            # Simulate update with affected row count
            return FakeResult(scalar=3)
        
        # Default empty result
        return FakeResult()
    
    return complex_query_handler


# ============================================================================
# EXAMPLE 5: Error Testing
# ============================================================================

@pytest.mark.asyncio
async def example_error_testing():
    """
    Example: Testing error handling with FakeSession.
    
    This shows how to test exception handling and rollback behavior.
    """
    
    def error_handler(sql, params):
        """Handler that simulates database errors."""
        if "error" in sql.lower():
            raise ValueError("Simulated database error")
        return FakeResult(scalar=1)
    
    session = FakeSession(error_handler)
    
    # Test error handling in transaction
    exception_caught = False
    try:
        async with session.begin():
            await session.execute("SELECT 1")  # This works
            await session.execute("ERROR QUERY")  # This raises exception
            await session.execute("SELECT 2")  # This shouldn't execute
    except ValueError:
        exception_caught = True
    
    assert exception_caught
    assert not session._in_transaction  # Transaction should be rolled back
    assert len(session.executed) == 2  # Only first two queries executed


# ============================================================================
# EXAMPLE 6: Migration Path for Existing Tests
# ============================================================================

def example_migration_path():
    """
    Example: How to migrate existing tests to use the new mock setup.
    
    This shows the before/after for migrating existing tests.
    """
    
    # BEFORE (old test that fails with clean AgentRun):
    # def test_old_pattern():
    #     run = AgentRun(
    #         task_id="test",
    #         decision_json="{}",
    #         trace_json="[]",
    #         trace_id="trace_123"
    #     )
    #     # TypeError: 'task_id' is an invalid keyword argument for AgentRun
    
    # AFTER (using TestAgentRun):
    def test_new_pattern():
        run = TestAgentRun(
            task_id="test",
            decision_json="{}",
            trace_json="[]",
            trace_id="trace_123"
        )
        # ✅ Works perfectly
    
    # AFTER (using factory function - recommended):
    def test_factory_pattern():
        run = create_test_agent_run(
            task_id="test",
            decision_json="{}",
            trace_json="[]",
            trace_id="trace_123"
        )
        # ✅ Works perfectly with cleaner syntax
    
    # AFTER (with production fields):
    def test_production_pattern():
        run = create_test_agent_run(
            task_id="test",
            decision_json="{}",
            trace_json="[]",
            trace_id="trace_123",
            strategy_id="momentum_v1",
            symbol="AAPL",
            action="buy",
            confidence=0.8
        )
        # ✅ Works with both legacy and production fields


# ============================================================================
# EXAMPLE 7: Performance and Load Testing
# ============================================================================

@pytest.mark.asyncio
async def example_performance_testing():
    """
    Example: Testing performance with many database operations.
    
    This shows how the mock setup handles high-volume testing scenarios.
    """
    
    def performance_handler(sql, params):
        """Fast handler for performance testing."""
        if "insert" in sql.lower():
            return FakeResult(scalar=1)
        elif "select" in sql.lower():
            return FakeResult(rows=[{"id": i} for i in range(10)])
        return FakeResult()
    
    session = FakeSession(performance_handler)
    
    # Simulate high-volume operations
    async with session.begin():
        # Insert many records
        for i in range(100):
            await session.execute(f"INSERT INTO test_table (value) VALUES ({i})")
        
        # Query many records
        for i in range(50):
            result = await session.execute("SELECT * FROM test_table LIMIT 10")
            rows = result.all()
            assert len(rows) == 10
    
    # Verify performance
    assert len(session.executed) == 150  # 100 inserts + 50 selects
    print(f"Processed 150 operations in mock session")


if __name__ == '__main__':
    print("=== Mock Setup Examples ===")
    print("\nAll examples are ready to be used in pytest tests!")
    print("\nKey patterns:")
    print("1. Use FakeSession(handler) for database mocking")
    print("2. Use FakeSessionFactory(session) for monkeypatching")
    print("3. Use TestAgentRun() for legacy test compatibility")
    print("4. Use create_test_agent_run() for new tests")
    print("5. All async patterns work: async with session / session.begin()")
