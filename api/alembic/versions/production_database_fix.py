"""Production-ready database migration setup

This fixes the migration chain for PostgreSQL deployment on Render.
"""

import os
from alembic import op
import sqlalchemy as sa

# Check if we're running on PostgreSQL
IS_POSTGRES = "postgresql" in os.getenv("DATABASE_URL", "")

def upgrade_postgres():
    """PostgreSQL-specific migrations"""
    # Enable extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
    
    # Set UUID defaults
    op.alter_column('vector_memory', 'id',
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String())
    op.alter_column('agent_logs', 'id',
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String())
    op.alter_column('llm_cost_tracking', 'id',
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String())

def upgrade_sqlite():
    """SQLite-specific migrations"""
    # Skip extensions and UUID defaults
    pass

def upgrade():
    if IS_POSTGRES:
        upgrade_postgres()
    else:
        upgrade_sqlite()
    
    # Common migrations for both databases
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check if agent_runs table needs new columns
    if 'agent_runs' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('agent_runs')]
        
        # Add missing columns
        new_columns = {
            'symbol': sa.String(64),
            'signal_data': sa.Text(),
            'action': sa.String(32),
            'confidence': sa.Float(),
            'primary_edge': sa.Text(),
            'risk_factors': sa.Text(),
            'size_pct': sa.Float(),
            'stop_atr_x': sa.Float(),
            'rr_ratio': sa.Float(),
            'latency_ms': sa.Integer(),
            'cost_usd': sa.Float(),
            'trace_id': sa.String(255),
            'fallback': sa.Boolean()
        }
        
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                op.add_column('agent_runs', sa.Column(col_name, col_type, nullable=True))
        
        # Create indexes
        if 'ix_agent_runs_strategy_id' not in [idx['name'] for idx in inspector.get_indexes('agent_runs')]:
            op.create_index('ix_agent_runs_strategy_id', 'agent_runs', ['strategy_id'])
        
        if 'ix_agent_runs_trace_id' not in [idx['name'] for idx in inspector.get_indexes('agent_runs')]:
            op.create_index('ix_agent_runs_trace_id', 'agent_runs', ['trace_id'])

def downgrade():
    # Remove indexes
    try:
        op.drop_index('ix_agent_runs_strategy_id')
        op.drop_index('ix_agent_runs_trace_id')
    except sa.exc.OperationalError:
        pass  # Indexes might not exist
