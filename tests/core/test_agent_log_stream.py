"""Tests for the shared SSE agent-log streamer (api/services/agent_log_stream.py).

Covers the two bugs the per-route copies shared before consolidation:
- /health/logs ran SQL in memory mode instead of degrading gracefully;
- the initial-query session stayed open for the SSE stream's whole lifetime
  (one pinned pool connection per connected client).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from api.constants import FieldName
from api.services.agent_log_stream import (
    _agent_log_generator,
    memory_mode_log_stream_response,
)


class _FakeRow:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self):
        return self._rows


_PROBE_COLUMNS = [
    ("created_at", "timestamptz"),
    ("agent_run_id", "varchar"),
    ("log_level", "varchar"),
    ("trace_id", "varchar"),
    ("message", "text"),
]


class _FakeSessionFactory:
    """Counts session enters/exits so tests can assert connection lifecycle."""

    def __init__(self, rows):
        self.rows = rows
        self.opened = 0
        self.closed = 0

    def __call__(self):
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, factory: _FakeSessionFactory):
        self._factory = factory

    async def __aenter__(self):
        self._factory.opened += 1
        return self

    async def __aexit__(self, *exc_info):
        self._factory.closed += 1
        return False

    async def execute(self, sql, params=None):
        if "information_schema" in str(sql):
            return _FakeResult(_PROBE_COLUMNS)
        return _FakeResult(self._factory.rows)


async def test_memory_mode_response_emits_single_empty_frame():
    response = memory_mode_log_stream_response()
    assert response.media_type == "text/event-stream"

    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 1
    payload = json.loads(chunks[0].removeprefix("data: "))
    assert payload[FieldName.MODE] == "memory"
    assert payload[FieldName.LOGS] == []


async def test_initial_session_closed_before_first_frame_is_yielded():
    """Regression: the poll loop must not hold the initial query's connection."""
    row = _FakeRow(
        id=1,
        agent_run_id="SIGNAL_AGENT",
        log_level="INFO",
        message="hello",
        step_name=None,
        step_data=None,
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        trace_id="t-1",
    )
    factory = _FakeSessionFactory(rows=[row])
    generator = _agent_log_generator(
        factory,
        limit=10,
        agent_id=None,
        level=None,
        ts_field=FieldName.CREATED_AT,
        include_trace_id=True,
    )
    try:
        frame = await anext(generator)
    finally:
        await generator.aclose()

    payload = json.loads(frame.removeprefix("data: "))
    assert payload[FieldName.MESSAGE] == "hello"
    assert payload[FieldName.TRACE_ID] == "t-1"
    assert payload[FieldName.CREATED_AT] == "2026-01-01T00:00:00+00:00"
    # The initial session must already be closed when the first frame arrives.
    assert factory.opened == 1
    assert factory.closed == 1


async def test_trace_id_and_ts_field_are_parameterized():
    row = _FakeRow(
        id=2,
        agent_run_id="REASONING_AGENT",
        log_level="INFO",
        message="m",
        step_name=None,
        step_data=None,
        ts=datetime(2026, 1, 2, tzinfo=timezone.utc),
        trace_id="t-2",
    )
    factory = _FakeSessionFactory(rows=[row])
    generator = _agent_log_generator(
        factory,
        limit=10,
        agent_id=None,
        level=None,
        ts_field=FieldName.TIMESTAMP,
        include_trace_id=False,
    )
    try:
        frame = await anext(generator)
    finally:
        await generator.aclose()

    payload = json.loads(frame.removeprefix("data: "))
    assert FieldName.TRACE_ID not in payload
    assert FieldName.TIMESTAMP in payload
    assert FieldName.CREATED_AT not in payload
