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
    def __init__(self, task_id=None, decision_json=None, trace_json=None, **kwargs):
        self._task_id = task_id
        self._decision_json = decision_json or "{}"
        self._trace_json = trace_json or "[]"
        super().__init__(**kwargs)

    @property
    def task_id(self):
        return self._task_id

    @property
    def decision_json(self):
        return self._decision_json

    @property
    def trace_json(self):
        return self._trace_json


def create_test_agent_run(**kwargs):
    return TestAgentRun(**kwargs)


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
