"""Upgrade to V3 Schema

Revision ID: upgrade_to_v3
Revises: (latest v2 migration)
Create Date: 2026-03-25 13:39:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "upgrade_to_v3"
down_revision: str | None = "b2850e0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _ensure_schema_version_column(table_name: str) -> None:
    if not _has_table(table_name):
        return
    if not _has_column(table_name, "schema_version"):
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                "ADD COLUMN schema_version VARCHAR(16) NOT NULL DEFAULT 'v3'"
            )
        )


def upgrade() -> None:
    """Upgrade database schema to V3."""
    for table_name in ("agent_runs", "agent_logs", "agent_grades"):
        _ensure_schema_version_column(table_name)

    # Update agent_runs table
    if _has_table("agent_runs"):
        op.execute("""
        ALTER TABLE agent_runs
        DROP CONSTRAINT IF EXISTS check_agent_runs_schema_v2,
        DROP CONSTRAINT IF EXISTS check_agent_runs_schema_v3,
        ADD CONSTRAINT check_agent_runs_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Update agent_logs table
    if _has_table("agent_logs"):
        op.execute("""
        ALTER TABLE agent_logs
        DROP CONSTRAINT IF EXISTS check_agent_logs_schema_v2,
        DROP CONSTRAINT IF EXISTS check_agent_logs_schema_v3,
        ADD CONSTRAINT check_agent_logs_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Update agent_grades table
    if _has_table("agent_grades"):
        op.execute("""
        ALTER TABLE agent_grades
        DROP CONSTRAINT IF EXISTS check_agent_grades_schema_v2,
        DROP CONSTRAINT IF EXISTS check_agent_grades_schema_v3,
        ADD CONSTRAINT check_agent_grades_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Add trace_id NOT NULL constraint for v3 (optional - can be added gradually)
    # op.execute("""
    #     ALTER TABLE agent_runs ALTER COLUMN trace_id SET NOT NULL
    # """)

    # Create indexes for better traceability
    if (
        _has_table("agent_runs")
        and _has_column("agent_runs", "trace_id")
        and not _has_index("agent_runs", "idx_agent_runs_trace_v3")
    ):
        op.create_index("idx_agent_runs_trace_v3", "agent_runs", ["trace_id"], unique=False)
    if (
        _has_table("agent_logs")
        and _has_column("agent_logs", "trace_id")
        and not _has_index("agent_logs", "idx_agent_logs_trace_v3")
    ):
        op.create_index("idx_agent_logs_trace_v3", "agent_logs", ["trace_id"], unique=False)

    # Add comment about v3 schema
    if _has_table("agent_runs"):
        op.execute("""
        COMMENT ON TABLE agent_runs IS 'V3: Agent runs with traceability and strict schema validation'
    """)
    if _has_table("agent_logs"):
        op.execute("""
        COMMENT ON TABLE agent_logs IS 'V3: Agent logs with traceability and strict schema validation'
    """)
    if _has_table("agent_grades"):
        op.execute("""
        COMMENT ON TABLE agent_grades IS 'V3: Agent grades with traceability and strict schema validation'
    """)


def downgrade() -> None:
    """Downgrade database schema from V3 to V2."""

    # Remove v3 constraints
    if _has_table("agent_runs"):
        op.execute("""
        ALTER TABLE agent_runs
        DROP CONSTRAINT IF EXISTS check_agent_runs_schema_v3,
        ADD CONSTRAINT check_agent_runs_schema_v2 CHECK (schema_version = 'v2')
    """)

    if _has_table("agent_logs"):
        op.execute("""
        ALTER TABLE agent_logs
        DROP CONSTRAINT IF EXISTS check_agent_logs_schema_v3,
        ADD CONSTRAINT check_agent_logs_schema_v2 CHECK (schema_version = 'v2')
    """)

    if _has_table("agent_grades"):
        op.execute("""
        ALTER TABLE agent_grades
        DROP CONSTRAINT IF EXISTS check_agent_grades_schema_v3,
        ADD CONSTRAINT check_agent_grades_schema_v2 CHECK (schema_version = 'v2')
    """)

    # Drop v3 indexes
    if _has_table("agent_runs") and _has_index("agent_runs", "idx_agent_runs_trace_v3"):
        op.drop_index("idx_agent_runs_trace_v3", table_name="agent_runs")
    if _has_table("agent_logs") and _has_index("agent_logs", "idx_agent_logs_trace_v3"):
        op.drop_index("idx_agent_logs_trace_v3", table_name="agent_logs")

    # Update comments
    if _has_table("agent_runs"):
        op.execute("""
        COMMENT ON TABLE agent_runs IS 'Agent runs with schema validation'
    """)
    if _has_table("agent_logs"):
        op.execute("""
        COMMENT ON TABLE agent_logs IS 'Agent logs with schema validation'
    """)
    if _has_table("agent_grades"):
        op.execute("""
        COMMENT ON TABLE agent_grades IS 'Agent grades with schema validation'
    """)
