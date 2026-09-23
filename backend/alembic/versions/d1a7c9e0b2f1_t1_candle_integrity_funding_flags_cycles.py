"""candle integrity: funding_rates, system_flags, worker cycle status, lease fencing

Revision ID: d1a7c9e0b2f1
Revises: c2f0a1d4e901
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d1a7c9e0b2f1"
down_revision = "c2f0a1d4e901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funding_rates",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("premium", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "time_ms", name="uq_funding_symbol_time"),
    )
    op.create_index("ix_funding_symbol_time", "funding_rates", ["symbol", "time_ms"])

    op.create_table(
        "system_flags",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("set_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("worker_leases") as batch:
        batch.add_column(sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("heartbeat_at", sa.Float(), nullable=True))

    with op.batch_alter_table("worker_cycles") as batch:
        # Historical rows: `completed=true` rows become COMPLETED, everything else STARTED.
        batch.add_column(sa.Column("status", sa.String(length=24), nullable=False, server_default="STARTED"))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("council_status", sa.String(length=24), nullable=True))
        batch.add_column(sa.Column("agents_processed", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trading_halt_reason", sa.String(length=256), nullable=True))
    op.execute("UPDATE worker_cycles SET status = 'COMPLETED' WHERE completed = 1 OR completed = true"
               if op.get_bind().dialect.name != "postgresql"
               else "UPDATE worker_cycles SET status = 'COMPLETED' WHERE completed IS TRUE")


def downgrade() -> None:
    with op.batch_alter_table("worker_cycles") as batch:
        batch.drop_column("trading_halt_reason")
        batch.drop_column("agents_processed")
        batch.drop_column("council_status")
        batch.drop_column("error")
        batch.drop_column("attempts")
        batch.drop_column("status")
    with op.batch_alter_table("worker_leases") as batch:
        batch.drop_column("heartbeat_at")
        batch.drop_column("epoch")
    op.drop_table("system_flags")
    op.drop_index("ix_funding_symbol_time", table_name="funding_rates")
    op.drop_table("funding_rates")
