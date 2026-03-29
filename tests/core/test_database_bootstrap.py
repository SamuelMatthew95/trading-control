from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_init_database_uses_alembic_for_postgres(monkeypatch):
    import api.database as database_module

    calls = []

    async def fake_to_thread(func, url):
        calls.append((func, url))
        return

    monkeypatch.setattr(database_module, "database_url", "postgresql+asyncpg://db/test")
    monkeypatch.setattr(database_module.asyncio, "to_thread", fake_to_thread)

    await database_module.init_database()

    assert calls == [(database_module._run_alembic_upgrade, "postgresql+asyncpg://db/test")]


@pytest.mark.asyncio
async def test_init_database_uses_metadata_create_all_for_sqlite(monkeypatch):
    import api.database as database_module

    class FakeConn:
        def __init__(self):
            self.run_sync_calls = []

        async def run_sync(self, fn):
            self.run_sync_calls.append(fn)

    class FakeBegin:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_conn = FakeConn()

    class FakeEngine:
        def begin(self):
            return FakeBegin(fake_conn)

    monkeypatch.setattr(database_module, "database_url", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(database_module, "async_engine", FakeEngine())

    await database_module.init_database()

    assert fake_conn.run_sync_calls == [database_module.Base.metadata.create_all]


def test_resolve_database_url_requires_database_in_production(monkeypatch):
    import api.database as database_module

    monkeypatch.setattr(
        database_module,
        "get_database_url",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("NODE_ENV", "production")

    with pytest.raises(RuntimeError, match="DATABASE_URL is required in production"):
        database_module._resolve_database_url()
