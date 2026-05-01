"""Add learning pipeline tables: trade_evaluations, reflections, strategies.

Revision ID: 20260501_learning_pipeline
Revises: 20260427_agent_instances_unique_key
Create Date: 2026-05-01

Adds three typed tables for the learning pipeline:
  - trade_evaluations: per-trade deterministic scores (5 dimensions + grade)
  - reflections: quant pattern analysis with mistake clusters
  - strategies: proposed rule changes with expected improvement
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260501_learning_pipeline"
down_revision: str | None = "20260427_agent_instances_unique_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_evaluations (
            id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            trade_id         TEXT        NOT NULL,
            symbol           VARCHAR(32),
            side             VARCHAR(16),

            pnl              NUMERIC,
            return_pct       NUMERIC,

            entry_quality    NUMERIC,
            exit_quality     NUMERIC,
            timing_score     NUMERIC,
            signal_alignment NUMERIC,
            risk_reward      NUMERIC,

            overall_score    NUMERIC     NOT NULL,
            grade            VARCHAR(2)  NOT NULL,
            confidence       NUMERIC,

            mistakes         JSONB       NOT NULL DEFAULT '[]',
            strengths        JSONB       NOT NULL DEFAULT '[]',

            source           VARCHAR(64) NOT NULL DEFAULT 'grade_agent',
            schema_version   VARCHAR(16) NOT NULL DEFAULT 'v3',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_trade_evaluations_trade_id
        ON trade_evaluations (trade_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_trade_evaluations_created_at
        ON trade_evaluations (created_at DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,

            patterns         JSONB       NOT NULL DEFAULT '[]',
            mistake_clusters JSONB       NOT NULL DEFAULT '[]',
            recommendations  JSONB       NOT NULL DEFAULT '[]',

            trades_analyzed  INTEGER,
            win_rate         NUMERIC,
            avg_return       NUMERIC,
            confidence       NUMERIC,

            source           VARCHAR(64) NOT NULL DEFAULT 'reflection_agent',
            schema_version   VARCHAR(16) NOT NULL DEFAULT 'v3',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_reflections_created_at
        ON reflections (created_at DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id                   UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,

            rules                JSONB       NOT NULL DEFAULT '{}',
            description          TEXT,
            expected_improvement NUMERIC,
            status               VARCHAR(32) NOT NULL DEFAULT 'pending',
            reflection_id        TEXT,

            source               VARCHAR(64) NOT NULL DEFAULT 'strategy_proposer',
            schema_version       VARCHAR(16) NOT NULL DEFAULT 'v3',
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_strategies_created_at
        ON strategies (created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_strategies_status
        ON strategies (status)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategies")
    op.execute("DROP TABLE IF EXISTS reflections")
    op.execute("DROP TABLE IF EXISTS trade_evaluations")
