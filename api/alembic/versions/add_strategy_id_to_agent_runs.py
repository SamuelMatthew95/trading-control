"""Add strategy_id to agent_runs

Revision ID: add_strategy_id_to_agent_runs
Revises: simple_initial
Create Date: 2026-03-24 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_strategy_id_to_agent_runs'
down_revision = 'simple_initial'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add strategy_id column to agent_runs table
    op.add_column('agent_runs', sa.Column('strategy_id', sa.String(), nullable=True))
    
    # Create index for performance
    op.create_index('ix_agent_runs_strategy_id', 'agent_runs', ['strategy_id'])

def downgrade() -> None:
    # Remove index and column
    op.drop_index('ix_agent_runs_strategy_id')
    op.drop_column('agent_runs', 'strategy_id')
