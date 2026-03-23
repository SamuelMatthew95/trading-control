"""
Production-safe SQLAlchemy AsyncSession mock setup for pytest tests.

This module provides comprehensive mock classes that simulate SQLAlchemy AsyncSession
behavior without requiring a real database connection. All classes are designed to be
fully compatible with pytest-asyncio and existing test patterns.

Key Features:
- Full AsyncSession compatibility: async with session / session.begin()
- Complete Result API: scalar(), scalar_one(), first(), all(), mappings()
- Transaction tracking and nested transaction support
- Backward-compatible AgentRun test layer
- Cross-database compatibility (SQLite/PostgreSQL)
- Production-safe: no test-only fields in production schema
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Union
from api.core.models import AgentRun


class FakeResult:
    """
    Mock for SQLAlchemy Result objects with complete API compatibility.
    
    Implements all common SQLAlchemy Result methods used in tests:
    - scalar(): Returns a single value (synchronous, like real SQLAlchemy)
    - scalar_one(): Same as scalar() (SQLAlchemy 2.0 compatibility)
    - first(): Returns the first row or mapping
    - all(): Returns all rows or mappings
    - mappings(): Returns mapping-compatible result for chaining
    
    Design Note: All methods are synchronous because SQLAlchemy Result methods
    are synchronous - only session.execute() is async.
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
        # mapping_rows take precedence over first_row (matches SQLAlchemy behavior)
        if self._mapping_rows:
            return self._mapping_rows[0]
        return self._first_row
    
    def all(self) -> List[Any]:
        """Return all rows or mappings."""
        # mapping_rows take precedence over rows (matches SQLAlchemy behavior)
        return self._mapping_rows or self._rows
    
    def mappings(self) -> 'FakeResult':
        """Return a mapping-compatible result."""
        # Return self to enable chaining: result.mappings().all()
        return self


