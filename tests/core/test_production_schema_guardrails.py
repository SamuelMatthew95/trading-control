"""Production schema guardrail tests.

These tests catch the class of bug we debugged: schema drift between
application code and the live PostgreSQL database.

The live production DB was created before the Alembic migration system was
introduced. Several tables have integer PKs (not UUID), missing columns, and
NOT NULL constraints that conflict with what the ORM models assume.

Every test here is a pure source-code inspection — no database, no network,
no async — so they run in milliseconds and are always green on a clean branch.

Tables with INTEGER primary keys (not UUID):
  - agent_runs  (id INTEGER, nextval sequence)
  - events      (id INTEGER, nextval sequence)

This means any INSERT that passes a UUID for `id` will fail at runtime.
The fix: omit `id` from column list, use RETURNING id, store as db_run_id.
"""

from __future__ import annotations

import pathlib
import re

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).parent.parent.parent  # repo root


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text()


def _sql_block_after(source: str, keyword: str) -> str:
    """Return the text from `keyword` to the next INSERT / UPDATE / end."""
    idx = source.find(keyword)
    if idx == -1:
        return ""
    snippet = source[idx:]
    # Cut at the next top-level statement keyword
    for stop in ["INSERT INTO", "UPDATE ", "SELECT ", "DELETE "]:
        next_kw = snippet.find(stop, len(keyword))
        if next_kw != -1:
            snippet = snippet[:next_kw]
    return snippet


# ---------------------------------------------------------------------------
# agent_runs INSERT guardrails
# ---------------------------------------------------------------------------


class TestAgentRunsInsert:
    """Guardrails for every INSERT INTO agent_runs in the codebase."""

    def _signal_gen(self) -> str:
        return _read("api/services/signal_generator.py")

    def test_no_id_column_in_insert(self):
        """agent_runs.id is an INTEGER sequence — never pass a UUID for it.

        The column list must NOT contain `id,` before RETURNING id.
        """
        src = self._signal_gen()
        # Extract text between INSERT INTO agent_runs and RETURNING
        match = re.search(
            r"INSERT INTO agent_runs\s*\((.+?)\)\s*VALUES",
            src,
            re.DOTALL,
        )
        assert match, "No INSERT INTO agent_runs found"
        col_list = match.group(1)
        # 'id' must not appear as a standalone column name in the list
        col_names = [c.strip() for c in col_list.split(",")]
        assert "id" not in col_names, (
            f"'id' must NOT be in agent_runs INSERT column list (integer PK, "
            f"never pass UUID). Found columns: {col_names}"
        )

    def test_returning_id_present(self):
        """RETURNING id must follow the INSERT so db_run_id gets the integer PK."""
        src = self._signal_gen()
        assert "RETURNING id" in src, (
            "INSERT INTO agent_runs must have RETURNING id to capture the "
            "integer primary key for subsequent UPDATEs"
        )

    def test_source_column_in_insert(self):
        """source column must be in the agent_runs INSERT (added by migration)."""
        src = self._signal_gen()
        block = _sql_block_after(src, "INSERT INTO agent_runs")
        assert "source" in block, (
            "INSERT INTO agent_runs must include 'source' column. "
            "Column was added by 20260407_fix_agent_runs_missing_cols migration."
        )

    def test_schema_version_in_insert(self):
        """schema_version must be in the agent_runs INSERT."""
        src = self._signal_gen()
        block = _sql_block_after(src, "INSERT INTO agent_runs")
        assert "schema_version" in block, (
            "INSERT INTO agent_runs must include 'schema_version' (= 'v3')"
        )

    def test_db_run_id_used_in_update(self):
        """UPDATE agent_runs WHERE id=:id must use db_run_id, not the UUID run_id."""
        src = self._signal_gen()
        # Find all UPDATE agent_runs blocks
        update_indices = [m.start() for m in re.finditer(r"UPDATE agent_runs", src)]
        assert update_indices, "No UPDATE agent_runs found"

        for idx in update_indices:
            snippet = src[idx : idx + 300]
            if "WHERE id=:id" in snippet or "WHERE id = :id" in snippet:
                # The param dict near this update must use db_run_id, not run_id
                param_region = src[idx : idx + 500]
                assert '"id": db_run_id' in param_region or "'id': db_run_id" in param_region, (
                    f"UPDATE agent_runs at offset {idx} must use db_run_id (integer), "
                    f"not run_id (UUID). Snippet:\n{snippet}"
                )

    def test_run_id_uuid_not_used_as_id_param(self):
        """Ensure 'id': run_id is not passed to any agent_runs statement.

        run_id is a UUID string; agent_runs.id is an integer. Passing the UUID
        directly would cause a type error in PostgreSQL.
        """
        src = self._signal_gen()
        # Look for the old bad pattern
        bad_patterns = ['"id": run_id', "'id': run_id"]
        for pat in bad_patterns:
            assert pat not in src, (
                f"Found '{pat}' in signal_generator.py. "
                "agent_runs.id is INTEGER — use db_run_id (from RETURNING id), "
                "not the UUID run_id."
            )


