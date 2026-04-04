from __future__ import annotations

import importlib


def test_upgrade_adds_schema_version_before_constraints(monkeypatch):
    migration = importlib.import_module("api.alembic.versions.upgrade_to_v3_schema")
    executed: list[str] = []
    created_indexes: list[str] = []

    class FakeInspector:
        def get_table_names(self):
            return ["agent_runs", "agent_logs", "agent_grades"]

        def get_columns(self, table_name):
            columns = {
                "agent_runs": [{"name": "trace_id"}],
                "agent_logs": [{"name": "trace_id"}],
                "agent_grades": [{"name": "trace_id"}],
            }
            return columns[table_name]

        def get_indexes(self, _table_name):
            return []

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: FakeInspector())
    monkeypatch.setattr(migration.op, "execute", lambda sql: executed.append(str(sql)))
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, *_args, **_kwargs: created_indexes.append(name),
    )

    migration.upgrade()

    assert any("ADD COLUMN schema_version" in sql and "agent_runs" in sql for sql in executed)
    assert any("ADD COLUMN schema_version" in sql and "agent_logs" in sql for sql in executed)
    assert any("ADD COLUMN schema_version" in sql and "agent_grades" in sql for sql in executed)
    assert "idx_agent_runs_trace_v3" in created_indexes
    assert "idx_agent_logs_trace_v3" in created_indexes


def test_upgrade_skips_missing_tables(monkeypatch):
    migration = importlib.import_module("api.alembic.versions.upgrade_to_v3_schema")
    executed: list[str] = []
    created_indexes: list[str] = []

    class FakeInspector:
        def get_table_names(self):
            return ["agent_runs"]

        def get_columns(self, table_name):
            return (
                [{"name": "schema_version"}, {"name": "trace_id"}]
                if table_name == "agent_runs"
                else []
            )

        def get_indexes(self, _table_name):
            return []

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: FakeInspector())
    monkeypatch.setattr(migration.op, "execute", lambda sql: executed.append(str(sql)))
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, *_args, **_kwargs: created_indexes.append(name),
    )

    migration.upgrade()

    assert any("ALTER TABLE agent_runs" in sql for sql in executed)
    assert all("agent_logs" not in sql for sql in executed)
    assert all("agent_grades" not in sql for sql in executed)
    assert created_indexes == ["idx_agent_runs_trace_v3"]
