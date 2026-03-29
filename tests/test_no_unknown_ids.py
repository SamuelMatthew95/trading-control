"""
Regression test - prevents id=unknown forever.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from api.core.writer import safe_writer as safe_writer_module


class _FakeInsertStmt:
    def on_conflict_do_nothing(self, **kwargs):
        return self


class _FakePgInsert:
    def values(self, **kwargs):
        return _FakeInsertStmt()


class _FakeResult:
    rowcount = 1


class _FakeSession:
    async def execute(self, _stmt):
        return _FakeResult()

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_write_system_metric_logs_real_id(caplog, safe_writer, monkeypatch):
    caplog.set_level("INFO")
    """Prevents regression of id=unknown bug."""

    @asynccontextmanager
    async def fake_transaction():
        yield _FakeSession()

    safe_writer.transaction = fake_transaction

    async def _fake_claim(*args, **kwargs):
        return True

    safe_writer._claim_message = _fake_claim
    monkeypatch.setattr(safe_writer_module, "pg_insert", lambda _model: _FakePgInsert())

    msg_id = "123e4567-e89b-12d3-a456-426614174000"

    await safe_writer.write_system_metric(
        msg_id=msg_id,
        metric_name="test",
        metric_value=1.0,
        metric_unit=None,
        tags={},
        schema_version="v2",
        source="test",
        timestamp=datetime.now(timezone.utc),
    )

    assert f"id={msg_id}" in caplog.text
    assert "id=unknown" not in caplog.text
