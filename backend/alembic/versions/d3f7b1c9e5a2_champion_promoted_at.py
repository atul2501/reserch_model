"""champion evidence: StrategyVersion.promoted_at

Revision ID: d3f7b1c9e5a2
Revises: c9e5a3b7d1f2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d3f7b1c9e5a2"
down_revision = "c9e5a3b7d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("strategy_versions") as batch:
        batch.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("strategy_versions") as batch:
        batch.drop_column("promoted_at")
