"""Add strategy_id to agent_runs table (SQLite compatible)

Revision ID: add_strategy_id_to_agent_runs
Revises: b2850e0a1b2
Create Date: 2026-03-24 18:38:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_strategy_id_to_agent_runs'
down_revision = 'b2850e0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # For SQLite, the strategy_id column already exists
    # Just ensure the index exists
    try:
        op.create_index('ix_agent_runs_strategy_id', 'agent_runs', ['strategy_id'])
    except sa.exc.OperationalError:
        # Index might already exist
        pass


def downgrade() -> None:
    # Remove strategy_id index from agent_runs table
    try:
        op.drop_index('ix_agent_runs_strategy_id')
    except sa.exc.OperationalError:
        # Index might not exist
        pass
