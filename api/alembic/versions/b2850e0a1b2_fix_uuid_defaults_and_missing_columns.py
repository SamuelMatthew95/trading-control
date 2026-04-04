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


def _split_table_name(table_name: str) -> tuple[str | None, str]:
    if "." not in table_name:
        return None, table_name
    schema, relation = table_name.split(".", 1)
    return schema, relation


def _has_column(table_name: str, column_name: str, schema: str | None = None) -> bool:
    bind = op.get_bind()
    table_schema = schema if schema is not None else _resolve_table_schema(table_name)
    _, relation_name = _split_table_name(table_name)
    inspector = sa.inspect(bind)
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(relation_name, schema=table_schema)
    )


def _has_index(table_name: str, index_name: str, schema: str | None = None) -> bool:
    bind = op.get_bind()
    table_schema = schema if schema is not None else _resolve_table_schema(table_name)
    _, relation_name = _split_table_name(table_name)
    inspector = sa.inspect(bind)
    return any(
        index["name"] == index_name
        for index in inspector.get_indexes(relation_name, schema=table_schema)
    )


def _resolve_table_schema(table_name: str) -> str | None:
    explicit_schema, relation_name = _split_table_name(table_name)
    if explicit_schema is not None:
        return explicit_schema

    bind = op.get_bind()
    return bind.execute(
        sa.text(
            """
            SELECT n.nspname
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE c.oid = to_regclass(:table_name)
            """
        ),
        {"table_name": relation_name},
    ).scalar()


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
    agent_runs_schema = _resolve_table_schema("agent_runs")

    # Add missing columns to agent_runs (matching reasoning_agent.py raw SQL)
    agent_runs_additions = [
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
        sa.Column("fallback", sa.Boolean(), server_default="false"),
    ]
    for column in agent_runs_additions:
        if not _has_column("agent_runs", column.name, schema=agent_runs_schema):
            op.add_column("agent_runs", column, schema=agent_runs_schema)

    if _has_column("agent_runs", "trace_id", schema=agent_runs_schema) and not _has_index(
        "agent_runs", "ix_agent_runs_trace_id", schema=agent_runs_schema
    ):
        op.create_index(
            "ix_agent_runs_trace_id",
            "agent_runs",
            ["trace_id"],
            schema=agent_runs_schema,
        )


def downgrade() -> None:
    agent_runs_schema = _resolve_table_schema("agent_runs")

    # Remove added columns from agent_runs
    for column_name in (
        "symbol",
        "signal_data",
        "action",
        "confidence",
        "primary_edge",
        "risk_factors",
        "size_pct",
        "stop_atr_x",
        "rr_ratio",
        "latency_ms",
        "cost_usd",
        "trace_id",
        "fallback",
    ):
        if _has_column("agent_runs", column_name, schema=agent_runs_schema):
            op.drop_column("agent_runs", column_name, schema=agent_runs_schema)
    if _has_index("agent_runs", "ix_agent_runs_trace_id", schema=agent_runs_schema):
        op.drop_index(
            "ix_agent_runs_trace_id",
            table_name="agent_runs",
            schema=agent_runs_schema,
        )

    # Remove server defaults from id columns
    op.alter_column("vector_memory", "id", server_default=None)
    op.alter_column("agent_logs", "id", server_default=None)
    op.alter_column("llm_cost_tracking", "id", server_default=None)
