"""Add trade_ledger table for transaction architecture

Revision ID: add_trade_ledger_table
Revises: upgrade_to_v3_schema
Create Date: 2026-04-13 15:30:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_trade_ledger_table"
down_revision = None  # This will be a new head
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create trade_ledger table
    op.create_table(
        "trade_ledger",
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("parent_trade_id", postgresql.UUID(as_uuid=True), nullable=True, comment="Links SELL to its corresponding BUY"),
        sa.Column("agent_id", sa.String(), nullable=False, comment="Which agent generated this trade"),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("trade_type", sa.Enum("BUY", "SELL", name="trade_type"), nullable=False, comment="BUY opens position, SELL closes position"),
        sa.Column("quantity", sa.Numeric(precision=18, scale=8), nullable=False, comment="Number of shares/contracts"),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=True, comment="Price at which trade was executed (filled for BUY, filled for SELL)"),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=8), nullable=True, comment="Only populated for SELL trades - the closing price"),
        sa.Column("pnl_realized", sa.Numeric(precision=18, scale=8), server_default="0", nullable=False, comment="Realized P&L = (exit_price - entry_price) * quantity"),
        sa.Column("status", sa.Enum("OPEN", "CLOSED", "CANCELLED", name="trade_status"), nullable=False, default="OPEN", comment="OPEN for BUY, CLOSED when paired with SELL"),
        sa.Column("execution_mode", sa.Enum("MOCK", "LIVE", name="execution_mode"), nullable=False, default="MOCK", comment="Whether this was a paper trade or real money"),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=2), nullable=True, comment="Agent's confidence in this trade (0-100)"),
        sa.Column("trade_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment="Additional trade context, signals, etc."),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="v3"),
        sa.Column("source", sa.String(), nullable=False, comment="System source identifier"),
        sa.Column("trace_id", sa.String(), nullable=True, comment="Trace ID for debugging"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True, comment="When the trade was closed (SELL filled)"),
        sa.ForeignKeyConstraint(["parent_trade_id"], ["trade_ledger.trade_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trade_id"),
        sa.CheckConstraint("schema_version = 'v3'", name="check_trade_ledger_schema_v3"),
        sa.CheckConstraint("quantity > 0", name="check_quantity_positive"),
        sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 100", name="check_confidence_range"),
        sa.CheckConstraint(
            "(trade_type = 'BUY' AND status IN ('OPEN', 'CANCELLED')) OR "
            "(trade_type = 'SELL' AND status IN ('CLOSED', 'CANCELLED'))",
            name="check_trade_type_status_consistency"
        ),
        sa.CheckConstraint(
            "(trade_type = 'BUY' AND entry_price IS NOT NULL AND exit_price IS NULL) OR "
            "(trade_type = 'SELL' AND entry_price IS NOT NULL AND exit_price IS NOT NULL)",
            name="check_price_logic"
        ),
    )

    # Create indexes
    op.create_index("idx_trade_ledger_agent_created", "trade_ledger", ["agent_id", "created_at"])
    op.create_index("idx_trade_ledger_symbol_status", "trade_ledger", ["symbol", "status"])
    op.create_index("idx_trade_ledger_strategy_symbol", "trade_ledger", ["strategy_id", "symbol"])
    op.create_index("idx_trade_ledger_parent_trade", "trade_ledger", ["parent_trade_id"])
    op.create_index("idx_trade_ledger_execution_mode", "trade_ledger", ["execution_mode"])
    op.create_index("idx_trade_ledger_trace_id", "trade_ledger", ["trace_id"])
    op.create_index("idx_trade_ledger_schema_version", "trade_ledger", ["schema_version"])

    # Foreign key indexes
    op.create_index(op.f("ix_trade_ledger_strategy_id"), "trade_ledger", ["strategy_id"])
    op.create_index(op.f("ix_trade_ledger_agent_id"), "trade_ledger", ["agent_id"])
    op.create_index(op.f("ix_trade_ledger_symbol"), "trade_ledger", ["symbol"])
    op.create_index(op.f("ix_trade_ledger_trade_type"), "trade_ledger", ["trade_type"])
    op.create_index(op.f("ix_trade_ledger_status"), "trade_ledger", ["status"])
    op.create_index(op.f("ix_trade_ledger_execution_mode"), "trade_ledger", ["execution_mode"])
    op.create_index(op.f("ix_trade_ledger_schema_version"), "trade_ledger", ["schema_version"])
    op.create_index(op.f("ix_trade_ledger_trace_id"), "trade_ledger", ["trace_id"])


def downgrade() -> None:
    op.drop_table("trade_ledger")
    op.execute("DROP TYPE IF EXISTS trade_type")
    op.execute("DROP TYPE IF EXISTS trade_status")
    op.execute("DROP TYPE IF EXISTS execution_mode")