# ---------------------------------------------------------------------------
# events INSERT guardrails
# ---------------------------------------------------------------------------


class TestEventsInsert:
    """Guardrails for INSERT INTO events in signal_generator.py."""

    def _signal_gen(self) -> str:
        return _read("api/services/signal_generator.py")

    def test_data_column_present(self):
        """events.data (JSONB) must be in the INSERT — added by migration."""
        src = self._signal_gen()
        block = _sql_block_after(src, "INSERT INTO events")
        assert "data" in block, (
            "INSERT INTO events must include 'data' column. "
            "Column was missing from live DB and added by 20260407 migration."
        )

    def test_idempotency_key_present(self):
        """events.idempotency_key must be in the INSERT for ON CONFLICT to work."""
        src = self._signal_gen()
        block = _sql_block_after(src, "INSERT INTO events")
        assert "idempotency_key" in block, (
            "INSERT INTO events must include 'idempotency_key'. "
            "Required for ON CONFLICT (idempotency_key) DO NOTHING dedup."
        )

    def test_schema_version_present(self):
        """events.schema_version must be in the INSERT."""
        src = self._signal_gen()
        block = _sql_block_after(src, "INSERT INTO events")
        assert "schema_version" in block, "INSERT INTO events must include 'schema_version'."

    def test_on_conflict_clause_present(self):
        """ON CONFLICT (idempotency_key) DO NOTHING must be present for dedup."""
        src = self._signal_gen()
        assert "ON CONFLICT (idempotency_key)" in src, (
            "INSERT INTO events must have ON CONFLICT (idempotency_key) DO NOTHING "
            "to prevent duplicate signal events."
        )


# ---------------------------------------------------------------------------
# agent_grades INSERT guardrails
# ---------------------------------------------------------------------------


class TestAgentGradesInsert:
    """Guardrails for INSERT INTO agent_grades."""

    def test_source_in_signal_generator(self):
        """agent_grades INSERT in signal_generator.py must include source."""
        src = _read("api/services/signal_generator.py")
        block = _sql_block_after(src, "INSERT INTO agent_grades")
        assert "source" in block, (
            "INSERT INTO agent_grades must include 'source' column. "
            "Added by 79567db1f377_fix_agent_schema migration."
        )

    def test_source_in_db_helpers(self):
        """write_grade_to_db in db_helpers.py must include source."""
        src = _read("api/services/agents/db_helpers.py")
        block = _sql_block_after(src, "INSERT INTO agent_grades")
        assert "source" in block, "write_grade_to_db INSERT must include 'source' column."

    def test_migration_drops_agent_id_not_null(self):
        """Migration must DROP NOT NULL on agent_grades.agent_id.

        Pre-migration schema created agent_id as NOT NULL with no default.
        write_grade_to_db omits agent_id entirely (NULL is valid).
        The migration must relax this constraint.
        """
        migration = _read("api/alembic/versions/20260407_fix_agent_runs_missing_cols.py")
        assert "agent_id" in migration and "DROP NOT NULL" in migration, (
            "Migration must DROP NOT NULL on agent_grades.agent_id. "
            "write_grade_to_db omits this column — NOT NULL would cause "
            "every grade write to fail."
        )

    def test_migration_drops_agent_run_id_not_null(self):
        """Migration must DROP NOT NULL on agent_grades.agent_run_id."""
        migration = _read("api/alembic/versions/20260407_fix_agent_runs_missing_cols.py")
        assert "agent_run_id" in migration and "DROP NOT NULL" in migration, (
            "Migration must DROP NOT NULL on agent_grades.agent_run_id."
        )


# ---------------------------------------------------------------------------
# agent_logs INSERT guardrails
# ---------------------------------------------------------------------------


