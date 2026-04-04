from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def migration_module():
    return importlib.import_module(
        "api.alembic.versions.b2850e0a1b2_fix_uuid_defaults_and_missing_columns"
    )


def test_resolve_table_schema_detects_single_non_system_schema(monkeypatch, migration_module):
    captured = {}

    class FakeResult:
        def scalar(self):
            return "alt_schema"

    class FakeBind:
        def execute(self, _statement, params):
            captured.update(params)
            return FakeResult()

    monkeypatch.setattr(migration_module.op, "get_bind", lambda: FakeBind())

    schema = migration_module._resolve_table_schema("agent_runs")

    assert schema == "alt_schema"
    assert captured == {"table_name": "agent_runs"}


def test_resolve_table_schema_honors_schema_qualified_name(migration_module):
    assert migration_module._resolve_table_schema("audit.agent_runs") == "audit"


def test_has_column_and_index_honor_resolved_schema(monkeypatch, migration_module):
    class FakeBind:
        def execute(self, _statement, _params):
            return SimpleNamespace(scalar=lambda: "alt_schema")

    class FakeInspector:
        def get_columns(self, table_name, schema=None):
            assert table_name == "agent_runs"
            assert schema == "alt_schema"
            return [{"name": "trace_id"}]

        def get_indexes(self, table_name, schema=None):
            assert table_name == "agent_runs"
            assert schema == "alt_schema"
            return [{"name": "ix_agent_runs_trace_id"}]

    monkeypatch.setattr(migration_module.op, "get_bind", lambda: FakeBind())
    monkeypatch.setattr(migration_module.sa, "inspect", lambda _bind: FakeInspector())

    assert migration_module._has_column("agent_runs", "trace_id") is True
    assert migration_module._has_index("agent_runs", "ix_agent_runs_trace_id") is True


def test_upgrade_only_adds_missing_columns(monkeypatch, migration_module):
    added_columns = []
    created_indexes = []

    existing_columns = {
        "symbol",
        "trace_id",
    }
    existing_indexes = {"some_other_index"}

    monkeypatch.setattr(migration_module.op, "execute", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration_module.op, "alter_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration_module.op,
        "add_column",
        lambda _table, column, schema=None: added_columns.append((column.name, schema)),
    )
    monkeypatch.setattr(
        migration_module.op,
        "create_index",
        lambda index_name, _table, _cols, schema=None: created_indexes.append((index_name, schema)),
    )
    monkeypatch.setattr(migration_module, "_resolve_table_schema", lambda _table: "alt_schema")
    monkeypatch.setattr(
        migration_module,
        "_has_column",
        lambda _table, col, schema=None: col in existing_columns,
    )
    monkeypatch.setattr(
        migration_module,
        "_has_index",
        lambda _table, idx, schema=None: idx in existing_indexes,
    )

    migration_module.upgrade()

    added_column_names = [column_name for column_name, _schema in added_columns]
    assert "symbol" not in added_column_names
    assert "trace_id" not in added_column_names
    assert set(["signal_data", "action", "confidence", "primary_edge", "risk_factors"]).issubset(set(added_column_names))
    assert set([schema for _, schema in added_columns]) == {"alt_schema"}
    assert created_indexes == [("ix_agent_runs_trace_id", "alt_schema")]


def test_downgrade_only_drops_existing_columns_and_index(monkeypatch, migration_module):
    dropped_columns = []
    dropped_indexes = []

    existing_columns = {"symbol", "trace_id", "fallback"}
    existing_indexes = {"ix_agent_runs_trace_id"}

    monkeypatch.setattr(
        migration_module.op,
        "drop_column",
        lambda _table, name, schema=None: dropped_columns.append((name, schema)),
    )
    monkeypatch.setattr(
        migration_module.op,
        "drop_index",
        lambda index_name, table_name=None, schema=None: dropped_indexes.append((index_name, table_name, schema)),
    )
    monkeypatch.setattr(migration_module.op, "alter_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration_module, "_resolve_table_schema", lambda _table: "alt_schema")
    monkeypatch.setattr(
        migration_module,
        "_has_column",
        lambda _table, col, schema=None: col in existing_columns,
    )
    monkeypatch.setattr(
        migration_module,
        "_has_index",
        lambda _table, idx, schema=None: idx in existing_indexes,
    )

    migration_module.downgrade()

    assert dropped_columns == [("symbol", "alt_schema"), ("trace_id", "alt_schema"), ("fallback", "alt_schema")]
    assert dropped_indexes == [("ix_agent_runs_trace_id", "agent_runs", "alt_schema")]
