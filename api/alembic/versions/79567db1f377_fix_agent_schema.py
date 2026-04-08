"""Fix agent schema with shorter version name.

This is a duplicate of 20260407_fix_agent_runs_missing_cols.py but with
a shorter revision ID to avoid 32-character limit in alembic_version table.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '79567db1f377'
down_revision = '20260404_positions_snapshot_fix'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # agent_runs
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent'"
    )
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "run_type VARCHAR(32) NOT NULL DEFAULT 'analysis'"
    )
    op.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS execution_time_ms INTEGER")

    # ------------------------------------------------------------------
    # agent_logs
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'agent'"
    )

    # ------------------------------------------------------------------
    # agent_grades
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'grade_agent'"
    )
    # Fix NOT NULL constraints that block inserts when column is omitted
    op.execute("ALTER TABLE agent_grades ALTER COLUMN agent_id DROP NOT NULL")
    op.execute("ALTER TABLE agent_grades ALTER COLUMN agent_run_id DROP NOT NULL")

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS data JSONB")
    op.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS "
        "idempotency_key VARCHAR(255) NOT NULL DEFAULT ''"
    )
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS schema_version VARCHAR(32)")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT FALSE")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_idempotency_key "
        "ON events(idempotency_key)"
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # agent_runs
    # ------------------------------------------------------------------
    op.drop_index('ix_agent_runs_trace_id', table_name='agent_runs')
    op.drop_column('agent_runs', 'execution_time_ms')
    op.drop_column('agent_runs', 'run_type')
    op.drop_column('agent_runs', 'source')

    # ------------------------------------------------------------------
    # agent_logs
    # ------------------------------------------------------------------
    op.drop_column('agent_logs', 'source')

    # ------------------------------------------------------------------
    # agent_grades
    # ------------------------------------------------------------------
    op.drop_column('agent_grades', 'source')
    # Restore NOT NULL constraints (will fail if data exists)
    op.execute("ALTER TABLE agent_grades ALTER COLUMN agent_id SET NOT NULL")
    op.execute("ALTER TABLE agent_grades ALTER COLUMN agent_run_id SET NOT NULL")

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    op.drop_index('uq_events_idempotency_key', table_name='events')
    op.drop_column('events', 'processed')
    op.drop_column('events', 'schema_version')
    op.drop_column('events', 'idempotency_key')
    op.drop_column('events', 'data')
