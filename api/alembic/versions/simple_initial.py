"""Simple initial schema for SQLite compatibility

Revision ID: simple_initial
Revises: 
Create Date: 2026-03-24 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'simple_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create strategies table
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("risk_limits", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # Create orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("broker_order_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("filled_at", sa.DateTime(), nullable=True),
    )

    # Create agent_runs table with strategy_id
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(64), nullable=True),
        sa.Column("signal_data", sa.Text(), nullable=True),
        sa.Column("action", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("primary_edge", sa.Text(), nullable=True),
        sa.Column("risk_factors", sa.Text(), nullable=True),
        sa.Column("size_pct", sa.Float(), nullable=True),
        sa.Column("stop_atr_x", sa.Float(), nullable=True),
        sa.Column("rr_ratio", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("trace_id", sa.String(255), nullable=True),
        sa.Column("fallback", sa.Boolean(), server_default='false'),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # Create indexes
    op.create_index('ix_agent_runs_strategy_id', 'agent_runs', ['strategy_id'])
    op.create_index('ix_agent_runs_trace_id', 'agent_runs', ['trace_id'])

def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("orders")
    op.drop_table("strategies")
