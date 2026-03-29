"""Add indexes for canonical schema tables.

Revision ID: add_canonical_schema_indexes
Revises: add_canonical_schema_tables
Create Date: 2026-03-28 14:50:00.000000

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = 'add_canonical_schema_indexes'
down_revision = 'seed_agent_pool'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Events table indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_entity ON events (entity_type, entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_processed ON events (processed);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at) USING BRIN;")
    
    # System metrics indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_system_metrics_name ON system_metrics (metric_name);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp ON system_metrics (timestamp) USING BRIN;")
    
    # Vector memory embedding index (ivfflat)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_vector_memory_embedding
        ON vector_memory USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)
    
    # Agent performance indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_trace_id ON agent_runs (trace_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs (status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_trace_id ON agent_logs (trace_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_agent_run_id ON agent_logs (agent_run_id);")
    
    # Trade performance indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_trade_performance_strategy_id ON trade_performance (strategy_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trade_performance_symbol ON trade_performance (symbol);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trade_performance_entry_time ON trade_performance (entry_time);")
    
    # Orders and positions indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy_id ON orders (strategy_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders (symbol);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_positions_strategy_symbol ON positions (strategy_id, symbol);")


def downgrade() -> None:
    # Drop indexes in reverse order
    indexes = [
        'idx_positions_strategy_symbol',
        'idx_orders_status',
        'idx_orders_symbol', 
        'idx_orders_strategy_id',
        'idx_trade_performance_entry_time',
        'idx_trade_performance_symbol',
        'idx_trade_performance_strategy_id',
        'idx_agent_logs_agent_run_id',
        'idx_agent_logs_trace_id',
        'idx_agent_runs_status',
        'idx_agent_runs_trace_id',
        'idx_vector_memory_embedding',
        'idx_system_metrics_timestamp',
        'idx_system_metrics_name',
        'idx_events_created_at',
        'idx_events_processed',
        'idx_events_entity',
        'idx_events_type'
    ]
    
    for index in indexes:
        op.execute(f"DROP INDEX IF EXISTS {index};")
