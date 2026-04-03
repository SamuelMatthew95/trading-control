from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_init_database_uses_alembic_for_postgres(monkeypatch):
    import api.database as database_module

    calls = []

    async def fake_upgrade_with_lock(url):
        calls.append(url)
        return

    monkeypatch.setattr(database_module, "database_url", "postgresql+asyncpg://db/test")
    monkeypatch.setattr(database_module, "_run_alembic_upgrade_with_lock", fake_upgrade_with_lock)

    await database_module.init_database()

    assert calls == ["postgresql+asyncpg://db/test"]


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


@pytest.mark.asyncio
async def test_run_alembic_upgrade_with_lock_uses_advisory_lock(monkeypatch):
    import api.database as database_module

    statements = []
    to_thread_calls = []
    execution_options_calls = []

    class FakeConn:
        async def execution_options(self, **kwargs):
            execution_options_calls.append(kwargs)
            return self

        async def execute(self, statement, params):
            statements.append((str(statement), params))

    class FakeConnect:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConnect()

    async def fake_to_thread(func, url):
        to_thread_calls.append((func, url))

    async def fake_bootstrap(*_args, **_kwargs):
        return None

    monkeypatch.setattr(database_module, "async_engine", FakeEngine())
    monkeypatch.setattr(database_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(database_module, "_bootstrap_existing_schema_revision", fake_bootstrap)

    await database_module._run_alembic_upgrade_with_lock("postgresql+asyncpg://db/test")

    assert statements == [
        ("SELECT pg_advisory_lock(:lock_id)", {"lock_id": database_module.ALEMBIC_STARTUP_LOCK_ID}),
        (
            "SELECT pg_advisory_unlock(:lock_id)",
            {"lock_id": database_module.ALEMBIC_STARTUP_LOCK_ID},
        ),
    ]
    assert execution_options_calls == [{"isolation_level": "AUTOCOMMIT"}]
    assert to_thread_calls == [
        (database_module._run_alembic_upgrade, "postgresql+asyncpg://db/test")
    ]


@pytest.mark.asyncio
async def test_bootstrap_existing_schema_revision_stamps_initial_revision(monkeypatch):
    import api.database as database_module

    to_thread_calls = []

    class FakeConn:
        async def scalar(self, statement, params=None):
            sql = str(statement)
            if "to_regclass" in sql:
                return None
            return 2

    async def fake_to_thread(func, *args):
        to_thread_calls.append((func, *args))

    monkeypatch.setattr(database_module.asyncio, "to_thread", fake_to_thread)

    await database_module._bootstrap_existing_schema_revision(
        FakeConn(), "postgresql+asyncpg://db/test"
    )

    assert to_thread_calls == [
        (
            database_module._run_alembic_stamp,
            "postgresql+asyncpg://db/test",
            database_module.INITIAL_REVISION,
        )
    ]


@pytest.mark.asyncio
async def test_bootstrap_existing_schema_revision_skips_when_version_table_exists(monkeypatch):
    import api.database as database_module

    to_thread_calls = []

    class FakeConn:
        async def scalar(self, statement, params=None):
            sql = str(statement)
            if "to_regclass" in sql:
                return "alembic_version"
            return 0

    async def fake_to_thread(func, *args):
        to_thread_calls.append((func, *args))

    monkeypatch.setattr(database_module.asyncio, "to_thread", fake_to_thread)

    await database_module._bootstrap_existing_schema_revision(
        FakeConn(), "postgresql+asyncpg://db/test"
    )

    assert to_thread_calls == []
