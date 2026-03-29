"""Upgrade to V3 Schema

Revision ID: upgrade_to_v3
Revises: (latest v2 migration)
Create Date: 2026-03-25 13:39:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "upgrade_to_v3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema to V3."""

    # Update agent_runs table
    op.execute("""
        ALTER TABLE agent_runs
        DROP CONSTRAINT IF EXISTS check_agent_runs_schema_v2,
        ADD CONSTRAINT check_agent_runs_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Update agent_logs table
    op.execute("""
        ALTER TABLE agent_logs
        DROP CONSTRAINT IF EXISTS check_agent_logs_schema_v2,
        ADD CONSTRAINT check_agent_logs_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Update agent_grades table
    op.execute("""
        ALTER TABLE agent_grades
        DROP CONSTRAINT IF EXISTS check_agent_grades_schema_v2,
        ADD CONSTRAINT check_agent_grades_schema_v3 CHECK (schema_version = 'v3')
    """)

    # Add trace_id NOT NULL constraint for v3 (optional - can be added gradually)
    # op.execute("""
    #     ALTER TABLE agent_runs ALTER COLUMN trace_id SET NOT NULL
    # """)

    # Create indexes for better traceability
    op.create_index("idx_agent_runs_trace_v3", "agent_runs", ["trace_id"], unique=False)
    op.create_index("idx_agent_logs_trace_v3", "agent_logs", ["trace_id"], unique=False)

    # Add comment about v3 schema
    op.execute("""
        COMMENT ON TABLE agent_runs IS 'V3: Agent runs with traceability and strict schema validation'
    """)
    op.execute("""
        COMMENT ON TABLE agent_logs IS 'V3: Agent logs with traceability and strict schema validation'
    """)
    op.execute("""
        COMMENT ON TABLE agent_grades IS 'V3: Agent grades with traceability and strict schema validation'
    """)


def downgrade() -> None:
    """Downgrade database schema from V3 to V2."""

    # Remove v3 constraints
    op.execute("""
        ALTER TABLE agent_runs
        DROP CONSTRAINT IF EXISTS check_agent_runs_schema_v3,
        ADD CONSTRAINT check_agent_runs_schema_v2 CHECK (schema_version = 'v2')
    """)

    op.execute("""
        ALTER TABLE agent_logs
        DROP CONSTRAINT IF EXISTS check_agent_logs_schema_v3,
        ADD CONSTRAINT check_agent_logs_schema_v2 CHECK (schema_version = 'v2')
    """)

    op.execute("""
        ALTER TABLE agent_grades
        DROP CONSTRAINT IF EXISTS check_agent_grades_schema_v3,
        ADD CONSTRAINT check_agent_grades_schema_v2 CHECK (schema_version = 'v2')
    """)

    # Drop v3 indexes
    op.drop_index("idx_agent_runs_trace_v3", table_name="agent_runs")
    op.drop_index("idx_agent_logs_trace_v3", table_name="agent_logs")

    # Update comments
    op.execute("""
        COMMENT ON TABLE agent_runs IS 'Agent runs with schema validation'
    """)
    op.execute("""
        COMMENT ON TABLE agent_logs IS 'Agent logs with schema validation'
    """)
    op.execute("""
        COMMENT ON TABLE agent_grades IS 'Agent grades with schema validation'
    """)
