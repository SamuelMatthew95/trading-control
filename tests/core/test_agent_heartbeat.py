from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.constants import FieldName
from api.services import agent_heartbeat


class _BeginCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.sql_statements: list[str] = []

    def begin(self) -> _BeginCtx:
        return _BeginCtx()

    async def execute(self, stmt, _params=None):
        self.sql_statements.append(str(stmt))
        return SimpleNamespace()


class _SessionFactoryCtx:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_write_heartbeat_upserts_agent_instance_when_missing(monkeypatch):
    session = _Session()
    redis = AsyncMock()
    upsert_calls: list[tuple[str, dict]] = []

    class _FakeStore:
        def upsert_agent(self, agent_name: str, payload: dict) -> None:
            upsert_calls.append((agent_name, payload))

    monkeypatch.setattr(agent_heartbeat, "is_db_available", lambda: True)
    monkeypatch.setattr(agent_heartbeat, "AsyncSessionFactory", lambda: _SessionFactoryCtx(session))
    monkeypatch.setattr(agent_heartbeat, "get_runtime_store", lambda: _FakeStore())

    await agent_heartbeat.write_heartbeat(
        redis=redis,
        agent_name="SIGNAL_AGENT",
        last_event="processed_signal",
        event_count=12,
    )

    assert any("INSERT INTO agent_heartbeats" in sql for sql in session.sql_statements)
    assert any("UPDATE agent_instances" in sql for sql in session.sql_statements)
    assert any("INSERT INTO agent_instances" in sql for sql in session.sql_statements)
    assert len(upsert_calls) == 1
    assert upsert_calls[0][0] == "SIGNAL_AGENT"
    assert upsert_calls[0][1][FieldName.SOURCE] == "heartbeat"


@pytest.mark.asyncio
async def test_write_heartbeat_in_memory_mode_skips_db_calls(monkeypatch):
    redis = AsyncMock()
    upsert_calls: list[tuple[str, dict]] = []

    class _FakeStore:
        def upsert_agent(self, agent_name: str, payload: dict) -> None:
            upsert_calls.append((agent_name, payload))

    def _boom_session_factory():
        raise AssertionError("DB session should not be opened in in-memory mode")

    monkeypatch.setattr(agent_heartbeat, "is_db_available", lambda: False)
    monkeypatch.setattr(agent_heartbeat, "AsyncSessionFactory", _boom_session_factory)
    monkeypatch.setattr(agent_heartbeat, "get_runtime_store", lambda: _FakeStore())

    await agent_heartbeat.write_heartbeat(
        redis=redis,
        agent_name="REASONING_AGENT",
        last_event="decision_emitted",
        event_count=7,
    )

    redis.set.assert_awaited_once()
    assert len(upsert_calls) == 1
    assert upsert_calls[0][0] == "REASONING_AGENT"
    payload = upsert_calls[0][1]
    assert payload["last_event"] == "decision_emitted"
    assert payload["event_count"] == 7
    assert payload[FieldName.SOURCE] == "heartbeat"
