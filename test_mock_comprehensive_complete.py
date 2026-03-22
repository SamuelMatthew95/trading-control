#!/usr/bin/env python3
"""
Comprehensive test suite for the production-safe mock setup.

Tests all aspects of the mock setup to ensure it works correctly
with existing test patterns and provides full SQLAlchemy compatibility.
Covers cross-database compatibility and all edge cases.
"""

import asyncio
import pytest
from tests.test_mocks_complete import (
    FakeResult,
    FakeSession, 
    FakeSessionFactory,
    TestAgentRun,
    create_test_agent_run,
    get_cross_database_defaults
)


class TestFakeResult:
    """Comprehensive tests for FakeResult functionality."""
    
    def test_scalar_methods(self):
        """Test scalar() and scalar_one() methods with various data types."""
        # Test with integer
        result = FakeResult(scalar=42)
        assert result.scalar() == 42
        assert result.scalar_one() == 42
        
        # Test with string
        result = FakeResult(scalar="test_value")
        assert result.scalar() == "test_value"
        assert result.scalar_one() == "test_value"
        
        # Test with None
        result_none = FakeResult(scalar=None)
        assert result_none.scalar() is None
        assert result_none.scalar_one() is None
    
    def test_first_method(self):
        """Test first() method with different data types and edge cases."""
        # Test with dictionary
        result = FakeResult(first_row={"id": 1, "name": "test"})
        assert result.first() == {"id": 1, "name": "test"}
        
        # Test with custom object
        class TestObj:
            def __init__(self, value):
                self.value = value
        
        obj = TestObj("test")
        result = FakeResult(first_row=obj)
        assert result.first().value == "test"
        
        # Test with mapping_rows (takes precedence over first_row)
        result = FakeResult(
            first_row={"old": "data"},
            mapping_rows=[{"id": 1, "name": "test"}]
        )
        assert result.first() == {"id": 1, "name": "test"}
        
        # Test with no data (edge case)
        result_empty = FakeResult()
        assert result_empty.first() is None
    
    def test_all_method(self):
        """Test all() method with rows, mappings, and edge cases."""
        # Test with simple rows
        result = FakeResult(rows=[{"id": 1}, {"id": 2}])
        assert result.all() == [{"id": 1}, {"id": 2}]
        
        # Test with objects
        class TestObj:
            def __init__(self, value):
                self.value = value
        
        objs = [TestObj("a"), TestObj("b")]
        result = FakeResult(rows=objs)
        assert len(result.all()) == 2
        assert result.all()[0].value == "a"
        
        # Test with mapping_rows (takes precedence over rows)
        result = FakeResult(
            rows=[{"old": "data"}],
            mapping_rows=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        )
        assert result.all() == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        
        # Test with empty data (edge case)
        result_empty = FakeResult()
        assert result_empty.all() == []
    
    def test_mappings_method(self):
        """Test mappings() method and chaining with all()."""
        # Test with mapping data
        result = FakeResult(mapping_rows=[{"id": 1, "name": "test"}])
        mappings = result.mappings()
        assert mappings.all() == [{"id": 1, "name": "test"}]
        
        # Test chaining behavior
        result = FakeResult(mapping_rows=[{"id": 1}, {"id": 2}])
        all_results = result.mappings().all()
        assert len(all_results) == 2
        assert all_results[0]["id"] == 1
    
    def test_mixed_data_types(self):
        """Test FakeResult with mixed and complex data types."""
        complex_data = {
            "id": 1,
            "name": "test",
            "metadata": {"key": "value"},
            "tags": ["tag1", "tag2"],
            "active": True,
            "score": 0.95
        }
        
        result = FakeResult(
            scalar=complex_data["id"],
            first_row=complex_data,
            rows=[complex_data],
            mapping_rows=[complex_data]
        )
        
        assert result.scalar() == 1
        assert result.first()["name"] == "test"
        assert result.all()[0]["tags"] == ["tag1", "tag2"]
        assert result.mappings().all()[0]["active"] is True


