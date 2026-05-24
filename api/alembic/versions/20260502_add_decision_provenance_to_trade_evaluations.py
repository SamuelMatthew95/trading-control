"""Add decision provenance to trade_evaluations.

Revision ID: 20260502_decision_provenance
Revises: 20260501_learning_pipeline
Create Date: 2026-05-02

Adds nullable columns so a graded trade can be traced back to the decision
that produced it:
  - model_used:        the "provider:model" label of the LLM that made the call
  - primary_edge:      the one-line thesis recorded by ReasoningAgent
  - decision_cost_usd: LLM cost of the decision, for per-model net ROI

All nullable with no backfill — existing rows keep NULL. Idempotent
ADD COLUMN IF NOT EXISTS matches the additive style of the prior migrations.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260502_decision_provenance"
down_revision: str | None = "20260501_learning_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trade_evaluations ADD COLUMN IF NOT EXISTS model_used VARCHAR(64)")
    op.execute("ALTER TABLE trade_evaluations ADD COLUMN IF NOT EXISTS primary_edge TEXT")
    op.execute("ALTER TABLE trade_evaluations ADD COLUMN IF NOT EXISTS decision_cost_usd NUMERIC")


def downgrade() -> None:
    op.execute("ALTER TABLE trade_evaluations DROP COLUMN IF EXISTS decision_cost_usd")
    op.execute("ALTER TABLE trade_evaluations DROP COLUMN IF EXISTS primary_edge")
    op.execute("ALTER TABLE trade_evaluations DROP COLUMN IF EXISTS model_used")
