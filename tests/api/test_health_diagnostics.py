from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.in_memory_store import InMemoryStore
from api.routes.health import health_check


@pytest.mark.asyncio
async def test_health_check_reports_degraded_diagnostics(monkeypatch):
    store = InMemoryStore()
    store.event_history.append({"event_type": "signal", "timestamp": 111.0})
    store.trade_feed.append({"created_at": 222.0})
    store.grade_history.append({"timestamp": 333.0})
    store.reflections.append({"created_at": 444.0})
    store.agents["SIGNAL_AGENT"] = {"status": "active"}

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                db_engine=object(),
                redis_client=None,
                event_pipeline=None,
                websocket_broadcaster=None,
                in_memory_store=store,
            )
        )
    )

    async def _db_down(_request):
        return False

    async def _redis_down(_request):
        return False

    monkeypatch.setattr("api.routes.health._database_ready", _db_down)
    monkeypatch.setattr("api.routes.health._redis_ready", _redis_down)

    payload = await health_check(request)

    assert payload["status"] == "degraded"
    assert payload["db_connected"] is False
    assert payload["redis_connected"] is False
    assert payload["persistence_mode"] == "in_memory_fallback"
    assert payload["degraded_reasons"] == ["database_unavailable", "redis_unavailable"]
    assert payload["active_agents"] == ["SIGNAL_AGENT"]
    assert payload["last_signal_at"] == 111.0
    assert payload["last_trade_at"] == 222.0
    assert payload["last_grade_at"] == 333.0
    assert payload["last_reflection_at"] == 444.0