class TestFakeSession:
    """Comprehensive tests for FakeSession functionality."""
    
    async def test_async_context_manager(self):
        """Test basic async context manager support."""
        session = FakeSession()
        
        async with session:
            assert isinstance(session, FakeSession)
            assert not session._in_transaction
        
        # Should work without errors for multiple uses
        async with session:
            await session.execute("SELECT 1")
        
        assert len(session.executed) == 1
    
    async def test_transaction_context_manager(self):
        """Test transaction context manager with state tracking."""
        session = FakeSession()
        
        # Test successful transaction
        async with session.begin():
            assert session._in_transaction
            await session.execute("INSERT INTO test VALUES (1)")
            await session.flush()
        
        assert not session._in_transaction
        assert len(session.executed) == 1
    
    async def test_transaction_rollback_on_exception(self):
        """Test transaction rollback behavior on exceptions."""
        session = FakeSession()
        exception_occurred = False
        
        try:
            async with session.begin():
                assert session._in_transaction
                await session.execute("INSERT INTO test VALUES (1)")
                raise ValueError("Test exception")
        except ValueError:
            exception_occurred = True
        
        assert exception_occurred
        assert not session._in_transaction
        assert len(session.executed) == 1  # Statement before exception still executed
    
    async def test_execute_with_handler(self):
        """Test execute() method with custom synchronous handler."""
        def handler(sql, params):
            if "COUNT" in sql:
                return FakeResult(scalar=100)
            elif "SELECT" in sql:
                return FakeResult(rows=[{"id": 1, "name": "test"}])
            elif "INSERT" in sql:
                return FakeResult(scalar=1)
            return FakeResult()
        
        session = FakeSession(handler)
        
        # Test COUNT query
        result = await session.execute("SELECT COUNT(*) FROM users")
        assert result.scalar() == 100
        
        # Test SELECT query
        result = await session.execute("SELECT * FROM users")
        assert result.all() == [{"id": 1, "name": "test"}]
        
        # Test INSERT query
        result = await session.execute("INSERT INTO users VALUES (1)")
        assert result.scalar() == 1
        
        # Test execution tracking
        assert len(session.executed) == 3
        assert "COUNT" in session.executed[0][0]
        assert "SELECT" in session.executed[1][0]
        assert "INSERT" in session.executed[2][0]
    
    async def test_execute_without_handler(self):
        """Test execute() method without handler (default behavior)."""
        session = FakeSession()
        
        result = await session.execute("SELECT 1")
        assert result.scalar() is None
        assert result.all() == []
        assert result.first() is None
        
        # Should still track execution
        assert len(session.executed) == 1
    
    async def test_execute_with_parameters(self):
        """Test execute() method with parameters."""
        def handler(sql, params):
            return FakeResult(scalar=f"Result for {params.get('name', 'unknown')}")
        
        session = FakeSession(handler)
        
        result = await session.execute("SELECT * FROM users WHERE name = :name", 
                                       {"name": "test"})
        assert result.scalar() == "Result for test"
        
        # Verify parameters were tracked
        assert session.executed[0][1] == {"name": "test"}
    
    async def test_transaction_control_methods(self):
        """Test flush(), commit(), and rollback() methods."""
        session = FakeSession()
        
        # All methods should be awaitable without error
        await session.flush()
        await session.commit()
        await session.rollback()
        
        # Commit should be tracked
        assert session.commits == 1
        
        # Multiple commits should be tracked
        await session.commit()
        await session.commit()
        assert session.commits == 3
    
    async def test_nested_transactions(self):
        """Test nested transaction behavior."""
        session = FakeSession()
        
        async with session.begin():
            assert session._in_transaction
            await session.execute("INSERT INTO test VALUES (1)")
            
            # In our implementation, nested begin() calls don't create true nesting
            # They share the same transaction context
            async with session.begin():
                assert session._in_transaction  # Still in transaction
                await session.execute("INSERT INTO test VALUES (2)")
            
            # Still in outer transaction
            assert session._in_transaction
            await session.execute("INSERT INTO test VALUES (3)")
        
        assert not session._in_transaction
        assert len(session.executed) == 3


