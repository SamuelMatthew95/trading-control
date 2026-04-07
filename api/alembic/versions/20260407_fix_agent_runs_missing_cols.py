"""Add missing source column to agent_runs, agent_logs, and agent_grades.

The 20260403_v2_bootstrap migration added `source` inside CREATE TABLE IF NOT
EXISTS blocks for all three tables, but its ALTER TABLE fallback path (which
runs when the tables already exist) omitted `source` for all of them.

Databases upgraded from 0001_initial (agent_runs, agent_logs) or from a
pre-migration schema (agent_grades) are missing this column, causing every
INSERT that references it to fail with UndefinedColumnError.

Also adds run_type to agent_runs, which has the same gap.

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
    # agent_runs — source, run_type, execution_time_ms were in CREATE TABLE but not ALTER TABLE fallback
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent'"
    )
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
        "run_type VARCHAR(32) NOT NULL DEFAULT 'analysis'"
    )
    op.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS execution_time_ms INTEGER")

    # agent_logs — source was in CREATE TABLE but not ALTER TABLE fallback
    op.execute(
        "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'agent'"
    )

    # agent_grades — source was in CREATE TABLE but not ALTER TABLE fallback
    # (agent_grades may pre-date the migration system entirely)
    op.execute(
        "ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS "
        "source VARCHAR(64) NOT NULL DEFAULT 'grade_agent'"
    )


def downgrade() -> None:
    # No destructive downgrade — columns with NOT NULL defaults are safe to keep.
    pass
