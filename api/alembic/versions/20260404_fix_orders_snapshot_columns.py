"""Patch orders table columns for runtime snapshot compatibility.

Revision ID: 20260404_orders_snapshot_fix
Revises: 20260403_v2_bootstrap
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260404_orders_snapshot_fix"
down_revision: str | Sequence[str] | None = "20260403_v2_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(32)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity NUMERIC(20, 8)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS filled_quantity NUMERIC(20, 8)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS filled_price NUMERIC(20, 8)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS exchange VARCHAR(64)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS commission NUMERIC(20, 8)")
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_metadata JSONB DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS schema_version VARCHAR(16) DEFAULT 'v2'"
    )
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(64)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")

    # Backfill quantity from legacy qty where possible.
    op.execute("UPDATE orders SET quantity = qty WHERE quantity IS NULL AND qty IS NOT NULL")


def downgrade() -> None:
    # Intentionally no-op: columns are additive runtime compatibility shims.
    pass
