"""Seed agent pool table with required agents.

Revision ID: seed_agent_pool
Revises: add_canonical_schema_tables
Create Date: 2026-03-28 15:00:00.000000

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = 'seed_agent_pool'
down_revision = 'add_canonical_schema_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Seed agent pool with all 7 agents using predictable UUIDs
    op.execute("""
        INSERT INTO agent_pool (id, name, agent_type, description, capabilities, schema_version, status, version, created_at, updated_at)
        VALUES
          ('a0000000-0000-0000-0000-000000000001', 'SIGNAL_AGENT',      'analysis',   'Detects price signals',        '["signal_detection"]',        'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000002', 'REASONING_AGENT',   'analysis',   'Applies trading rules',         '["rule_reasoning"]',   'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000003', 'GRADE_AGENT',       'analysis',   'Scores decision quality',       '["grading"]',          'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000004', 'IC_UPDATER',        'execution',  'Updates investment context',    '["ic_management"]',    'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000005', 'REFLECTION_AGENT',  'learning',   'Writes to vector memory',       '["memory_write"]',     'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000006', 'STRATEGY_PROPOSER', 'analysis',   'Updates strategy definitions',  '["strategy_update"]',  'active', '1.0', NOW(), NOW()),
          ('a0000000-0000-0000-0000-000000000007', 'NOTIFICATION_AGENT','monitoring', 'Fires trade alerts',            '["alerting"]',         'active', '1.0', NOW(), NOW())
        ON CONFLICT (name) DO NOTHING;
    """)


def downgrade() -> None:
    # Remove seeded agents
    op.execute("DELETE FROM agent_pool WHERE name IN ('SIGNAL_AGENT', 'REASONING_AGENT', 'GRADE_AGENT', 'IC_UPDATER', 'REFLECTION_AGENT', 'STRATEGY_PROPOSER', 'NOTIFICATION_AGENT');")
