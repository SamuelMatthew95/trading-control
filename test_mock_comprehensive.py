#!/usr/bin/env python3
"""
Comprehensive test suite for the mock setup.

This file tests all aspects of the mock setup to ensure it works correctly
with existing test patterns and provides full SQLAlchemy compatibility.
"""

import asyncio
import pytest
from tests.test_mocks import (
    FakeResult,
    FakeSession, 
    FakeSessionFactory,
    TestAgentRun,
    create_test_agent_run
)


class TestFakeResult:
    """Test FakeResult functionality."""
    
    def test_scalar_methods(self):
        """Test scalar() and scalar_one() methods."""
        result = FakeResult(scalar=42)
        assert result.scalar() == 42
        assert result.scalar_one() == 42
        
        result_none = FakeResult(scalar=None)
        assert result_none.scalar() is None
        assert result_none.scalar_one() is None
    
    def test_first_method(self):
        """Test first() method with different data types."""
        # Test with first_row
        result = FakeResult(first_row={"id": 1, "name": "test"})
        assert result.first() == {"id": 1, "name": "test"}
        
        # Test with mapping_rows (takes precedence)
        result = FakeResult(
            first_row={"old": "data"},
            mapping_rows=[{"id": 1, "name": "test"}]
        )
        assert result.first() == {"id": 1, "name": "test"}
        
        # Test with no data
        result_empty = FakeResult()
        assert result_empty.first() is None
    
    def test_all_method(self):
        """Test all() method with rows and mappings."""
        # Test with rows
        result = FakeResult(rows=[{"id": 1}, {"id": 2}])
        assert result.all() == [{"id": 1}, {"id": 2}]
        
        # Test with mapping_rows (takes precedence)
        result = FakeResult(
            rows=[{"old": "data"}],
            mapping_rows=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        )
        assert result.all() == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        
        # Test with no data
        result_empty = FakeResult()
        assert result_empty.all() == []
    
    def test_mappings_method(self):
        """Test mappings() method."""
        result = FakeResult(mapping_rows=[{"id": 1}])
        mappings = result.mappings()
        assert mappings.all() == [{"id": 1}]


class TestFakeSession:
    """Test FakeSession functionality."""
    
    async def test_async_context_manager(self):
        """Test basic async context manager support."""
        session = FakeSession()
        
        async with session:
            assert isinstance(session, FakeSession)
        
        # Should work without errors
        await session.execute("SELECT 1")
    
    async def test_transaction_context_manager(self):
        """Test transaction context manager support."""
        session = FakeSession()
        
        async with session.begin():
            await session.execute("INSERT INTO test VALUES (1)")
            await session.flush()
        
        # Should track transaction state
        assert not session._in_transaction
        assert len(session.executed) == 1
    
    async def test_execute_with_handler(self):
        """Test execute() method with custom handler."""
        def handler(sql, params):
            if "COUNT" in sql:
                return FakeResult(scalar=100)
            elif "SELECT" in sql:
                return FakeResult(rows=[{"id": 1, "name": "test"}])
            return FakeResult()
        
        session = FakeSession(handler)
        
        # Test COUNT query
        result = await session.execute("SELECT COUNT(*) FROM users")
        assert result.scalar() == 100
        
        # Test SELECT query
        result = await session.execute("SELECT * FROM users")
        assert result.all() == [{"id": 1, "name": "test"}]
        
        # Test execution tracking
        assert len(session.executed) == 2
        assert session.executed[0][0] == "SELECT COUNT(*) FROM users"
        assert session.executed[1][0] == "SELECT * FROM users"
    
    async def test_execute_without_handler(self):
        """Test execute() method without handler (default behavior)."""
        session = FakeSession()
        
        result = await session.execute("SELECT 1")
        assert result.scalar() is None
        assert result.all() == []
    
    async def test_transaction_control_methods(self):
        """Test flush(), commit(), and rollback() methods."""
        session = FakeSession()
        
        # All methods should be awaitable without error
        await session.flush()
        await session.commit()
        await session.rollback()
        
        # Commit should be tracked
        assert session.commits == 1
    
    async def test_transaction_rollback_on_exception(self):
        """Test transaction rollback behavior on exception."""
        session = FakeSession()
        exception_occurred = False
        
        try:
            async with session.begin():
                await session.execute("INSERT INTO test VALUES (1)")
                raise ValueError("Test exception")
        except ValueError:
            exception_occurred = True
        
        assert exception_occurred
        assert not session._in_transaction
        assert len(session.executed) == 1


class TestFakeSessionFactory:
    """Test FakeSessionFactory functionality."""
    
    def test_factory_with_default_session(self):
        """Test factory creates default session when none provided."""
        factory = FakeSessionFactory()
        session = factory()
        
        assert isinstance(session, FakeSession)
        assert session.handler is None
    
    def test_factory_with_custom_session(self):
        """Test factory returns provided session."""
        custom_session = FakeSession()
        factory = FakeSessionFactory(custom_session)
        
        session = factory()
        assert session is custom_session