class TestAgentLogsInsert:
    """Guardrails for INSERT INTO agent_logs across all write sites."""

    def _files(self) -> list[tuple[str, str]]:
        paths = [
            "api/services/signal_generator.py",
            "api/services/agents/db_helpers.py",
        ]
        return [(p, _read(p)) for p in paths]

    def test_source_column_in_all_inserts(self):
        """Every INSERT INTO agent_logs must include the source column."""
        for path, src in self._files():
            if "INSERT INTO agent_logs" not in src:
                continue
            block = _sql_block_after(src, "INSERT INTO agent_logs")
            assert "source" in block, (
                f"{path}: INSERT INTO agent_logs must include 'source' column. "
                "Added by 79567db1f377_fix_agent_schema migration."
            )

    def test_log_type_column_used(self):
        """agent_logs uses log_type (not log_level) — verify correct column name."""
        for path, src in self._files():
            if "INSERT INTO agent_logs" not in src:
                continue
            block = _sql_block_after(src, "INSERT INTO agent_logs")
            assert "log_type" in block, (
                f"{path}: INSERT INTO agent_logs must use 'log_type' column "
                "(not 'log_level'). Live DB has log_type VARCHAR(100)."
            )

    def test_payload_column_used(self):
        """agent_logs.payload is TEXT in live DB — verify INSERT uses payload."""
        for path, src in self._files():
            if "INSERT INTO agent_logs" not in src:
                continue
            block = _sql_block_after(src, "INSERT INTO agent_logs")
            assert "payload" in block, (
                f"{path}: INSERT INTO agent_logs must use 'payload' column (TEXT in live DB)."
            )


# ---------------------------------------------------------------------------
# Migration completeness guardrails
# ---------------------------------------------------------------------------


class TestMigrationCompleteness:
    """Verify the 20260407 migration contains all required ALTER TABLE statements."""

    def _migration(self) -> str:
        return _read("api/alembic/versions/20260407_fix_agent_runs_missing_cols.py")

    def test_agent_runs_source_added(self):
        src = self._migration()
        assert "agent_runs" in src and "source" in src, "Migration must ADD source to agent_runs"

    def test_agent_runs_execution_time_ms_added(self):
        src = self._migration()
        assert "execution_time_ms" in src, (
            "Migration must ADD execution_time_ms to agent_runs. "
            "UPDATE agent_runs SET execution_time_ms=:elapsed would otherwise fail."
        )

    def test_agent_logs_source_added(self):
        src = self._migration()
        assert "agent_logs" in src and "source" in src, "Migration must ADD source to agent_logs"

    def test_agent_grades_source_added(self):
        src = self._migration()
        assert "agent_grades" in src and "source" in src, (
            "Migration must ADD source to agent_grades"
        )

    def test_events_data_column_added(self):
        src = self._migration()
        assert "events" in src and "data" in src, "Migration must ADD data JSONB to events table"

    def test_events_idempotency_key_added(self):
        src = self._migration()
        assert "idempotency_key" in src, "Migration must ADD idempotency_key to events table"

    def test_events_unique_index_created(self):
        src = self._migration()
        assert "events_idempotency_key_idx" in src, (
            "Migration must CREATE UNIQUE INDEX on events.idempotency_key — "
            "required for ON CONFLICT (idempotency_key) DO NOTHING"
        )

    def test_events_processed_column_added(self):
        src = self._migration()
        assert "processed" in src, "Migration must ADD processed BOOLEAN to events table"

    def test_migration_chain_is_correct(self):
        """Migration must revise the current HEAD (20260404_positions_snapshot_fix)."""
        src = self._migration()
        assert "20260404_positions_snapshot_fix" in src, (
            "down_revision must be 20260404_positions_snapshot_fix (the previous HEAD)"
        )


# ---------------------------------------------------------------------------
# Cross-file consistency: all source files use constants, not literals
# ---------------------------------------------------------------------------


class TestConstantUsage:
    """Verify source files use DB_SCHEMA_VERSION constant, not hardcoded 'v3'."""

    def _write_files(self) -> list[tuple[str, str]]:
        paths = [
            "api/services/signal_generator.py",
            "api/services/agents/db_helpers.py",
        ]
        return [(p, _read(p)) for p in paths]

    def test_no_hardcoded_schema_version_in_inserts(self):
        """schema_version must use DB_SCHEMA_VERSION constant, not 'v3' literal."""
        bad = re.compile(r"""["']v3["']""")
        for path, src in self._write_files():
            # Allow the import line and comments
            code_lines = [
                ln
                for ln in src.splitlines()
                if not ln.strip().startswith("#") and "schema_version.py" not in ln
            ]
            code = "\n".join(code_lines)
            matches = bad.findall(code)
            assert not matches, (
                f"{path}: Found hardcoded 'v3' string literal. "
                "Use DB_SCHEMA_VERSION from api.schema_version instead."
            )
