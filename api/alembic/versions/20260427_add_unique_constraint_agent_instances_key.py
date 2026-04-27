"""Add UNIQUE constraint on agent_instances.instance_key

Revision ID: 20260427_agent_instances_unique_key
Revises: 20260409_merge_agent_schema_fixes
Create Date: 2026-04-27

The original add_trade_lifecycle_agent_instances migration created only a
regular (non-unique) index on agent_instances.instance_key.  The
register_agent_instance() helper uses ON CONFLICT (instance_key) which
requires a UNIQUE constraint; without it every INSERT that would conflict
raises a PostgreSQL error instead of upserting, leaving the agent without
a persisted lifecycle record.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260427_agent_instances_unique_key"
down_revision: str | None = "20260409_merge_agent_schema_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the existing non-unique index, then create a unique one.
    # Using IF EXISTS / IF NOT EXISTS so the migration is re-runnable.
    op.execute("DROP INDEX IF EXISTS idx_agent_instances_key")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_instances_key ON agent_instances(instance_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_instances_key")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_instances_key ON agent_instances(instance_key)"
    )
