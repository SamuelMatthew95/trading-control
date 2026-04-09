"""Fix missing columns in events and agent_logs tables.

Adds entity_id and entity_type columns to events table that signal_generator expects.
Also fixes agent_logs table to ensure source column exists and removes invalid UUID cast syntax.

Revision ID: 20260409_fix_events_and_agent_logs_columns
Revises: 20260409_merge_agent_schema_fixes
Create Date: 2026-04-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260409_fix_events_and_agent_logs_columns"
down_revision: str | Sequence[str] | None = "20260409_merge_agent_schema_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # events table - add missing entity_id and entity_type columns
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS entity_type VARCHAR(50)")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS entity_id VARCHAR(255)")
    
    # ------------------------------------------------------------------
    # agent_logs table - ensure source column exists (should already exist from previous migration)
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'agent'"
    )


def downgrade() -> None:
    # Remove the added columns
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS entity_type")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS entity_id")
    op.execute("ALTER TABLE agent_logs DROP COLUMN IF EXISTS source")