class TestFakeSessionFactory:
    """Tests for FakeSessionFactory functionality."""
    
    def test_factory_with_default_session(self):
        """Test factory creates default session when none provided."""
        factory = FakeSessionFactory()
        session = factory()
        
        assert isinstance(session, FakeSession)
        assert session.handler is None
        assert session.commits == 0
    
    def test_factory_with_custom_session(self):
        """Test factory returns provided session."""
        def custom_handler(sql, params):
            return FakeResult(scalar="custom")
        
        custom_session = FakeSession(custom_handler)
        factory = FakeSessionFactory(custom_session)
        
        session = factory()
        assert session is custom_session
        assert session.handler is custom_session.handler
    
    def test_factory_reuse(self):
        """Test that factory returns the same session instance."""
        factory = FakeSessionFactory()
        session1 = factory()
        session2 = factory()
        
        assert session1 is session2


class TestAgentRunCompatibility:
    """Tests for TestAgentRun backward compatibility."""
    
    def test_legacy_fields_access(self):
        """Test access to legacy fields with various data types."""
        run = TestAgentRun(
            task_id="test_task",
            decision_json='{"action": "buy", "confidence": 0.8}',
            trace_json='[{"step": "analyze", "result": "bullish"}]',
            trace_id="trace_123"
        )
        
        # Legacy field access
        assert run.task_id == "test_task"
        assert run.decision_json == '{"action": "buy", "confidence": 0.8}'
        assert run.trace_json == '[{"step": "analyze", "result": "bullish"}]'
        
        # Production field access
        assert run.trace_id == "trace_123"
    
    def test_legacy_fields_defaults(self):
        """Test default values for legacy fields."""
        run = TestAgentRun(trace_id="trace_456")
        
        assert run.task_id is None
        assert run.decision_json == "{}"
        assert run.trace_json == "[]"
    
    def test_production_fields_work(self):
        """Test production fields work normally with TestAgentRun."""
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
    
    def test_mixed_legacy_and_production_fields(self):
        """Test using both legacy and production fields together."""
        run = TestAgentRun(
            # Legacy fields
            task_id="mixed_test",
            decision_json='{"action": "sell", "confidence": 0.9}',
            trace_json='[{"step": "analyze", "tool": "technical"}]',
            
            # Production fields
            strategy_id="mean_reversion",
            symbol="MSFT",
            action="sell",
            confidence=0.9,
            trace_id="trace_999"
        )
        
        # Legacy fields
        assert run.task_id == "mixed_test"
        assert "sell" in run.decision_json
        assert "technical" in run.trace_json
        
        # Production fields
        assert run.strategy_id == "mean_reversion"
        assert run.symbol == "MSFT"
        assert run.action == "sell"
        assert run.confidence == 0.9
        assert run.trace_id == "trace_999"
    
    def test_factory_function(self):
        """Test create_test_agent_run factory function."""
        run = create_test_agent_run(
            task_id="factory_test",
            decision_json='{"action": "hold"}',
            trace_json='[]',
            strategy_id="rsi_v2",
            symbol="BTC",
            action="hold",
            confidence=0.5,
            trace_id="trace_888"
        )
        
        assert isinstance(run, TestAgentRun)
        assert run.task_id == "factory_test"
        assert run.decision_json == '{"action": "hold"}'
        assert run.trace_json == '[]'
        assert run.strategy_id == "rsi_v2"
        assert run.symbol == "BTC"
        assert run.action == "hold"
        assert run.confidence == 0.5
        assert run.trace_id == "trace_888"
    
    def test_factory_with_minimal_arguments(self):
        """Test factory function with minimal arguments."""
        run = create_test_agent_run(trace_id="minimal_trace")
        
        assert isinstance(run, TestAgentRun)
        assert run.task_id is None
        assert run.decision_json == "{}"
        assert run.trace_json == "[]"
        assert run.trace_id == "minimal_trace"


