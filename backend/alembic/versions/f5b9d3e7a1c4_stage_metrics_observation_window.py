"""stage metrics carry their observation window (reality-gap normalisation)

Revision ID: f5b9d3e7a1c4
Revises: e4a8c2d6f0b3
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f5b9d3e7a1c4"
down_revision = "e4a8c2d6f0b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stage_metrics") as batch:
        batch.add_column(sa.Column("observed_days", sa.Float(), nullable=True))
        batch.add_column(sa.Column("period_start_ms", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("period_end_ms", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("bar_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stage_metrics") as batch:
        for c in ("bar_count", "period_end_ms", "period_start_ms", "observed_days"):
            batch.drop_column(c)
