"""Fix schema drift across agent_runs, agent_logs, agent_grades, and events.

Root cause: 20260403_v2_bootstrap used CREATE TABLE IF NOT EXISTS for all
tables. When tables pre-existed, that was a no-op. The ALTER TABLE fallback
path in that migration was incomplete — it omitted several columns that the
application code expects. This migration closes all known gaps found by
comparing the live production schema against every INSERT in the codebase.

Changes per table
-----------------
agent_runs:
  - source (VARCHAR 64, NOT NULL DEFAULT 'reasoning_agent') — writer identity
  - run_type (VARCHAR 32, NOT NULL DEFAULT 'analysis') — required by ORM
  - execution_time_ms (INTEGER, nullable) — written by success UPDATE

agent_logs:
  - source (VARCHAR 64, NOT NULL DEFAULT 'agent') — writer identity

agent_grades:
  - source (VARCHAR 64, NOT NULL DEFAULT 'grade_agent') — writer identity
  - agent_id: DROP NOT NULL — pre-migration schema created it NOT NULL;
    write_grade_to_db omits it (acceptable NULL), and signal_generator
    passes agent_pool_id which may be NULL when no pool row exists
  - agent_run_id: DROP NOT NULL — same reason

events:
  - data (JSONB, DEFAULT '{}') — signal payload stored here
  - idempotency_key (VARCHAR 255, nullable) — used for ON CONFLICT dedup
  - processed (BOOLEAN, NOT NULL DEFAULT false) — event processing flag
  - schema_version (VARCHAR 16, DEFAULT 'v3') — v3 audit field
  - UNIQUE index on idempotency_key (required for ON CONFLICT clause)

Revision ID: 20260407_fix_agent_runs_missing_cols
Revises: 20260404_positions_snapshot_fix
Create Date: 2026-04-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260407_fix_agent_runs_missing_cols"
down_revision: str | Sequence[str] | None = "20260404_positions_snapshot_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    # Pre-migration schema created these as NOT NULL with no default.
    # write_grade_to_db omits them entirely (NULL is correct semantics
    # when no pool/run context is available).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='agent_grades' AND column_name='agent_id'
                  AND is_nullable='NO'
            ) THEN
                ALTER TABLE agent_grades ALTER COLUMN agent_id DROP NOT NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='agent_grades' AND column_name='agent_run_id'
                  AND is_nullable='NO'
            ) THEN
                ALTER TABLE agent_grades ALTER COLUMN agent_run_id DROP NOT NULL;
            END IF;
        END $$
        """
    )

    # ------------------------------------------------------------------
    # events — columns used by signal_generator INSERT are absent
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)")
    op.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS schema_version VARCHAR(16) DEFAULT 'v3'"
    )
    # Required for ON CONFLICT (idempotency_key) DO NOTHING
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS events_idempotency_key_idx "
        "ON events (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    # No destructive downgrade — additive changes are safe to keep.
    pass
