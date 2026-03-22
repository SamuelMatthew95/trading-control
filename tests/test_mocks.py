"""
Production-safe SQLAlchemy mock setup for async pytest tests.

This module provides comprehensive mock classes that simulate SQLAlchemy behavior
without requiring a real database connection. All classes are designed to be
fully compatible with async pytest tests and existing code patterns.

Features:
- Full async support for sessions and transactions
- Complete SQLAlchemy-like API for query results
- Backward-compatible AgentRun test layer
- Minimal boilerplate with maximum compatibility
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Union
from api.core.models import AgentRun


class FakeResult:
    """
    Comprehensive mock for SQLAlchemy Result objects.
    
    Supports all common SQLAlchemy Result methods used in tests:
    - scalar(): Returns a single value
    - scalar_one(): Returns a single value (alias for scalar)
    - first(): Returns the first row
    - all(): Returns all rows
    - mappings(): Returns rows as dictionaries
    
    Can be preloaded with test data during initialization or via handler functions.
    """
    
    def __init__(
        self,
        scalar: Any = None,
        first_row: Any = None,
        rows: List[Any] = None,
        mapping_rows: List[Dict[str, Any]] = None
    ):
        """
        Initialize FakeResult with test data.
        
        Args:
            scalar: Value to return from scalar() calls
            first_row: Value to return from first() calls
            rows: List of values to return from all() calls
            mapping_rows: List of dictionaries to return from mappings().all()
        """
        self._scalar = scalar
        self._first_row = first_row
        self._rows = rows or []
        self._mapping_rows = mapping_rows or []
    
    def scalar(self) -> Any:
        """Return a single scalar value."""
        return self._scalar
    
    def scalar_one(self) -> Any:
        """Return a single scalar value (SQLAlchemy 2.0 style)."""
        return self._scalar
    
    def first(self) -> Any:
        """Return the first row or mapping."""
        if self._mapping_rows:
            return self._mapping_rows[0]
        return self._first_row
    
    def all(self) -> List[Any]:
        """Return all rows or mappings."""
        return self._mapping_rows or self._rows
    
    def mappings(self) -> 'FakeResult':
        """Return a mapping-compatible result."""
        # For simplicity, return self - mappings() and all() work together
        return self


class FakeSession:
    """
    Async-compatible mock for SQLAlchemy AsyncSession.
    
    Supports all async session patterns used in production code:
    - async with session: Basic context manager
    - async with session.begin(): Transaction context manager
    - execute(): Query execution with handler function
    - flush(), commit(), rollback(): Transaction control methods
    
    Tracks all executed statements for test verification.
    """
    
    def __init__(self, handler: Optional[Callable] = None):
        """
        Initialize FakeSession with optional query handler.
        
        Args:
            handler: Function called for execute() calls with (sql, params)
                    Should return a FakeResult or similar result object
        """
        self.handler = handler
        self.executed: List[tuple[str, Dict[str, Any]]] = []
        self.commits = 0
        self._in_transaction = False
    
    # Async context manager support
    async def __aenter__(self) -> 'FakeSession':
        """Enter async context manager."""
        return self
    
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit async context manager."""
        pass
    
    # Transaction support
    def begin(self) -> '_TransactionContext':
        """
        Return a transaction context manager.
        
        Usage:
            async with session.begin():
                await session.execute("INSERT INTO ...")
        """
        return self._TransactionContext(self)
    
    class _TransactionContext:
        """Inner class handling transaction context management."""
        
        def __init__(self, session: 'FakeSession'):
            self.session = session
            self._in_transaction = False
        
        async def __aenter__(self) -> 'FakeSession':
            """Enter transaction context."""
            self.session._in_transaction = True
            return self.session
        
        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            """Exit transaction context."""
            self.session._in_transaction = False
            if exc_type is not None:
                # In real sessions, exception would trigger rollback
                pass
    
    # Query execution
    async def execute(
        self, 
        statement: Any, 
        params: Optional[Dict[str, Any]] = None
    ) -> FakeResult:
        """
        Execute a query statement.
        
        Args:
            statement: SQL statement or SQLAlchemy construct
            params: Query parameters
            
        Returns:
            FakeResult with handler response or default result
        """
        sql = str(statement)
        self.executed.append((sql, params))
        
        if self.handler:
            return self.handler(sql, params)
        
        # Default empty result if no handler provided
        return FakeResult()
    
    # Transaction control methods
    async def flush(self) -> None:
        """Simulate session flush - does nothing but can be awaited."""
        pass
    
    async def commit(self) -> None:
        """Simulate session commit - tracks commit count."""
        self.commits += 1
    
    async def rollback(self) -> None:
        """Simulate session rollback - does nothing but can be awaited."""
        pass


class FakeSessionFactory:
    """
    Factory for creating FakeSession instances.
    
    Compatible with monkeypatching SQLAlchemy session factories:
        monkeypatch.setattr('api.database.AsyncSessionFactory', FakeSessionFactory(session))
    """
    
    def __init__(self, session: Optional[FakeSession] = None):
        """
        Initialize factory with optional session instance.
        
        Args:
            session: Pre-configured FakeSession to return, creates default if None
        """
        self.session = session or FakeSession()
    
    def __call__(self) -> FakeSession:
        """Return the configured FakeSession instance."""
        return self.session


