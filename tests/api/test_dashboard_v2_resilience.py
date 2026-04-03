from __future__ import annotations

import pytest

from api.routes import dashboard_v2


class _ExplodingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("db unavailable")


def _exploding_factory():
    return _ExplodingSession()


@pytest.mark.asyncio
async def test_trade_feed_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_trade_feed()

    assert payload["count"] == 0
    assert payload["trades"] == []
    assert payload["error"] == "trade_feed_unavailable"


@pytest.mark.asyncio
async def test_performance_trends_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_performance_trends()

    assert payload["summary"]["total_trades"] == 0
    assert payload["daily_pnl"] == []
    assert payload["grade_trend"] == []
    assert payload["error"] == "performance_trends_unavailable"


@pytest.mark.asyncio
async def test_agent_instances_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_agent_instances()

    assert payload["instances"] == []
    assert payload["active_count"] == 0
    assert payload["retired_count"] == 0
    assert payload["error"] == "agent_instances_unavailable"


def test_system_metrics_alias_route_exists():
    paths = {route.path for route in dashboard_v2.router.routes}
    assert "/dashboard/system-metrics" in paths


@pytest.mark.asyncio
async def test_event_history_falls_back_when_query_fails(monkeypatch):
    monkeypatch.setattr(dashboard_v2, "AsyncSessionFactory", _exploding_factory)
    payload = await dashboard_v2.get_event_history()

    assert payload["stream_counts"] == []
    assert payload["persisted_events"] == []
    assert payload["persisted_logs"] == []
