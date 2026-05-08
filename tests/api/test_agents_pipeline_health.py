from __future__ import annotations

import pytest

from api.routes import dashboard_v2


class _BaseRedis:
    """Minimal Redis stub: all agents WAITING, xlen returns 0, EE has no heartbeat."""

    async def get(self, _key):
        return None

    async def xlen(self, _stream):
        return 0


@pytest.mark.asyncio
async def test_agents_status_includes_pipeline_health_key(monkeypatch):
    async def _get_redis():
        return _BaseRedis()

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)
    monkeypatch.setattr(dashboard_v2, "is_db_available", lambda: False)

    payload = await dashboard_v2.get_agents_status()

    assert payload["agents"] is not None
    assert "pipeline_health" in payload


@pytest.mark.asyncio
async def test_pipeline_health_has_required_fields(monkeypatch):
    async def _get_redis():
        return _BaseRedis()

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)
    monkeypatch.setattr(dashboard_v2, "is_db_available", lambda: False)

    payload = await dashboard_v2.get_agents_status()

    pipeline_health = payload["pipeline_health"]
    assert "signal_stream_length" in pipeline_health
    assert "decision_stream_length" in pipeline_health


@pytest.mark.asyncio
async def test_pipeline_health_shows_stream_lengths(monkeypatch):
    class _StreamRedis(_BaseRedis):
        def __init__(self):
            self._call_count = 0

        async def xlen(self, _stream):
            self._call_count += 1
            if self._call_count == 1:
                return 10  # STREAM_SIGNALS
            return 7  # STREAM_DECISIONS

    async def _get_redis():
        return _StreamRedis()

    monkeypatch.setattr(dashboard_v2, "get_redis", _get_redis)
    monkeypatch.setattr(dashboard_v2, "is_db_available", lambda: False)

    payload = await dashboard_v2.get_agents_status()

    pipeline_health = payload["pipeline_health"]
    assert pipeline_health["signal_stream_length"] == 10
    assert pipeline_health["decision_stream_length"] == 7
