"""Add prices_snapshot and agent_heartbeats tables.

Revision ID: add_price_and_agent_tables
Revises: b2850e0a1b2
Create Date: 2026-03-28 14:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_price_and_agent_tables'
down_revision = 'b2850e0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create prices_snapshot table
    op.execute("""
        CREATE TABLE IF NOT EXISTS prices_snapshot (
            symbol       VARCHAR(20) PRIMARY KEY,
            price        NUMERIC(20, 8) NOT NULL,
            change_amt   NUMERIC(20, 8),
            change_pct   NUMERIC(10, 4),
            updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    
    # Create agent_heartbeats table
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_heartbeats (
            agent_name   VARCHAR(50) PRIMARY KEY,
            status       VARCHAR(20) NOT NULL DEFAULT 'WAITING',
            last_event   TEXT,
            event_count  INTEGER DEFAULT 0,
            last_seen    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    
    # Create indexes for better performance
    op.execute("CREATE INDEX IF NOT EXISTS idx_prices_snapshot_updated_at ON prices_snapshot(updated_at);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_last_seen ON agent_heartbeats(last_seen);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_status ON agent_heartbeats(status);")


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_prices_snapshot_updated_at;")
    op.execute("DROP INDEX IF EXISTS idx_agent_heartbeats_last_seen;")
    op.execute("DROP INDEX IF EXISTS idx_agent_heartbeats_status;")
    
    # Drop tables
    op.execute("DROP TABLE IF EXISTS agent_heartbeats;")
    op.execute("DROP TABLE IF EXISTS prices_snapshot;")
