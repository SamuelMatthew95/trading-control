from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError


@pytest.fixture
def migration_module():
    return importlib.import_module("api.alembic.versions.0001_initial")


def test_table_id_type_prefers_reflection_over_catalog_mapping(monkeypatch, migration_module):
    class FakeResult:
        def fetchall(self):
            return [SimpleNamespace(nspname="legacy", id_type="text")]

    class FakeBind:
        def execute(self, statement, params):
            assert "CAST(:schema_name AS text)" not in str(statement)
            assert ":schema_name" not in str(statement)
            assert params == {"relation_name": "orders"}
            return FakeResult()

    class FakeInspector:
        def get_columns(self, relation_name, schema=None):
            assert relation_name == "orders"
            assert schema == "legacy"
            return [{"name": "id", "type": sa.String(length=64)}]

    monkeypatch.setattr(migration_module.op, "get_bind", lambda: FakeBind())
    monkeypatch.setattr(migration_module.sa, "inspect", lambda _bind: FakeInspector())

    detected = migration_module._table_id_type("orders")

    assert isinstance(detected, sa.String)
    assert detected.length == 64


def test_table_id_type_uses_catalog_fallback_when_reflection_fails(monkeypatch, migration_module):
    class FakeResult:
        def fetchall(self):
            return [SimpleNamespace(nspname="public", id_type="bigint")]

    class FakeBind:
        def execute(self, statement, params):
            assert "CAST(:schema_name AS text)" not in str(statement)
            assert ":schema_name" not in str(statement)
            assert params == {"relation_name": "orders"}
            return FakeResult()

    class FakeInspector:
        def get_columns(self, *_args, **_kwargs):
            raise SQLAlchemyError("reflection failed")

    monkeypatch.setattr(migration_module.op, "get_bind", lambda: FakeBind())
    monkeypatch.setattr(migration_module.sa, "inspect", lambda _bind: FakeInspector())

    detected = migration_module._table_id_type("orders")

    assert isinstance(detected, sa.BigInteger)


def test_table_id_type_honors_schema_qualified_name(monkeypatch, migration_module):
    captured = {}

    class FakeResult:
        def fetchall(self):
            return []

    class FakeBind:
        def execute(self, statement, params):
            assert "n.nspname = :schema_name" in str(statement)
            captured.update(params)
            return FakeResult()

    class FakeInspector:
        def get_columns(self, *_args, **_kwargs):
            raise NoSuchTableError("missing")

    monkeypatch.setattr(migration_module.op, "get_bind", lambda: FakeBind())
    monkeypatch.setattr(migration_module.sa, "inspect", lambda _bind: FakeInspector())

    detected = migration_module._table_id_type("alt_schema.orders")

    assert captured == {"relation_name": "orders", "schema_name": "alt_schema"}
    assert isinstance(detected, migration_module.postgresql.UUID)
