"""Merge agent schema fixes.

This migration merges the two parallel heads:
- 20260407_fix_agent_runs_missing_cols
- 79567db1f377_fix_agent_schema

Both migrations address the same schema issues but one is a no-op
since the schema was already manually fixed.

Revision ID: 20260409_merge_agent_schema_fixes
Revises: 20260407_fix_agent_runs_missing_cols, 79567db1f377_fix_agent_schema
Create Date: 2026-04-09
"""

from collections.abc import Sequence

revision: str = "20260409_merge_agent_schema_fixes"
down_revision: str | Sequence[str] | None = ("20260407_fix_agent_runs_missing_cols", "79567db1f377")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Merge migration - no additional changes needed
    # Both parent migrations have already been applied or are no-ops
    pass


def downgrade() -> None:
    # To downgrade, we would need to apply the downgrades of both parents
    # However, since both are additive changes, we keep them
    pass
