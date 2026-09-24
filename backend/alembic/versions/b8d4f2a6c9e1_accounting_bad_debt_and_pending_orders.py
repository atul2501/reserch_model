"""bad-debt accounting, next-bar-open pending orders, per-bar position idempotency

Revision ID: b8d4f2a6c9e1
Revises: a7c3e5f1b2d4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b8d4f2a6c9e1"
down_revision = "a7c3e5f1b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("bad_debt", sa.Float(), nullable=False, server_default="0"))
    with op.batch_alter_table("trades") as batch:
        batch.add_column(sa.Column("bad_debt", sa.Float(), nullable=False, server_default="0"))
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("signal_candle_open_time", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("intent", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("positions") as batch:
        batch.add_column(sa.Column("pending_exit_reason", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("pending_exit_signal_time", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("last_processed_open_time", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("exit_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("positions") as batch:
        batch.drop_column("exit_attempts")
        batch.drop_column("last_processed_open_time")
        batch.drop_column("pending_exit_signal_time")
        batch.drop_column("pending_exit_reason")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("intent")
        batch.drop_column("signal_candle_open_time")
    with op.batch_alter_table("trades") as batch:
        batch.drop_column("bad_debt")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("bad_debt")
