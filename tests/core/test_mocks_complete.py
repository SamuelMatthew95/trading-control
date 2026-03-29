"""
Production-safe SQLAlchemy mock setup for async pytest tests.

This module provides comprehensive mock classes that simulate SQLAlchemy behavior
without requiring a real database connection. All classes are designed to be
fully compatible with async pytest tests and existing code patterns.

Features:
- Full async support for sessions and transactions
- Complete SQLAlchemy-like API for query results
- Backward-compatible AgentRun test layer
- Cross-database compatibility (SQLite/PostgreSQL)
- Minimal boilerplate with maximum compatibility
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.core.models import AgentRun


class FakeResult:
    """
    Comprehensive mock for SQLAlchemy Result objects.

    Supports all common SQLAlchemy Result methods used in tests:
    - scalar(): Returns a single value
    - scalar_one(): Returns a single value (SQLAlchemy 2.0 style)
    - first(): Returns the first row or mapping
    - all(): Returns all rows or mappings
    - mappings(): Returns mapping-compatible result

    Handles edge cases: None values, empty results, mixed data types.
    """

    def __init__(
        self,
        scalar: Any = None,
        first_row: Any = None,
        rows: list[Any] = None,
        mapping_rows: list[dict[str, Any]] = None,
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

    def all(self) -> list[Any]:
        """Return all rows or mappings."""
        return self._mapping_rows or self._rows

    def mappings(self) -> FakeResult:
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

    Tracks all executed statements for test verification and supports
    cross-database compatibility without affecting production.
    """

    def __init__(self, handler: Callable | None = None):
        """
        Initialize FakeSession with optional query handler.

        Args:
            handler: Function called for execute() calls with (sql, params)
                    Should return a FakeResult or similar result object
                    Function should be synchronous (not async) for compatibility
        """
        self.handler = handler
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self._in_transaction = False

    # Async context manager support
    async def __aenter__(self) -> FakeSession:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit async context manager."""
        pass

    # Transaction support
    def begin(self) -> _TransactionContext:
        """
        Return a transaction context manager.

        Usage:
            async with session.begin():
                await session.execute("INSERT INTO ...")
        """
        return self._TransactionContext(self)

    class _TransactionContext:
        """Inner class handling transaction context management."""

        def __init__(self, session: FakeSession):
            self.session = session
            self._was_in_transaction = session._in_transaction

        async def __aenter__(self) -> FakeSession:
            """Enter transaction context."""
            self.session._in_transaction = True
            return self.session

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            """Exit transaction context."""
            # Only set to False if this was the outermost transaction
            if not self._was_in_transaction:
                self.session._in_transaction = False
            if exc_type is not None:
                # In real sessions, exception would trigger rollback
                # Our mock tracks the state but doesn't perform actual rollback
                pass
            else:
                # Successful transaction - in real SQLAlchemy this would commit
                # Our mock doesn't auto-commit to match real behavior
                pass

    # Query execution
    async def execute(
        self, statement: Any, params: dict[str, Any] | None = None
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

    Supports both default session creation and custom pre-configured sessions.
    """

    def __init__(self, session: FakeSession | None = None):
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
    attributes and do not create database columns, keeping production schema clean.

    Legacy fields (test-only):
    - task_id: Legacy task identifier
    - decision_json: Legacy decision data (defaults to "{}")
    - trace_json: Legacy trace data (defaults to "[]")

    Production fields work normally:
    - strategy_id, trace_id, symbol, action, confidence, created_at, etc.
    """

    def __init__(
        self,
        task_id: str | None = None,
        decision_json: str | None = None,
        trace_json: str | None = None,
        **kwargs,
    ):
        """
        Initialize TestAgentRun with legacy fields.

        Args:
            task_id: Legacy task identifier (test-only)
            decision_json: Legacy decision data (test-only)
            trace_json: Legacy trace data (test-only)
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
    def task_id(self) -> str | None:
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
    with sensible defaults for legacy fields while maintaining production field support.

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
# CROSS-DATABASE COMPATIBILITY HELPERS
# ============================================================================


def get_cross_database_defaults():
    """
    Get database-appropriate defaults for cross-database compatibility.

    Returns configuration for SQLite (CI) and PostgreSQL (production):
    - SQLite: Uses Python-side defaults for compatibility
    - PostgreSQL: Uses server-side defaults for performance

    This function helps maintain cross-database compatibility in tests.
    """
    try:
        from pgvector.sqlalchemy import Vector
        from sqlalchemy.dialects.postgresql.json import JSONB

        postgres_available = True
    except ImportError:
        postgres_available = False

    if postgres_available:
        return {
            "uuid_default": "gen_random_uuid()::text",
            "datetime_default": "now()",
            "json_type": JSONB,
            "vector_type": Vector(1536),
        }
    return {
        "uuid_default": None,  # Use Python-side default
        "datetime_default": None,  # Use Python-side default
        "json_type": "TEXT",
        "vector_type": "TEXT",
    }


# Export the main classes for easy importing
__all__ = [
    "FakeResult",
    "FakeSession",
    "FakeSessionFactory",
    "TestAgentRun",
    "create_test_agent_run",
    "get_cross_database_defaults",
]