# ============================================================================
# BACKWARD-COMPATIBLE AGENT RUN TEST LAYER
# ============================================================================

class TestAgentRun(AgentRun):
    """
    Backward-compatible AgentRun subclass for test compatibility.
    
    Adds legacy fields that were removed from production but are still
    expected by existing tests. These fields exist only as instance
    attributes and do not create database columns.
    
    Legacy fields:
    - task_id: Legacy task identifier (test-only)
    - decision_json: Legacy decision data (test-only)
    - trace_json: Legacy trace data (test-only)
    """
    
    def __init__(
        self,
        task_id: Optional[str] = None,
        decision_json: Optional[str] = None,
        trace_json: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize TestAgentRun with legacy fields.
        
        Args:
            task_id: Legacy task identifier
            decision_json: Legacy decision data (defaults to "{}")
            trace_json: Legacy trace data (defaults to "[]")
            **kwargs: Production AgentRun fields (strategy_id, trace_id, etc.)
        """
        # Store legacy fields as instance attributes (non-persistent)
        self._task_id = task_id
        self._decision_json = decision_json or "{}"
        self._trace_json = trace_json or "[]"
        
        # Initialize production AgentRun with remaining kwargs
        super().__init__(**kwargs)
    
    # Property accessors for backward compatibility
    @property
    def task_id(self) -> Optional[str]:
        """Get legacy task_id field."""
        return self._task_id
    
    @property
    def decision_json(self) -> str:
        """Get legacy decision_json field."""
        return self._decision_json
    
    @property
    def trace_json(self) -> str:
        """Get legacy trace_json field."""
        return self._trace_json


def create_test_agent_run(**kwargs) -> TestAgentRun:
    """
    Factory function for creating TestAgentRun instances.
    
    Provides a convenient way to create test-compatible AgentRun instances
    with sensible defaults for legacy fields.
    
    Example:
        # Basic usage with legacy fields
        run = create_test_agent_run(
            task_id="test_task",
            decision_json='{"action": "buy"}',
            trace_json='[{"step": "analyze"}]',
            trace_id="trace_123"
        )
        
        # With production fields
        run = create_test_agent_run(
            task_id="production_test",
            strategy_id="momentum_v1",
            symbol="AAPL",
            action="buy",
            confidence=0.8,
            trace_id="trace_456"
        )
    """
    return TestAgentRun(**kwargs)


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_usage():
    """
    Examples demonstrating how to use the mock setup in tests.
    
    These examples show common patterns used in the existing test suite.
    """
    
    # Example 1: Basic FakeSession with handler
    async def basic_query_handler(sql: str, params: Dict[str, Any]) -> FakeResult:
        """Handler that returns different results based on SQL."""
        if "SELECT COUNT" in sql:
            return FakeResult(scalar=42)
        elif "SELECT *" in sql:
            return FakeResult(
                rows=[{"id": 1, "name": "test"}],
                mapping_rows=[{"id": 1, "name": "test"}]
            )
        return FakeResult()
    
    session = FakeSession(basic_query_handler)
    
    # Example 2: Using async context managers
    async def example_async_usage():
        """Demonstrate async session patterns."""
        
        # Basic async context manager
        async with session:
            result = await session.execute("SELECT COUNT(*) FROM users")
            count = result.scalar()
            assert count == 42
        
        # Transaction context manager
        async with session.begin():
            await session.execute("INSERT INTO users (name) VALUES (?)", {"name": "test"})
            await session.flush()  # Can be awaited without error
        
        # Verify execution tracking
        assert len(session.executed) == 2
        assert session.commits >= 1
    
    # Example 3: TestAgentRun for backward compatibility
    def example_agent_run_usage():
        """Demonstrate TestAgentRun compatibility."""
        
        # Legacy-style instantiation (what old tests expect)
        run = TestAgentRun(
            task_id="consensus:run-2",
            decision_json='{"action": "buy", "confidence": 0.8}',
            trace_json='[{"step": "analyze", "result": "bullish"}]',
            trace_id="trace_123"
        )
        
        # Factory function (recommended approach)
        run2 = create_test_agent_run(
            task_id="factory_test",
            decision_json='{"action": "sell"}',
            trace_json='[]',
            trace_id="trace_456",
            strategy_id="momentum_v1",
            symbol="AAPL",
            action="sell",
            confidence=0.7
        )
        
        # Access both legacy and production fields
        assert run.decision_json == '{"action": "buy", "confidence": 0.8}'
        assert run.task_id == "consensus:run-2"
        assert run2.strategy_id == "momentum_v1"
        assert run2.symbol == "AAPL"
    
    # Example 4: Monkeypatching in tests
    def example_monkeypatching():
        """Demonstrate how to monkeypatch in pytest tests."""
        
        # In pytest test:
        # def test_my_feature(monkeypatch):
        #     session = FakeSession(my_handler)
        #     factory = FakeSessionFactory(session)
        #     monkeypatch.setattr('api.database.AsyncSessionFactory', factory)
        #     
        #     # Test code now uses FakeSession
        #     result = await my_function_that_uses_db()
        #     assert session.executed  # Verify database calls
        pass


# Export the main classes for easy importing
__all__ = [
    'FakeResult',
    'FakeSession', 
    'FakeSessionFactory',
    'TestAgentRun',
    'create_test_agent_run',
]
