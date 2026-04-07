"""Add missing source/schema_version/run_type columns to agent_runs.

These were included in the CREATE TABLE IF NOT EXISTS statement in
20260403_v2_bootstrap but not in the ALTER TABLE fallback path, so
databases upgraded from the original 0001_initial schema are missing them.

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
    # source: who wrote the row (e.g. 'SIGNAL_AGENT', 'reasoning_agent')
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent'"
    )
    # schema_version: enforces v3 writes
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "schema_version VARCHAR(16) NOT NULL DEFAULT 'v3'"
    )
    # run_type: required by ORM model
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "run_type VARCHAR(32) NOT NULL DEFAULT 'analysis'"
    )


def downgrade() -> None:
    # No destructive downgrade — columns with NOT NULL defaults are safe to keep.
    pass
