"""runtime safety, cycle idempotency, and execution accounting

Revision ID: c2f0a1d4e901
Revises: b9bae753da23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c2f0a1d4e901"
down_revision = "b9bae753da23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable execution fields preserve all historical orders/positions.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("daily_trade_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_trade_time", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("requested_notional", sa.Float(), nullable=True))
        batch.add_column(sa.Column("approved_notional", sa.Float(), nullable=True))
        batch.add_column(sa.Column("initial_margin", sa.Float(), nullable=True))
        batch.add_column(sa.Column("risk_amount", sa.Float(), nullable=True))
    with op.batch_alter_table("positions") as batch:
        batch.add_column(sa.Column("initial_margin", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("maintenance_margin", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("peak_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("trough_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("last_funding_time", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("council_bias", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("council_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("final_signal", sa.String(length=16), nullable=True))
        batch.create_unique_constraint("uq_decision_agent_candle", ["agent_id", "market_candle_open_time"])
    op.create_index("ix_decision_candle", "decisions", ["market_candle_open_time"])
    op.create_index("ix_orders_agent_created", "orders", ["agent_id", "created_at"])
    op.create_index("ix_positions_agent_open", "positions", ["agent_id", "is_open"])
    op.create_table(
        "worker_leases",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "worker_cycles",
        sa.Column("cycle_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("candle_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("cycle_started_at", sa.Float(), nullable=False),
        sa.Column("cycle_completed_at", sa.Float(), nullable=True),
        sa.Column("cycle_latency_seconds", sa.Float(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_worker_cycles_candle_timestamp", "worker_cycles", ["candle_timestamp"])


def downgrade() -> None:
    op.drop_index("ix_worker_cycles_candle_timestamp", table_name="worker_cycles")
    op.drop_table("worker_cycles")
    op.drop_table("worker_leases")
    op.drop_index("ix_positions_agent_open", table_name="positions")
    op.drop_index("ix_orders_agent_created", table_name="orders")
    op.drop_index("ix_decision_candle", table_name="decisions")
    with op.batch_alter_table("decisions") as batch:
        batch.drop_constraint("uq_decision_agent_candle", type_="unique")
        batch.drop_column("final_signal")
        batch.drop_column("council_confidence")
        batch.drop_column("council_bias")
    with op.batch_alter_table("positions") as batch:
        batch.drop_column("last_funding_time")
        batch.drop_column("trough_price")
        batch.drop_column("peak_price")
        batch.drop_column("maintenance_margin")
        batch.drop_column("initial_margin")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("risk_amount")
        batch.drop_column("initial_margin")
        batch.drop_column("approved_notional")
        batch.drop_column("requested_notional")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("cooldown_until")
        batch.drop_column("last_trade_time")
        batch.drop_column("daily_trade_count")
