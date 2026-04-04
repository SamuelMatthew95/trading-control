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
    op.execute(
        """
        ALTER TABLE prices_snapshot
        ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'prices_snapshot'
                  AND column_name = 'created_at'
            ) THEN
                EXECUTE '
                    UPDATE prices_snapshot
                    SET recorded_at = COALESCE(recorded_at, created_at, NOW())
                    WHERE recorded_at IS NULL
                ';
            ELSE
                EXECUTE '
                    UPDATE prices_snapshot
                    SET recorded_at = COALESCE(recorded_at, NOW())
                    WHERE recorded_at IS NULL
                ';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE prices_snapshot
        ALTER COLUMN recorded_at SET DEFAULT NOW()
        """
    )
    op.execute(
        """
        ALTER TABLE prices_snapshot
        ALTER COLUMN recorded_at SET NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'prices_snapshot'
                  AND column_name = 'recorded_at'
            ) THEN
                EXECUTE '
                    CREATE INDEX IF NOT EXISTS ix_prices_snapshot_symbol_recorded_at
                    ON prices_snapshot (symbol, recorded_at DESC)
                ';
            ELSIF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'prices_snapshot'
                  AND column_name = 'updated_at'
            ) THEN
                EXECUTE '
                    CREATE INDEX IF NOT EXISTS ix_prices_snapshot_symbol_updated_at
                    ON prices_snapshot (symbol, updated_at DESC)
                ';
            ELSIF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'prices_snapshot'
                  AND column_name = 'created_at'
            ) THEN
                EXECUTE '
                    CREATE INDEX IF NOT EXISTS ix_prices_snapshot_symbol_created_at
                    ON prices_snapshot (symbol, created_at DESC)
                ';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prices_snapshot")
