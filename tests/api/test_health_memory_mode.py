"""GET /health and /readiness behaviour under USE_MEMORY_MODE.

In memory mode the operator has explicitly declared "no Postgres". The
endpoints must:

- Report database as "memory", not "disconnected".
- Stay healthy when Redis is up.
- Skip the DB connect attempt entirely (otherwise we'd spam DNS warnings
  on every health probe).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.routes import health as health_module


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


@pytest.fixture
def memory_mode(monkeypatch):
    """Flip USE_MEMORY_MODE on for the duration of one test."""
    monkeypatch.setattr(health_module.settings, "USE_MEMORY_MODE", True, raising=False)
    # Also stub the DB engine so that even if we accidentally tried to connect,
    # we'd fail loudly rather than hang.
    yield


@pytest.mark.asyncio
async def test_database_ready_short_circuits_in_memory_mode(monkeypatch) -> None:
    """Calling _database_ready under memory mode must NOT touch the engine."""
    monkeypatch.setattr(health_module.settings, "USE_MEMORY_MODE", True, raising=False)

    # Build a fake request whose engine raises if anyone touches it.
    request = MagicMock()
    request.app.state.db_engine.connect = MagicMock(
        side_effect=AssertionError("must not connect in memory mode")
    )
    assert await health_module._database_ready(request) is False
    request.app.state.db_engine.connect.assert_not_called()


@pytest.mark.asyncio
async def test_database_ready_attempts_connection_when_not_memory_mode(monkeypatch) -> None:
    monkeypatch.setattr(health_module.settings, "USE_MEMORY_MODE", False, raising=False)

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(return_value=None)

    class _Ctx:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    request = MagicMock()
    request.app.state.db_engine.connect = MagicMock(return_value=_Ctx())
    assert await health_module._database_ready(request) is True
    fake_conn.execute.assert_awaited()


@pytest.mark.asyncio
async def test_health_reports_database_memory_under_memory_mode(
    client: AsyncClient, memory_mode, monkeypatch
) -> None:
    # Force the uptime grace check to pass.
    monkeypatch.setattr(
        health_module,
        "PROCESS_START_TIME",
        health_module.PROCESS_START_TIME.replace(year=2020),
    )
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "memory"


@pytest.mark.asyncio
async def test_readiness_ready_when_redis_up_in_memory_mode(
    client: AsyncClient, memory_mode, monkeypatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "PROCESS_START_TIME",
        health_module.PROCESS_START_TIME.replace(year=2020),
    )
    monkeypatch.setattr(health_module, "_redis_ready", AsyncMock(return_value=True))
    r = await client.get("/readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["database"] == "memory"


@pytest.mark.asyncio
async def test_readiness_degraded_when_redis_down_in_memory_mode(
    client: AsyncClient, memory_mode, monkeypatch
) -> None:
    monkeypatch.setattr(
        health_module,
        "PROCESS_START_TIME",
        health_module.PROCESS_START_TIME.replace(year=2020),
    )
    monkeypatch.setattr(health_module, "_redis_ready", AsyncMock(return_value=False))
    r = await client.get("/readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "disconnected"
