"""Initial Phase 2 schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UTC_NOW = sa.text("TIMEZONE('utc', NOW())")
UUID_DEFAULT = sa.text("gen_random_uuid()")


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **kw):
        return f"vector({self.dimensions})"


def _uuid_column(name: str = "id") -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        server_default=UUID_DEFAULT,
    )


def _timestamp_column(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name,
        postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=UTC_NOW,
    )


def _create_table(table_name: str, *columns: sa.Column) -> None:
    op.create_table(table_name, *columns, if_not_exists=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    _create_table(
        "strategies",
        _uuid_column(),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _timestamp_column(),
    )

    _create_table(
        "orders",
        _uuid_column(),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("broker_order_id", sa.String(length=255), nullable=True),
        _timestamp_column(),
        sa.Column("filled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )

    _create_table(
        "positions",
        _uuid_column(),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("unrealised_pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "opened_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=UTC_NOW,
        ),
    )

    _create_table(
        "agent_runs",
        _uuid_column(),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("signal_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("primary_edge", sa.String(length=255), nullable=False),
        sa.Column("risk_factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("size_pct", sa.Float(), nullable=False),
        sa.Column("stop_atr_x", sa.Float(), nullable=False),
        sa.Column("rr_ratio", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _timestamp_column(),
    )

    _create_table(
        "agent_logs",
        _uuid_column(),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("log_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp_column(),
    )

    _create_table(
        "vector_memory",
        _uuid_column(),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _timestamp_column(),
    )
    op.execute(
        """
        DO $$
        DECLARE _embedding_udt TEXT;
        BEGIN
            IF to_regtype('vector') IS NULL THEN
                RAISE NOTICE
                    'Skipping vector index creation because pgvector type is not available in schema %',
                    current_schema();
                RETURN;
            END IF;

            SELECT format_type(a.atttypid, a.atttypmod)
              INTO _embedding_udt
              FROM pg_attribute a
              JOIN pg_class t ON t.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = current_schema()
               AND t.relname = 'vector_memory'
               AND a.attname = 'embedding'
               AND a.attnum > 0
               AND NOT a.attisdropped;

            IF _embedding_udt IS NULL THEN
                RETURN;
            END IF;

            IF _embedding_udt NOT LIKE 'vector%' THEN
                BEGIN
                    EXECUTE
                        'ALTER TABLE vector_memory '
                        || 'ALTER COLUMN embedding TYPE vector(1536) '
                        || 'USING embedding::vector';
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE
                        'Skipping vector index creation because vector_memory.embedding '
                        || 'could not be converted to vector(1536): %',
                        SQLERRM;
                    RETURN;
                END;
            END IF;

            EXECUTE
                'CREATE INDEX IF NOT EXISTS vector_memory_embedding_idx '
                || 'ON vector_memory USING ivfflat '
                || '(embedding vector_cosine_ops) WITH (lists = 100)';
        END $$;
        """
    )

    _create_table(
        "trade_performance",
        _uuid_column(),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("holding_secs", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("market_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "factor_attribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        _timestamp_column(),
    )

    _create_table(
        "strategy_metrics",
        _uuid_column(),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_pnl", sa.Float(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=UTC_NOW,
        ),
    )

    _create_table(
        "factor_ic_history",
        _uuid_column(),
        sa.Column("factor_name", sa.String(length=128), nullable=False),
        sa.Column("ic_score", sa.Float(), nullable=False),
        sa.Column(
            "computed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=UTC_NOW,
        ),
    )

    _create_table(
        "system_metrics",
        _uuid_column(),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "timestamp",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=UTC_NOW,
        ),
    )

    _create_table(
        "audit_log",
        _uuid_column(),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp_column(),
    )

    _create_table(
        "order_reconciliation",
        _uuid_column(),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("discrepancy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _timestamp_column(),
    )

    _create_table(
        "llm_cost_tracking",
        _uuid_column(),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        _timestamp_column(),
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS audit_log_created_at_desc_idx ON audit_log (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS system_metrics_metric_name_timestamp_desc_idx "
        "ON system_metrics (metric_name, timestamp DESC)"
    )

    strategies_table = sa.table(
        "strategies",
        sa.column("name", sa.String),
        sa.column("rules", postgresql.JSONB),
        sa.column("risk_limits", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
    )

    strategy_seed_rows = [
        {
            "name": "BTC_MOMENTUM_V3",
            "rules": {
                "universe": ["BTC/USD"],
                "entry": {
                    "trend_window": "4h",
                    "trigger": "breakout_with_volume_confirmation",
                    "minimum_composite_score": 0.72,
                },
                "exit": {
                    "stop_loss": "2.2_atr",
                    "take_profit": "trailing_3.5_atr",
                    "time_stop_hours": 18,
                },
                "filters": {
                    "avoid_high_impact_news_minutes": 30,
                    "require_positive_funding_regime": False,
                },
            },
            "risk_limits": {
                "max_position_pct": 0.08,
                "max_daily_loss_pct": 0.025,
                "max_open_positions": 1,
                "slippage_bps_cap": 18,
            },
            "is_active": True,
        },
        {
            "name": "ETH_REVERSAL_V2",
            "rules": {
                "universe": ["ETH/USD"],
                "entry": {
                    "signal_family": "mean_reversion",
                    "oversold_rsi_threshold": 28,
                    "require_orderflow_divergence": True,
                },
                "exit": {
                    "stop_loss": "1.6_atr",
                    "first_target": "session_vwap",
                    "final_target": "2.8_atr",
                },
                "filters": {
                    "min_liquidity_usd": 5000000,
                    "disable_during_fomc_window": True,
                },
            },
            "risk_limits": {
                "max_position_pct": 0.06,
                "max_daily_loss_pct": 0.02,
                "max_open_positions": 1,
                "slippage_bps_cap": 15,
            },
            "is_active": True,
        },
    ]
    existing_strategy_names = {
        row[0]
        for row in op.get_bind().execute(
            sa.text(
                """
                SELECT name
                FROM strategies
                WHERE name IN ('BTC_MOMENTUM_V3', 'ETH_REVERSAL_V2')
                """
            )
        )
    }
    missing_seed_rows = [
        row for row in strategy_seed_rows if row["name"] not in existing_strategy_names
    ]
    if missing_seed_rows:
        op.bulk_insert(strategies_table, missing_seed_rows)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS system_metrics_metric_name_timestamp_desc_idx")
    op.execute("DROP INDEX IF EXISTS audit_log_created_at_desc_idx")
    op.execute("DROP INDEX IF EXISTS vector_memory_embedding_idx")
    op.drop_table("llm_cost_tracking")
    op.drop_table("order_reconciliation")
    op.drop_table("audit_log")
    op.drop_table("system_metrics")
    op.drop_table("factor_ic_history")
    op.drop_table("strategy_metrics")
    op.drop_table("trade_performance")
    op.drop_table("vector_memory")
    op.drop_table("agent_logs")
    op.drop_table("agent_runs")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("strategies")
