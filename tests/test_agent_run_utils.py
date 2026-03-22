"""
Test utilities for AgentRun model compatibility.

This module provides backward-compatible test utilities that allow existing tests
to continue working with the legacy AgentRun interface while the production model
remains clean and focused on production-ready fields only.

The TestAgentRun class extends AgentRun with temporary fields that were removed
from production but are still expected by existing tests:
- decision_json: Legacy field for decision data
- trace_json: Legacy field for trace data  
- task_id: Legacy field for task identification

This approach allows:
1. Production schema to remain clean and focused
2. Existing tests to run without modification
3. Gradual migration path for test updates
4. Cross-database compatibility (SQLite/Postgres)
"""

from typing import Optional
from api.core.models import AgentRun


class TestAgentRun(AgentRun):
    """
    Test-compatible AgentRun subclass that adds legacy fields for backward compatibility.
    
    This class extends the production AgentRun model with temporary fields that
    were removed from production but are still expected by existing tests.
    
    Legacy fields added:
    - decision_json: Temporary field for decision data (tests expect this)
    - trace_json: Temporary field for trace data (tests expect this)
    - task_id: Temporary field for task identification (tests expect this)
    
    Note: These fields exist only in test code and are NOT part of the production schema.
    They are stored as instance attributes and do not create database columns.
    """
    
    def __init__(
        self,
        decision_json: Optional[str] = None,
        trace_json: Optional[str] = None,
        task_id: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize TestAgentRun with legacy fields for test compatibility.
        
        Args:
            decision_json: Legacy decision data (test-only field)
            trace_json: Legacy trace data (test-only field)
            task_id: Legacy task identifier (test-only field)
            **kwargs: Production AgentRun fields
        """
        # Store legacy fields as instance attributes (non-persistent)
        self._decision_json = decision_json or "{}"
        self._trace_json = trace_json or "[]"
        self._task_id = task_id
        
        # Initialize production AgentRun
        super().__init__(**kwargs)
    
    @property
    def decision_json(self) -> str:
        """Get legacy decision_json field for test compatibility."""
        return self._decision_json
    
    @decision_json.setter
    def decision_json(self, value: str):
        """Set legacy decision_json field for test compatibility."""
        self._decision_json = value
    
    @property
    def trace_json(self) -> str:
        """Get legacy trace_json field for test compatibility."""
        return self._trace_json
    
    @trace_json.setter
    def trace_json(self, value: str):
        """Set legacy trace_json field for test compatibility."""
        self._trace_json = value
    
    @property
    def task_id(self) -> Optional[str]:
        """Get legacy task_id field for test compatibility."""
        return self._task_id
    
    @task_id.setter
    def task_id(self, value: Optional[str]):
        """Set legacy task_id field for test compatibility."""
        self._task_id = value


def create_test_agent_run(
    task_id: str = "test_task",
    decision_json: str = "{}",
    trace_json: str = "[]",
    trace_id: str = "test_trace",
    strategy_id: Optional[str] = None,
    symbol: Optional[str] = None,
    signal_data: Optional[dict] = None,
    **kwargs
) -> TestAgentRun:
    """
    Factory function to create TestAgentRun instances with sensible defaults.
    
    This factory provides a convenient way to create test-compatible AgentRun
    instances with all the legacy fields that existing tests expect.
    
    Args:
        task_id: Legacy task identifier (test-only)
        decision_json: Legacy decision data (test-only)
        trace_json: Legacy trace data (test-only)
        trace_id: Required trace identifier for correlation
        strategy_id: Production strategy identifier
        symbol: Trading symbol
        signal_data: Production signal data
        **kwargs: Additional AgentRun fields
        
    Returns:
        TestAgentRun instance with legacy fields for test compatibility
        
    Example:
        # Create a test-compatible AgentRun
        run = create_test_agent_run(
            task_id="my_task",
            decision_json='{"action": "buy", "confidence": 0.8}',
            trace_json='[{"step": "analyze", "result": "bullish"}]',
            trace_id="trace_123",
            strategy_id="momentum_v1",
            symbol="AAPL"
        )
        
        # Access both legacy and production fields
        assert run.decision_json == '{"action": "buy", "confidence": 0.8}'
        assert run.trace_json == '[{"step": "analyze", "result": "bullish"}]'
        assert run.task_id == "my_task"
        assert run.strategy_id == "momentum_v1"
        assert run.symbol == "AAPL"
    """
    return TestAgentRun(
        task_id=task_id,
        decision_json=decision_json,
        trace_json=trace_json,
        trace_id=trace_id,
        strategy_id=strategy_id,
        symbol=symbol,
        signal_data=signal_data,
        **kwargs
    )


# Enhanced FakeSession with proper async context manager support
class FakeSession:
    """
    Enhanced FakeSession that supports async context managers and transactions.
    
    This mock session properly implements the async context manager protocol
    and supports the begin() method for transaction testing, making it compatible
    with modern SQLAlchemy async patterns used in production code.
    """
    
    def __init__(self, handler=None):
        self.handler = handler
        self.executed = []
        self.commits = 0
        self._in_transaction = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        """Return a transaction context manager for async with session.begin()"""
        return self._TransactionContext(self)

    class _TransactionContext:
        """Inner class to handle transaction context management"""
        def __init__(self, session):
            self.session = session
            self._in_transaction = False

        async def __aenter__(self):
            self.session._in_transaction = True
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            self.session._in_transaction = False
            if exc_type is not None:
                # On exception, rollback would happen here
                pass
            return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if self.handler:
            return self.handler(sql, params)
        # Return a minimal result if no handler provided
        return FakeResult()

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1
        return None

    async def rollback(self):
        return None


class FakeResult:
    """Minimal fake result for FakeSession when no handler is provided"""
    def __init__(self, rows=None, first_row=None, mapping_rows=None):
        self._rows = rows or []
        self._first_row = first_row
        self._mapping_rows = mapping_rows or []

    def mappings(self):
        return self

    def all(self):
        return self._mapping_rows or self._rows

    def first(self):
        if self._mapping_rows:
            return self._mapping_rows[0]
        return self._first_row

    def scalar(self):
        return None

    def scalar_one(self):
        return None


class FakeSessionFactory:
    """Factory for creating FakeSession instances"""
    def __init__(self, session=None):
        self.session = session or FakeSession()

    def __call__(self):
        return self.session
