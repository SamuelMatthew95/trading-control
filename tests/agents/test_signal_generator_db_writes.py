"""Functional tests for SignalGenerator database write patterns.

Tests the actual SQL execution flow using FakeSession to capture
every statement sent to the database, then asserts on:
  - Column lists in INSERT statements
  - RETURNING id is used and the integer result drives UPDATEs
  - events INSERT has all required columns (data, idempotency_key, etc.)
  - source / schema_version appear in every write
  - No UUID is passed as agent_runs.id
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.core.async_sqlalchemy_mocks import FakeResult, FakeSession, FakeSessionFactory

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FAKE_DB_RUN_ID = 99  # integer PK returned by RETURNING id


def _make_handler() -> tuple[FakeSession, list[tuple[str, Any]]]:
    """Return a FakeSession that records all calls and returns sensible defaults."""
    calls: list[tuple[str, Any]] = []

    def handler(sql: str, params: Any) -> FakeResult:
        calls.append((sql, params))
        if "RETURNING id" in sql:
            # Simulate PostgreSQL returning integer sequence value
            return FakeResult(first_row=(_FAKE_DB_RUN_ID,))
        if "SELECT 1 FROM processed_events" in sql:
            # No duplicate → allow processing
            return FakeResult(first_row=None)
        if "SELECT id FROM agent_pool" in sql:
            return FakeResult(first_row=("pool-uuid-abc",))
        return FakeResult(first_row=None)

    session = FakeSession(handler=handler)
    return session, calls


def _make_fake_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="1-0")
    bus.redis = MagicMock()
    bus.redis.set = AsyncMock()
    return bus


def _make_fake_dlq() -> MagicMock:
    dlq = MagicMock()
    dlq.send = AsyncMock()
    return dlq


_SAMPLE_PAYLOAD = {
    "payload": json.dumps(
        {
            "symbol": "BTC/USD",
            "price": 43000.0,
            "pct": 2.5,
            "trace_id": "test-trace-001",
        }
    ),
    "msg_id": "msg-001",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalGeneratorDBWrites:
    """Verify the exact SQL patterns emitted by SignalGenerator.process()."""

    @pytest.fixture(autouse=True)
    def _patch_session_factory(self, monkeypatch):
        """Replace AsyncSessionFactory with a FakeSessionFactory for every test."""
        self._session, self._calls = _make_handler()
        factory = FakeSessionFactory(self._session)
        monkeypatch.setattr(
            "api.services.signal_generator.AsyncSessionFactory",
            factory,
        )

    @pytest.fixture(autouse=True)
    def _patch_heartbeat(self, monkeypatch):
        """Stub the shared heartbeat writer so it doesn't need real Redis."""
        monkeypatch.setattr(
            "api.services.signal_generator.AsyncSessionFactory",
            FakeSessionFactory(self._session if hasattr(self, "_session") else FakeSession()),
        )

    async def _run_process(self, monkeypatch) -> None:
        from api.services.signal_generator import SignalGenerator

        bus = _make_fake_bus()
        dlq = _make_fake_dlq()
        sg = SignalGenerator(bus, dlq)
        # Patch AsyncSessionFactory again after __init__ (in case of import-time binding)
        monkeypatch.setattr(
            "api.services.signal_generator.AsyncSessionFactory",
            FakeSessionFactory(self._session),
        )
        await sg.process(_SAMPLE_PAYLOAD)

    def _sqls(self) -> list[str]:
        return [sql for sql, _ in self._session.executed]

    def _params_for(self, keyword: str) -> dict | None:
        for sql, params in self._session.executed:
            if keyword in sql:
                return params
        return None

    # -- agent_runs INSERT ---------------------------------------------------

    async def test_agent_runs_insert_has_returning_id(self, monkeypatch):
        """INSERT INTO agent_runs must have RETURNING id (integer PK pattern)."""
        await self._run_process(monkeypatch)
        sqls = self._sqls()
        insert_sql = next((s for s in sqls if "INSERT INTO agent_runs" in s), None)
        assert insert_sql is not None, "No INSERT INTO agent_runs executed"
        assert "RETURNING id" in insert_sql, (
            "INSERT must use RETURNING id — agent_runs.id is an integer sequence, not a UUID column"
        )

    async def test_agent_runs_insert_has_no_id_column(self, monkeypatch):
        """agent_runs INSERT must not pass id (avoids UUID→integer type error)."""
        await self._run_process(monkeypatch)
        sqls = self._sqls()
        insert_sql = next((s for s in sqls if "INSERT INTO agent_runs" in s), None)
        assert insert_sql is not None

        # Extract the column list: text between ( and ) before VALUES
        col_section = insert_sql.split("VALUES")[0]
        match_cols = col_section[col_section.rfind("(") + 1 : col_section.rfind(")")]
        col_names = [c.strip() for c in match_cols.split(",")]
        assert "id" not in col_names, f"'id' must not be in INSERT column list. Got: {col_names}"

    async def test_agent_runs_insert_has_source(self, monkeypatch):
        """agent_runs INSERT must include source column."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO agent_runs")
        assert params is not None, "No INSERT INTO agent_runs params found"
        assert "source" in params, (
            f"INSERT INTO agent_runs params missing 'source'. Got: {list(params.keys())}"
        )

    async def test_agent_runs_insert_has_schema_version(self, monkeypatch):
        """agent_runs INSERT must include schema_version = 'v3'."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO agent_runs")
        assert params is not None
        assert "schema_version" in params
        assert params["schema_version"] == "v3", (
            f"schema_version must be 'v3', got {params['schema_version']!r}"
        )

    async def test_agent_runs_update_uses_integer_id(self, monkeypatch):
        """UPDATE agent_runs WHERE id=:id must pass the integer returned by RETURNING."""
        await self._run_process(monkeypatch)
        update_params = self._params_for("UPDATE agent_runs")
        assert update_params is not None, "No UPDATE agent_runs found"
        id_val = update_params.get("id")
        assert id_val == _FAKE_DB_RUN_ID, (
            f"UPDATE must use integer db_run_id ({_FAKE_DB_RUN_ID}), not a UUID. Got: {id_val!r}"
        )

    # -- events INSERT -------------------------------------------------------

    async def test_events_insert_has_data_column(self, monkeypatch):
        """events INSERT must include data (JSONB) — column was missing in live DB."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO events")
        assert params is not None, "No INSERT INTO events executed"
        assert "data" in params, (
            f"INSERT INTO events params missing 'data'. Got: {list(params.keys())}"
        )

    async def test_events_insert_has_idempotency_key(self, monkeypatch):
        """events INSERT must include idempotency_key for ON CONFLICT dedup."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO events")
        assert params is not None
        assert "idem_key" in params or "idempotency_key" in params, (
            f"INSERT INTO events params missing idempotency key. Got: {list(params.keys())}"
        )

    async def test_events_insert_has_schema_version(self, monkeypatch):
        """events INSERT must include schema_version."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO events")
        assert params is not None
        assert "schema_version" in params, (
            f"events INSERT missing schema_version. Got: {list(params.keys())}"
        )

    async def test_events_on_conflict_present(self, monkeypatch):
        """events INSERT must have ON CONFLICT (idempotency_key) DO NOTHING."""
        await self._run_process(monkeypatch)
        sqls = self._sqls()
        events_sql = next((s for s in sqls if "INSERT INTO events" in s), None)
        assert events_sql is not None
        assert "ON CONFLICT" in events_sql, "events INSERT must have ON CONFLICT clause for dedup"

    # -- agent_grades INSERT -------------------------------------------------

    async def test_agent_grades_insert_has_source(self, monkeypatch):
        """agent_grades INSERT must include source."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO agent_grades")
        assert params is not None, "No INSERT INTO agent_grades executed"
        assert "source" in params, (
            f"agent_grades INSERT missing 'source'. Got: {list(params.keys())}"
        )

    async def test_agent_grades_insert_has_schema_version(self, monkeypatch):
        """agent_grades INSERT must include schema_version."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO agent_grades")
        assert params is not None
        assert "schema_version" in params

    # -- agent_logs INSERT ---------------------------------------------------

    async def test_agent_logs_insert_has_source(self, monkeypatch):
        """agent_logs INSERT must include source."""
        await self._run_process(monkeypatch)
        params = self._params_for("INSERT INTO agent_logs")
        assert params is not None, "No INSERT INTO agent_logs executed"
        assert "source" in params, f"agent_logs INSERT missing 'source'. Got: {list(params.keys())}"
