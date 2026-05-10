from __future__ import annotations

import pytest

from api.services.dashboard_source_selector import DashboardReadSelector


@pytest.mark.asyncio
async def test_select_resource_prefers_db_when_healthy(monkeypatch):
    monkeypatch.setattr("api.services.dashboard_source_selector.is_db_available", lambda: True)
    selector = DashboardReadSelector()
    result = await selector.select_resource(
        resource_name="orders",
        db_source=lambda: {"source": "db"},
        runtime_source=lambda: {"source": "in_memory"},
        empty_source=lambda: {"source": "empty"},
    )
    assert result["source"] == "db"


@pytest.mark.asyncio
async def test_select_resource_uses_runtime_when_db_unhealthy(monkeypatch):
    monkeypatch.setattr("api.services.dashboard_source_selector.is_db_available", lambda: False)
    selector = DashboardReadSelector()
    result = await selector.select_resource(
        resource_name="orders",
        db_source=lambda: {"source": "db"},
        runtime_source=lambda: {"source": "in_memory"},
        empty_source=lambda: {"source": "empty"},
    )
    assert result["source"] == "in_memory"


@pytest.mark.asyncio
async def test_select_resource_uses_empty_when_runtime_empty(monkeypatch):
    monkeypatch.setattr("api.services.dashboard_source_selector.is_db_available", lambda: False)
    selector = DashboardReadSelector()
    result = await selector.select_resource(
        resource_name="orders",
        db_source=lambda: {"source": "db"},
        runtime_source=lambda: {"items": []},
        empty_source=lambda: {"source": "empty"},
        is_empty=lambda p: p == {"items": []},
    )
    assert result["source"] == "empty"
