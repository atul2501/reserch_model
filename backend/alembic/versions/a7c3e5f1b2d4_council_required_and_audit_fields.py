"""council fail-closed: explicit council_required per cycle, council completion/consensus audit fields

Revision ID: a7c3e5f1b2d4
Revises: c6f3a1b8d5e2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a7c3e5f1b2d4"
down_revision = "c6f3a1b8d5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("worker_cycles") as batch:
        batch.add_column(sa.Column("council_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("council_decisions") as batch:
        batch.add_column(sa.Column("council_completed_at", sa.Float(), nullable=True))
        batch.add_column(sa.Column("consensus_time_seconds", sa.Float(), nullable=True))
        batch.add_column(sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("council_decisions") as batch:
        batch.drop_column("failed_count")
        batch.drop_column("consensus_time_seconds")
        batch.drop_column("council_completed_at")
    with op.batch_alter_table("worker_cycles") as batch:
        batch.drop_column("council_required")