class FakeSession:
    """
    Async-compatible mock for SQLAlchemy AsyncSession.
    
    Simulates AsyncSession behavior including:
    - Async context managers: async with session / session.begin()
    - Query execution with custom handlers
    - Transaction tracking and nested transaction support
    - Execution tracking for test assertions
    
    Design Note: Handler functions must be synchronous because they're called
    within the async execute() method, making the overall flow async while
    keeping handlers simple and testable.
    """
    
    def __init__(self, handler: Optional[Callable[[str, Dict[str, Any]], FakeResult]] = None):
        """
        Initialize FakeSession with optional query handler.
        
        Args:
            handler: Synchronous function called for execute() with (sql, params)
                    Should return a FakeResult. Handler enables custom test scenarios.
        """
        self.handler = handler
        self.executed: List[tuple[str, Optional[Dict[str, Any]]]] = []
        self.commits = 0
        self.rollbacks = 0
        self._transaction_depth = 0  # Track nested transactions
    
    # Async context manager support (matches AsyncSession API)
    async def __aenter__(self) -> 'FakeSession':
        """Enter async context manager."""
        return self
    
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit async context manager."""
        pass
    
    # Transaction support (matches AsyncSession.begin() API)
    def begin(self) -> '_TransactionContext':
        """
        Return a transaction context manager.
        
        Supports nested transactions by tracking depth:
            async with session.begin():  # depth = 1
                async with session.begin():  # depth = 2
                    # operations
                # depth = 1 (inner transaction closed)
            # depth = 0 (outer transaction closed)
        """
        return self._TransactionContext(self)
    
    class _TransactionContext:
        """Inner class handling transaction context management."""
        
        def __init__(self, session: 'FakeSession'):
            self.session = session
            self._start_depth = session._transaction_depth
        
        async def __aenter__(self) -> 'FakeSession':
            """Enter transaction context."""
            self.session._transaction_depth += 1
            return self.session
        
        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            """Exit transaction context."""
            self.session._transaction_depth -= 1
            
            # Only rollback on exception if this was the outermost transaction
            if exc_type is not None and self.session._transaction_depth == 0:
                self.session.rollbacks += 1
            # Auto-commit only on successful exit of outermost transaction
            elif self.session._transaction_depth == 0:
                self.session.commits += 1
    
    # Query execution (matches AsyncSession.execute() API)
    async def execute(
        self, 
        statement: Any, 
        params: Optional[Dict[str, Any]] = None
    ) -> FakeResult:
        """
        Execute a query statement.
        
        Args:
            statement: SQL statement or SQLAlchemy construct
            params: Query parameters (optional)
            
        Returns:
            FakeResult with handler response or default empty result
        """
        sql = str(statement)
        self.executed.append((sql, params))
        
        if self.handler:
            return self.handler(sql, params)
        
        # Default empty result if no handler provided
        return FakeResult()
    
    # Transaction control methods (matches AsyncSession API)
    async def flush(self) -> None:
        """Simulate session flush - no-op but awaitable."""
        pass
    
    async def commit(self) -> None:
        """Simulate session commit - tracks commit count."""
        if self._transaction_depth == 0:
            # Direct commit outside transaction
            self.commits += 1
        # Note: Commits inside transactions are handled by _TransactionContext
    
    async def rollback(self) -> None:
        """Simulate session rollback - tracks rollback count."""
        if self._transaction_depth == 0:
            # Direct rollback outside transaction
            self.rollbacks += 1
        # Note: Rollbacks inside transactions are handled by _TransactionContext
    
    @property
    def in_transaction(self) -> bool:
        """Check if session is currently in a transaction."""
        return self._transaction_depth > 0


class FakeSessionFactory:
    """
    Factory for creating FakeSession instances.
    
    Compatible with monkeypatching SQLAlchemy session factories:
        monkeypatch.setattr('api.database.AsyncSessionFactory', FakeSessionFactory(session))
    
    Design Note: Implements __call__ to match factory pattern used by SQLAlchemy.
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
    attributes and do NOT create database columns, keeping production schema clean.
    
    Legacy Test-Only Fields:
    - task_id: Legacy task identifier (test-only)
    - decision_json: Legacy decision data (defaults to "{}")
    - trace_json: Legacy trace data (defaults to "[]")
    
    Production Fields Work Normally:
    - strategy_id, trace_id, symbol, action, confidence, created_at, etc.
    
    Design Note: Uses properties instead of Column definitions to ensure
    these fields never create database columns while maintaining test compatibility.
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
            task_id: Legacy task identifier (test-only, not persisted)
            decision_json: Legacy decision data (test-only, defaults to "{}")
            trace_json: Legacy trace data (test-only, defaults to "[]")
            **kwargs: Production AgentRun fields (strategy_id, trace_id, etc.)
        """
        # Store legacy fields as instance attributes (non-persistent)
        self._task_id = task_id
        self._decision_json = decision_json or "{}"
        self._trace_json = trace_json or "[]"
        
        # Initialize production AgentRun with remaining kwargs
        super().__init__(**kwargs)
    
    # Property accessors for backward compatibility (read-only)
    @property
    def task_id(self) -> Optional[str]:
        """Get legacy task_id field (test-only)."""
        return self._task_id
    
    @property
    def decision_json(self) -> str:
        """Get legacy decision_json field (test-only)."""
        return self._decision_json
    
    @property
    def trace_json(self) -> str:
        """Get legacy trace_json field (test-only)."""
        return self._trace_json


def create_test_agent_run(**kwargs) -> TestAgentRun:
    """
    Factory function for creating TestAgentRun instances.
    
    Provides a convenient way to create test-compatible AgentRun instances
    with sensible defaults for legacy fields while supporting all production fields.
    
    Example:
        # Basic legacy usage
        run = create_test_agent_run(
            task_id="test_task",
            decision_json='{"action": "buy"}',
            trace_json='[{"step": "analyze"}]',
            trace_id="trace_123"
        )
        
        # Mixed legacy + production fields
        run = create_test_agent_run(
            task_id="production_test",
            decision_json='{"action": "sell"}',
            trace_json='[]',
            trace_id="trace_456",
            strategy_id="momentum_v1",
            symbol="AAPL",
            action="sell",
            confidence=0.7
        )
    
    Design Note: Factory pattern provides clean API and handles defaults automatically.
    """
    return TestAgentRun(**kwargs)


# ============================================================================
# CROSS-DATABASE COMPATIBILITY HELPERS
# ============================================================================

def get_cross_database_defaults() -> Dict[str, Any]:
    """
    Get database-appropriate defaults for cross-database compatibility.
    
    Returns configuration for SQLite (CI) and PostgreSQL (production):
    - SQLite: Uses Python-side defaults for compatibility
    - PostgreSQL: Uses server-side defaults for performance
    
    Design Note: Helps tests work consistently across different database backends
    without hardcoding database-specific logic in test code.
    """
    try:
        # Check if PostgreSQL-specific imports are available
        from sqlalchemy.dialects.postgresql.json import JSONB
        from pgvector.sqlalchemy import Vector
        POSTGRES_AVAILABLE = True
    except ImportError:
        POSTGRES_AVAILABLE = False
    
    if POSTGRES_AVAILABLE:
        return {
            'uuid_default': 'gen_random_uuid()::text',
            'datetime_default': 'now()',
            'json_type': JSONB,
            'vector_type': Vector(1536),
            'database_type': 'postgresql'
        }
    else:
        return {
            'uuid_default': None,  # Use Python-side default
            'datetime_default': None,  # Use Python-side default
            'json_type': 'TEXT',
            'vector_type': 'TEXT',
            'database_type': 'sqlite'
        }


# Export the main classes for easy importing
__all__ = [
    'FakeResult',
    'FakeSession', 
    'FakeSessionFactory',
    'TestAgentRun',
    'create_test_agent_run',
    'get_cross_database_defaults',
]
