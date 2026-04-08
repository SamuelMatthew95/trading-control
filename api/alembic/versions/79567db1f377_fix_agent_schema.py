"""Minimal migration to satisfy alembic lookup."""

revision = "79567db1f377"
down_revision = "20260404_positions_snapshot_fix"


def upgrade() -> None:
    # No-op - schema already has source columns from manual fix
    pass


def downgrade() -> None:
    pass
