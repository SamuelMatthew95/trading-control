"""Patch positions table columns for runtime snapshot compatibility.

Revision ID: 20260404_positions_snapshot_fix
Revises: 20260404_orders_snapshot_fix
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260404_positions_snapshot_fix"
down_revision: str | Sequence[str] | None = "20260404_orders_snapshot_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS quantity NUMERIC(20, 8)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS avg_cost NUMERIC(20, 8)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS market_value NUMERIC(20, 8)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC(20, 8)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS last_price NUMERIC(20, 8)")
    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS position_metadata JSONB DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS schema_version VARCHAR(16) DEFAULT 'v2'"
    )
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS source VARCHAR(64)")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")

    # Backfill v2 columns from legacy v1 column names where available.
    op.execute("UPDATE positions SET quantity = qty WHERE quantity IS NULL AND qty IS NOT NULL")
    op.execute(
        "UPDATE positions SET avg_cost = entry_price WHERE avg_cost IS NULL AND entry_price IS NOT NULL"
    )
    op.execute(
        "UPDATE positions SET last_price = current_price "
        "WHERE last_price IS NULL AND current_price IS NOT NULL"
    )
    op.execute(
        "UPDATE positions SET market_value = quantity * last_price "
        "WHERE market_value IS NULL AND quantity IS NOT NULL AND last_price IS NOT NULL"
    )
    op.execute(
        "UPDATE positions SET unrealized_pnl = unrealised_pnl "
        "WHERE unrealized_pnl IS NULL AND unrealised_pnl IS NOT NULL"
    )


def downgrade() -> None:
    # Intentionally no-op: columns are additive runtime compatibility shims.
    pass
