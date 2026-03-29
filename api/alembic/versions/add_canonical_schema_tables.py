"""Add canonical schema tables from Section 0.

Revision ID: add_canonical_schema_tables
Revises: add_price_and_agent_tables
Create Date: 2026-03-28 14:45:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_canonical_schema_tables'
down_revision = 'add_price_and_agent_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create extensions first
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # Core tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL UNIQUE,
            description     TEXT,
            config          JSONB NOT NULL DEFAULT '{}',
            schema_version  VARCHAR NOT NULL DEFAULT 'v2',
            source          VARCHAR NOT NULL,
            status          VARCHAR NOT NULL DEFAULT 'active',
            created_by      VARCHAR,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id       UUID NOT NULL,
            external_order_id TEXT UNIQUE,
            idempotency_key   TEXT NOT NULL UNIQUE,
            symbol            TEXT NOT NULL,
            side              TEXT NOT NULL,
            order_type        TEXT NOT NULL,
            quantity          NUMERIC NOT NULL,
            price             NUMERIC,
            filled_quantity   NUMERIC NOT NULL DEFAULT 0,
            filled_price      NUMERIC,
            status            TEXT NOT NULL,
            exchange          TEXT,
            commission        NUMERIC NOT NULL DEFAULT 0,
            order_metadata    JSONB NOT NULL DEFAULT '{}',
            schema_version    VARCHAR NOT NULL DEFAULT 'v2',
            source            VARCHAR NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id       UUID NOT NULL,
            symbol            TEXT NOT NULL,
            quantity          NUMERIC NOT NULL,
            avg_cost          NUMERIC NOT NULL,
            market_value      NUMERIC,
            unrealized_pnl    NUMERIC,
            last_price        NUMERIC,
            position_metadata JSONB NOT NULL DEFAULT '{}',
            schema_version    VARCHAR NOT NULL DEFAULT 'v2',
            source            VARCHAR NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (strategy_id, symbol)
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_performance (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id            UUID NOT NULL,
            agent_id               UUID,
            trade_id               TEXT NOT NULL,
            symbol                 TEXT NOT NULL,
            entry_time             TIMESTAMPTZ NOT NULL,
            exit_time              TIMESTAMPTZ,
            entry_price            NUMERIC NOT NULL,
            exit_price             NUMERIC,
            quantity               NUMERIC NOT NULL,
            pnl                    NUMERIC,
            pnl_percent            NUMERIC,
            holding_period_minutes INTEGER,
            max_drawdown           NUMERIC,
            max_runup              NUMERIC,
            sharpe_ratio           NUMERIC,
            trade_type             VARCHAR,
            exit_reason            TEXT,
            regime                 TEXT,
            hour_utc               INTEGER,
            performance_metrics    JSONB NOT NULL DEFAULT '{}',
            schema_version         VARCHAR NOT NULL DEFAULT 'v2',
            source                 VARCHAR NOT NULL,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (strategy_id, trade_id)
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type      TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       UUID,
            idempotency_key TEXT NOT NULL UNIQUE,
            processed       BOOLEAN NOT NULL DEFAULT false,
            data            JSONB NOT NULL DEFAULT '{}',
            schema_version  VARCHAR NOT NULL DEFAULT 'v2',
            source          VARCHAR NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            msg_id        TEXT PRIMARY KEY,
            stream        TEXT NOT NULL,
            processed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type TEXT,
            entity_id   UUID,
            action      TEXT NOT NULL,
            old_values  JSONB,
            new_values  JSONB,
            user_id     VARCHAR,
            ip_address  INET,
            user_agent  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS schema_write_audit (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            table_name     TEXT NOT NULL,
            schema_version VARCHAR NOT NULL,
            source         VARCHAR NOT NULL,
            operation      VARCHAR NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    # Agent tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_pool (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name         TEXT NOT NULL UNIQUE,
            agent_type   TEXT NOT NULL,
            description  TEXT,
            config       JSONB NOT NULL DEFAULT '{}',
            capabilities JSONB NOT NULL DEFAULT '[]',
            status       TEXT NOT NULL DEFAULT 'active',
            version      TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id          UUID NOT NULL,
            trace_id          UUID NOT NULL,
            run_type          TEXT,
            trigger_event     TEXT,
            input_data        JSONB NOT NULL DEFAULT '{}',
            output_data       JSONB NOT NULL DEFAULT '{}',
            schema_version    VARCHAR NOT NULL DEFAULT 'v2',
            source            VARCHAR NOT NULL,
            status            TEXT NOT NULL DEFAULT 'running',
            error_message     TEXT,
            execution_time_ms INTEGER,
            tokens_used       INTEGER,
            cost_usd          NUMERIC NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_run_id UUID NOT NULL,
            log_level    TEXT NOT NULL,
            message      TEXT NOT NULL,
            step_name    TEXT,
            step_data    JSONB NOT NULL DEFAULT '{}',
            trace_id     UUID NOT NULL,
            schema_version VARCHAR NOT NULL DEFAULT 'v2',
            source       VARCHAR NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_grades (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id     UUID NOT NULL,
            agent_run_id UUID,
            grade_type   TEXT NOT NULL,
            score        NUMERIC NOT NULL,
            metrics      JSONB NOT NULL DEFAULT '{}',
            feedback     TEXT,
            schema_version VARCHAR NOT NULL DEFAULT 'v2',
            source       VARCHAR NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    op.execute("""
        CREATE TABLE IF NOT EXISTS vector_memory (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id       UUID,
            strategy_id    UUID,
            content        TEXT NOT NULL,
            content_type   TEXT NOT NULL,
            embedding      VECTOR(1536) NOT NULL,
            vector_metadata JSONB NOT NULL DEFAULT '{}',
            outcome        JSONB,
            schema_version VARCHAR NOT NULL DEFAULT 'v2',
            source         VARCHAR NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    
    # Analytics tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS system_metrics (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            metric_name  TEXT NOT NULL,
            metric_value NUMERIC NOT NULL,
            metric_unit  TEXT,
            tags         JSONB NOT NULL DEFAULT '{}',
            schema_version VARCHAR NOT NULL DEFAULT 'v2',
            source       VARCHAR NOT NULL,
            timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    # Drop tables in reverse order
    tables = [
        'system_metrics',
        'vector_memory', 
        'agent_grades',
        'agent_logs',
        'agent_runs',
        'agent_pool',
        'schema_write_audit',
        'audit_log',
        'processed_events',
        'events',
        'trade_performance',
        'positions',
        'orders',
        'strategies'
    ]
    
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table};")