class TestAgentRunCompatibility:
    """Test TestAgentRun backward compatibility."""
    
    def test_legacy_fields_access(self):
        """Test access to legacy fields."""
        run = TestAgentRun(
            task_id="test_task",
            decision_json='{"action": "buy"}',
            trace_json='[{"step": "analyze"}]',
            trace_id="trace_123"
        )
        
        # Legacy field access
        assert run.task_id == "test_task"
        assert run.decision_json == '{"action": "buy"}'
        assert run.trace_json == '[{"step": "analyze"}]'
        
        # Production field access
        assert run.trace_id == "trace_123"
    
    def test_legacy_fields_defaults(self):
        """Test default values for legacy fields."""
        run = TestAgentRun(trace_id="trace_456")
        
        assert run.task_id is None
        assert run.decision_json == "{}"
        assert run.trace_json == "[]"
    
    def test_production_fields_work(self):
        """Test production fields work normally."""
        run = TestAgentRun(
            strategy_id="momentum_v1",
            symbol="AAPL",
            action="buy",
            confidence=0.8,
            trace_id="trace_789"
        )
        
        assert run.strategy_id == "momentum_v1"
        assert run.symbol == "AAPL"
        assert run.action == "buy"
        assert run.confidence == 0.8
        assert run.trace_id == "trace_789"
    
    def test_factory_function(self):
        """Test create_test_agent_run factory function."""
        run = create_test_agent_run(
            task_id="factory_test",
            decision_json='{"action": "sell"}',
            trace_json='[]',
            strategy_id="rsi_v2",
            symbol="BTC",
            trace_id="trace_999"
        )
        
        assert isinstance(run, TestAgentRun)
        assert run.task_id == "factory_test"
        assert run.decision_json == '{"action": "sell"}'
        assert run.trace_json == "[]"
        assert run.strategy_id == "rsi_v2"
        assert run.symbol == "BTC"
        assert run.trace_id == "trace_999"


class TestIntegration:
    """Integration tests combining all mock components."""
    
    async def test_full_integration_scenario(self):
        """Test a complete scenario using all mock components."""
        
        # Setup query handler
        def handler(sql, params):
            if "agent_runs" in sql and "SELECT" in sql:
                return FakeResult(
                    rows=[
                        {
                            "id": "run_1",
                            "strategy_id": "momentum_v1",
                            "symbol": "AAPL",
                            "trace_id": "trace_123"
                        }
                    ]
                )
            elif "INSERT" in sql:
                return FakeResult(scalar=1)
            return FakeResult()
        
        # Create session and factory
        session = FakeSession(handler)
        factory = FakeSessionFactory(session)
        
        # Test database operations
        async with session.begin():
            # Query existing runs
            result = await session.execute("SELECT * FROM agent_runs")
            runs = result.all()
            assert len(runs) == 1
            assert runs[0]["strategy_id"] == "momentum_v1"
            
            # Insert new run using TestAgentRun
            test_run = create_test_agent_run(
                task_id="integration_test",
                decision_json='{"action": "buy"}',
                trace_json='[]',
                trace_id="trace_456",
                strategy_id="mean_reversion",
                symbol="MSFT"
            )
            
            # Simulate database insert
            await session.execute("INSERT INTO agent_runs VALUES (...)", {
                "id": test_run.id,
                "strategy_id": test_run.strategy_id,
                "trace_id": test_run.trace_id
            })
        
        # Verify execution tracking
        assert len(session.executed) == 2
        # Note: Transaction context manager doesn't auto-commit in our mock
        # Real SQLAlchemy would commit on successful exit, but our mock tracks manual commits
        assert session.commits == 0  # No manual commit called in this test
        
        # Verify TestAgentRun works
        assert test_run.task_id == "integration_test"
        assert test_run.strategy_id == "mean_reversion"
        assert test_run.symbol == "MSFT"


if __name__ == '__main__':
    # Run all tests
    print("=== Running Mock Setup Tests ===")
    
    # Test FakeResult
    print("\n1. Testing FakeResult...")
    result_tests = TestFakeResult()
    result_tests.test_scalar_methods()
    result_tests.test_first_method()
    result_tests.test_all_method()
    result_tests.test_mappings_method()
    print("✅ FakeResult tests passed")
    
    # Test FakeSession (async)
    print("\n2. Testing FakeSession...")
    async def test_session():
        session_tests = TestFakeSession()
        await session_tests.test_async_context_manager()
        await session_tests.test_transaction_context_manager()
        await session_tests.test_execute_with_handler()
        await session_tests.test_execute_without_handler()
        await session_tests.test_transaction_control_methods()
        await session_tests.test_transaction_rollback_on_exception()
        print("✅ FakeSession tests passed")
    
    asyncio.run(test_session())
    
    # Test FakeSessionFactory
    print("\n3. Testing FakeSessionFactory...")
    factory_tests = TestFakeSessionFactory()
    factory_tests.test_factory_with_default_session()
    factory_tests.test_factory_with_custom_session()
    print("✅ FakeSessionFactory tests passed")
    
    # Test TestAgentRun
    print("\n4. Testing TestAgentRun...")
    agent_tests = TestAgentRunCompatibility()
    agent_tests.test_legacy_fields_access()
    agent_tests.test_legacy_fields_defaults()
    agent_tests.test_production_fields_work()
    agent_tests.test_factory_function()
    print("✅ TestAgentRun tests passed")
    
    # Test Integration
    print("\n5. Testing Integration...")
    async def test_integration():
        integration_tests = TestIntegration()
        await integration_tests.test_full_integration_scenario()
        print("✅ Integration tests passed")
    
    asyncio.run(test_integration())
    
    print("\n🎉 ALL MOCK SETUP TESTS PASSED!")
    print("✅ Ready for production use in pytest test suite")
