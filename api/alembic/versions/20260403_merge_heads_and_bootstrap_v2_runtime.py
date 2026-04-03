"""Merge alembic heads and bootstrap v2 runtime schema safely.

Revision ID: 20260403_v2_bootstrap
Revises: add_prices_snapshot, add_trade_lifecycle_v1
Create Date: 2026-04-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260403_v2_bootstrap"
down_revision: str | Sequence[str] | None = ("add_prices_snapshot", "add_trade_lifecycle_v1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_pool (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(128) UNIQUE NOT NULL,
            agent_type VARCHAR(32) NOT NULL DEFAULT 'analysis',
            description TEXT,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            version VARCHAR(16) NOT NULL DEFAULT '1.0.0',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID REFERENCES agent_pool(id) ON DELETE SET NULL,
            agent_run_id UUID,
            trace_id VARCHAR(255) NOT NULL,
            run_type VARCHAR(32) NOT NULL DEFAULT 'analysis',
            trigger_event VARCHAR(255),
            input_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_data JSONB,
            strategy_id VARCHAR(255),
            symbol VARCHAR(64),
            signal_data JSONB,
            action VARCHAR(64),
            confidence DOUBLE PRECISION,
            primary_edge TEXT,
            risk_factors JSONB,
            size_pct DOUBLE PRECISION,
            stop_atr_x DOUBLE PRECISION,
            rr_ratio DOUBLE PRECISION,
            latency_ms INTEGER,
            cost_usd DOUBLE PRECISION,
            fallback BOOLEAN NOT NULL DEFAULT FALSE,
            schema_version VARCHAR(16) NOT NULL DEFAULT 'v3',
            source VARCHAR(64) NOT NULL DEFAULT 'reasoning_agent',
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            error_message TEXT,
            execution_time_ms INTEGER,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            instance_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
            trace_id VARCHAR(255) NOT NULL,
            log_type VARCHAR(100) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            log_level VARCHAR(16) NOT NULL DEFAULT 'info',
            message TEXT,
            step_name VARCHAR(128),
            step_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            schema_version VARCHAR(16) NOT NULL DEFAULT 'v3',
            source VARCHAR(64) NOT NULL DEFAULT 'agent',
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_grades (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID REFERENCES agent_pool(id) ON DELETE SET NULL,
            agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
            trace_id VARCHAR(255),
            grade_type VARCHAR(32) NOT NULL,
            score NUMERIC NOT NULL,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            feedback TEXT,
            schema_version VARCHAR(16) NOT NULL DEFAULT 'v3',
            source VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type VARCHAR(100) NOT NULL,
            entity_type VARCHAR(100),
            entity_id VARCHAR(255),
            idempotency_key VARCHAR(255) UNIQUE,
            processed BOOLEAN NOT NULL DEFAULT FALSE,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            schema_version VARCHAR(16) NOT NULL DEFAULT 'v3',
            source VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_events (
            msg_id VARCHAR(255) PRIMARY KEY,
            stream VARCHAR(100) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_heartbeats (
            agent_name VARCHAR(128) PRIMARY KEY,
            status VARCHAR(32) NOT NULL,
            last_event TEXT,
            event_count INTEGER NOT NULL DEFAULT 0,
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id VARCHAR(255) NOT NULL,
            symbol VARCHAR(64) NOT NULL,
            side VARCHAR(16) NOT NULL,
            qty NUMERIC(20, 8) NOT NULL,
            price NUMERIC(20, 8) NOT NULL,
            status VARCHAR(32) NOT NULL,
            idempotency_key VARCHAR(255) UNIQUE NOT NULL,
            broker_order_id VARCHAR(255),
            external_order_id VARCHAR(255),
            trace_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            filled_at TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_memory (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content TEXT NOT NULL,
            embedding vector(1536),
            metadata_ JSONB NOT NULL DEFAULT '{}'::jsonb,
            outcome JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Additive compatibility columns for existing installs.
    op.execute("ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS agent_run_id UUID")
    op.execute("ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb")
    op.execute(
        "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"
    )
    op.execute(
        "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS timestamp TIMESTAMPTZ DEFAULT NOW()"
    )

    op.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS trace_id VARCHAR(255)")
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS input_data JSONB DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS output_data JSONB")
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'running'"
    )
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"
    )
    op.execute(
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"
    )

    op.execute("ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS agent_run_id UUID")
    op.execute("ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS trace_id VARCHAR(255)")
    op.execute(
        "ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"
    )

    op.execute("ALTER TABLE trade_lifecycle ADD COLUMN IF NOT EXISTS agent_run_id UUID")

    # Defaults for id columns that were sometimes created as varchar.
    op.execute(
        """
        DO $$
        DECLARE _dtype TEXT;
        BEGIN
          SELECT data_type INTO _dtype
          FROM information_schema.columns
          WHERE table_name = 'orders' AND column_name = 'id';
          IF _dtype = 'uuid' THEN
            EXECUTE 'ALTER TABLE orders ALTER COLUMN id SET DEFAULT gen_random_uuid()';
          ELSIF _dtype IS NOT NULL THEN
            EXECUTE 'ALTER TABLE orders ALTER COLUMN id SET DEFAULT gen_random_uuid()::text';
          END IF;
        END $$;
        """
    )

    # Indexes for tracing and hot paths.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_trace_created ON agent_runs(trace_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_trace_created ON agent_logs(trace_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_run_created ON agent_logs(agent_run_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_grades_run_created ON agent_grades(agent_run_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_symbol_created ON orders(symbol, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_exec_trace ON trade_lifecycle(execution_trace_id)"
    )


def downgrade() -> None:
    # No destructive downgrade for safety.
    pass