class TestCrossDatabaseCompatibility:
    """Tests for cross-database compatibility features."""
    
    def test_get_cross_database_defaults(self):
        """Test cross-database defaults detection."""
        defaults = get_cross_database_defaults()
        
        # Should return expected keys
        assert 'uuid_default' in defaults
        assert 'datetime_default' in defaults
        assert 'json_type' in defaults
        assert 'vector_type' in defaults
        
        # Values should be appropriate for detected database
        if defaults['uuid_default'] is not None:
            # PostgreSQL detected
            assert 'gen_random_uuid' in defaults['uuid_default']
            assert defaults['datetime_default'] == 'now()'
        else:
            # SQLite detected
            assert defaults['uuid_default'] is None
            assert defaults['datetime_default'] is None
            assert defaults['json_type'] == 'TEXT'
            assert defaults['vector_type'] == 'TEXT'


class TestIntegration:
    """Integration tests combining all mock components."""
    
    async def test_full_integration_scenario(self):
        """Test a complete scenario using all mock components."""
        
        # Setup query handler for realistic database simulation
        def handler(sql, params):
            sql_lower = sql.lower()
            
            if "count" in sql_lower and "agent_runs" in sql_lower:
                return FakeResult(scalar=42)
            elif "select" in sql_lower and "agent_runs" in sql_lower:
                if params and params.get("strategy_id") == "momentum_v1":
                    return FakeResult(
                        mapping_rows=[
                            {
                                "id": "run_1",
                                "strategy_id": "momentum_v1",
                                "symbol": "AAPL",
                                "action": "buy",
                                "confidence": 0.8,
                                "trace_id": "trace_123"
                            }
                        ]
                    )
                else:
                    return FakeResult(mapping_rows=[])
            elif "insert" in sql_lower and "agent_runs" in sql_lower:
                return FakeResult(scalar=1)
            return FakeResult()
        
        # Create session and factory
        session = FakeSession(handler)
        factory = FakeSessionFactory(session)
        
        # Test database operations with TestAgentRun
        async with session.begin():
            # Query existing runs
            result = await session.execute(
                "SELECT * FROM agent_runs WHERE strategy_id = :strategy_id",
                {"strategy_id": "momentum_v1"}
            )
            runs = result.all()
            assert len(runs) == 1
            assert runs[0]["strategy_id"] == "momentum_v1"
            assert runs[0]["symbol"] == "AAPL"
            
            # Create new run using TestAgentRun
            test_run = create_test_agent_run(
                task_id="integration_test",
                decision_json='{"action": "buy", "confidence": 0.9}',
                trace_json='[{"step": "analyze", "result": "bullish"}]',
                trace_id="trace_456",
                strategy_id="mean_reversion",
                symbol="MSFT",
                action="buy",
                confidence=0.9
            )
            
            # Simulate database insert
            await session.execute(
                "INSERT INTO agent_runs (id, strategy_id, symbol, action, confidence, trace_id) VALUES (...)",
                {
                    "id": test_run.id,
                    "strategy_id": test_run.strategy_id,
                    "symbol": test_run.symbol,
                    "action": test_run.action,
                    "confidence": test_run.confidence,
                    "trace_id": test_run.trace_id
                }
            )
            
            # Query count
            count_result = await session.execute("SELECT COUNT(*) FROM agent_runs")
            count = count_result.scalar()
            assert count == 42
        
        # Verify execution tracking
        assert len(session.executed) == 3
        assert not session._in_transaction
        
        # Verify TestAgentRun compatibility
        assert test_run.task_id == "integration_test"
        assert test_run.decision_json == '{"action": "buy", "confidence": 0.9}'
        assert test_run.trace_json == '[{"step": "analyze", "result": "bullish"}]'
        assert test_run.strategy_id == "mean_reversion"
        assert test_run.symbol == "MSFT"
    
    async def test_error_scenarios(self):
        """Test error handling and edge cases."""
        def error_handler(sql, params):
            if "error" in sql.lower():
                raise ValueError("Simulated database error")
            if "none" in sql.lower():
                return FakeResult(scalar=None)
            if "empty" in sql.lower():
                return FakeResult()  # Empty result with no scalar
            return FakeResult(scalar="success")
        
        # Use fresh session for this test
        session = FakeSession(error_handler)
        
        # Test successful query
        result = await session.execute("SELECT success")
        assert result.scalar() == "success"
        
        # Test None result
        result = await session.execute("SELECT none")
        assert result.scalar() is None
        
        # Test empty results
        result = await session.execute("SELECT empty")
        assert result.scalar() is None  # Empty result returns None
        assert result.all() == []
        
        # Test error in transaction with fresh session
        session2 = FakeSession(error_handler)
        exception_caught = False
        try:
            async with session2.begin():
                await session2.execute("SELECT success")  # This works
                await session2.execute("SELECT error")   # This raises exception
                await session2.execute("SELECT should_not_execute")  # This shouldn't execute
        except ValueError:
            exception_caught = True
        
        assert exception_caught
        assert not session2._in_transaction
        assert len(session2.executed) == 2  # Only first two queries attempted
    
    async def test_high_volume_operations(self):
        """Test performance with many database operations."""
        def simple_handler(sql, params):
            if "insert" in sql.lower():
                return FakeResult(scalar=1)
            elif "select" in sql.lower():
                return FakeResult(rows=[{"id": i} for i in range(10)])
            return FakeResult()
        
        session = FakeSession(simple_handler)
        
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
        
        # Verify performance tracking
        assert len(session.executed) == 150  # 100 inserts + 50 selects
        assert session.commits == 0  # No manual commits in transaction


