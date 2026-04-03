"""Add trade_lifecycle and agent_instances tables

Revision ID: add_trade_lifecycle_v1
Revises: upgrade_to_v3
Create Date: 2026-04-01 00:00:00.000000

Adds:
  - agent_instances: tracks each running instance of an agent by UUID,
    enabling retire-and-replace lifecycle with full audit history
  - trade_lifecycle: single table joining signal→decision→execution→grade→
    reflection for every trade, giving end-to-end traceability
  - instance_id FK on agent_runs so every run links to the specific instance
    that executed it
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.sql.sqltypes import NullType

revision: str = "add_trade_lifecycle_v1"
down_revision: str | None = "upgrade_to_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_sql_type(table_name: str, default: str = "UUID") -> str:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        for column in inspector.get_columns(table_name):
            if column["name"] == "id":
                detected_type = column.get("type")
                if detected_type is None or isinstance(detected_type, NullType):
                    return default
                return str(detected_type.compile(dialect=bind.dialect))
    except NoSuchTableError:
        return default
    return default


def upgrade() -> None:
    # ------------------------------------------------------------------
    # agent_instances — one row per running agent process
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_instances (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_key    VARCHAR(255) NOT NULL,
            pool_name       VARCHAR(128) NOT NULL,
            status          VARCHAR(16)  NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'retired')),
            started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            retired_at      TIMESTAMPTZ,
            event_count     INTEGER      NOT NULL DEFAULT 0,
            metadata        JSONB        NOT NULL DEFAULT '{}',
            schema_version  VARCHAR(16)  NOT NULL DEFAULT 'v3',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_instances_key    ON agent_instances(instance_key)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_instances_status ON agent_instances(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_instances_pool   ON agent_instances(pool_name)"
    )

    # Add instance_id to agent_runs (nullable — old rows have no instance)
    agent_instances_id_type = _id_sql_type("agent_instances")
    op.execute(f"""
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS instance_id {agent_instances_id_type}
                REFERENCES agent_instances(id) ON DELETE SET NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_instance ON agent_runs(instance_id)")

    # ------------------------------------------------------------------
    # trade_lifecycle — end-to-end trade traceability
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS trade_lifecycle (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol               VARCHAR(64)    NOT NULL,
            side                 VARCHAR(8)     NOT NULL CHECK (side IN ('buy', 'sell')),
            qty                  NUMERIC(18, 8),
            entry_price          NUMERIC(18, 8),
            exit_price           NUMERIC(18, 8),
            pnl                  NUMERIC(18, 8),
            pnl_percent          NUMERIC(18, 8),
            order_id             UUID,
            signal_trace_id      VARCHAR(255),
            decision_trace_id    VARCHAR(255),
            execution_trace_id   VARCHAR(255),
            grade_trace_id       VARCHAR(255),
            reflection_trace_id  VARCHAR(255),
            grade                VARCHAR(2),
            grade_score          NUMERIC(5, 2),
            grade_label          VARCHAR(64),
            status               VARCHAR(32)    NOT NULL DEFAULT 'signal'
                                     CHECK (status IN (
                                         'signal','decision','executing',
                                         'filled','graded','reflected'
                                     )),
            filled_at            TIMESTAMPTZ,
            graded_at            TIMESTAMPTZ,
            reflected_at         TIMESTAMPTZ,
            schema_version       VARCHAR(16)    NOT NULL DEFAULT 'v3',
            source               VARCHAR(64)    NOT NULL DEFAULT 'execution_engine',
            created_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tl_exec_trace_uq ON trade_lifecycle(execution_trace_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tl_symbol         ON trade_lifecycle(symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tl_status         ON trade_lifecycle(status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tl_signal_trace   ON trade_lifecycle(signal_trace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tl_created        ON trade_lifecycle(created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tl_grade          ON trade_lifecycle(grade)")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS instance_id")
    op.execute("DROP TABLE IF EXISTS trade_lifecycle")
    op.execute("DROP TABLE IF EXISTS agent_instances")
