"""Fix UUID defaults and missing columns for agent_runs

Revision ID: b2850e0a1b2
Revises: 0001_initial
Create Date: 2026-03-22 19:17:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2850e0a1b2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Set server defaults for id columns that use raw SQL inserts without specifying id
    op.alter_column(
        "vector_memory",
        "id",
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String(),
    )
    op.alter_column(
        "agent_logs",
        "id",
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String(),
    )
    op.alter_column(
        "llm_cost_tracking",
        "id",
        server_default=sa.text("gen_random_uuid()::text"),
        existing_type=sa.String(),
    )

    # Add missing columns to agent_runs (matching reasoning_agent.py raw SQL)
    op.add_column("agent_runs", sa.Column("symbol", sa.String(64), nullable=True))
    op.add_column("agent_runs", sa.Column("signal_data", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("action", sa.String(32), nullable=True))
    op.add_column("agent_runs", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("primary_edge", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("risk_factors", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("size_pct", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("stop_atr_x", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("rr_ratio", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("agent_runs", sa.Column("cost_usd", sa.Float(), nullable=True))
    op.add_column("agent_runs", sa.Column("trace_id", sa.String(255), nullable=True))
    op.add_column("agent_runs", sa.Column("fallback", sa.Boolean(), server_default="false"))
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])

    # Remove old unused columns from agent_runs
    op.drop_column("agent_runs", "task_id")
    op.drop_column("agent_runs", "decision_json")
    op.drop_column("agent_runs", "trace_json")


def downgrade() -> None:
    # Remove added columns from agent_runs
    op.drop_column("agent_runs", "symbol")
    op.drop_column("agent_runs", "signal_data")
    op.drop_column("agent_runs", "action")
    op.drop_column("agent_runs", "confidence")
    op.drop_column("agent_runs", "primary_edge")
    op.drop_column("agent_runs", "risk_factors")
    op.drop_column("agent_runs", "size_pct")
    op.drop_column("agent_runs", "stop_atr_x")
    op.drop_column("agent_runs", "rr_ratio")
    op.drop_column("agent_runs", "latency_ms")
    op.drop_column("agent_runs", "cost_usd")
    op.drop_column("agent_runs", "trace_id")
    op.drop_column("agent_runs", "fallback")
    op.drop_index("ix_agent_runs_trace_id")

    # Restore old columns to agent_runs
    op.add_column("agent_runs", sa.Column("task_id", sa.String(), nullable=False))
    op.add_column("agent_runs", sa.Column("decision_json", sa.Text(), nullable=False))
    op.add_column("agent_runs", sa.Column("trace_json", sa.Text(), nullable=False))

    # Remove server defaults from id columns
    op.alter_column("vector_memory", "id", server_default=None)
    op.alter_column("agent_logs", "id", server_default=None)
    op.alter_column("llm_cost_tracking", "id", server_default=None)