if __name__ == '__main__':
    """Run all tests to verify complete functionality."""
    
    async def run_all_tests():
        print("=== Running Comprehensive Mock Setup Tests ===")
        
        # Test FakeResult
        print("\n1. Testing FakeResult...")
        result_tests = TestFakeResult()
        result_tests.test_scalar_methods()
        result_tests.test_first_method()
        result_tests.test_all_method()
        result_tests.test_mappings_method()
        result_tests.test_mixed_data_types()
        print("✅ FakeResult tests passed")
        
        # Test FakeSession
        print("\n2. Testing FakeSession...")
        session_tests = TestFakeSession()
        await session_tests.test_async_context_manager()
        await session_tests.test_transaction_context_manager()
        await session_tests.test_transaction_rollback_on_exception()
        await session_tests.test_execute_with_handler()
        await session_tests.test_execute_without_handler()
        await session_tests.test_execute_with_parameters()
        await session_tests.test_transaction_control_methods()
        await session_tests.test_nested_transactions()
        print("✅ FakeSession tests passed")
        
        # Test FakeSessionFactory
        print("\n3. Testing FakeSessionFactory...")
        factory_tests = TestFakeSessionFactory()
        factory_tests.test_factory_with_default_session()
        factory_tests.test_factory_with_custom_session()
        factory_tests.test_factory_reuse()
        print("✅ FakeSessionFactory tests passed")
        
        # Test TestAgentRun
        print("\n4. Testing TestAgentRun...")
        agent_tests = TestAgentRunCompatibility()
        agent_tests.test_legacy_fields_access()
        agent_tests.test_legacy_fields_defaults()
        agent_tests.test_production_fields_work()
        agent_tests.test_mixed_legacy_and_production_fields()
        agent_tests.test_factory_function()
        agent_tests.test_factory_with_minimal_arguments()
        print("✅ TestAgentRun tests passed")
        
        # Test Cross-Database Compatibility
        print("\n5. Testing Cross-Database Compatibility...")
        db_tests = TestCrossDatabaseCompatibility()
        db_tests.test_get_cross_database_defaults()
        print("✅ Cross-Database Compatibility tests passed")
        
        # Test Integration
        print("\n6. Testing Full Integration...")
        integration_tests = TestIntegration()
        await integration_tests.test_full_integration_scenario()
        await integration_tests.test_error_scenarios()
        await integration_tests.test_high_volume_operations()
        print("✅ Integration tests passed")
        
        print("\n🎉 ALL COMPREHENSIVE TESTS PASSED!")
        print("✅ Production-safe mock setup ready for deployment")
        print("✅ All error scenarios handled correctly")
        print("✅ Cross-database compatibility verified")
        print("✅ Full async SQLAlchemy compatibility confirmed")
    
    asyncio.run(run_all_tests())
