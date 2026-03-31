"""Add prices_snapshot table for price poller persistence.

Revision ID: add_prices_snapshot
Revises: upgrade_to_v3
"""

from __future__ import annotations

from alembic import op

revision: str = "add_prices_snapshot"
down_revision: str | None = "upgrade_to_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS prices_snapshot (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol      TEXT NOT NULL,
            price       NUMERIC(20, 8) NOT NULL,
            change      NUMERIC(20, 8),
            change_pct  NUMERIC(10, 6),
            source      TEXT NOT NULL DEFAULT 'price_poller',
            trace_id    UUID,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_prices_snapshot_symbol_recorded_at
        ON prices_snapshot (symbol, recorded_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prices_snapshot")
