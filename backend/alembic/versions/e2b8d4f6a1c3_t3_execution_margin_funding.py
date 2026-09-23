"""paper execution v2: position cost basis, funding payments, order fill quality, one-open-position index

Revision ID: e2b8d4f6a1c3
Revises: d1a7c9e0b2f1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e2b8d4f6a1c3"
down_revision = "d1a7c9e0b2f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("positions") as batch:
        batch.add_column(sa.Column("entry_order_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("entry_fee", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("entry_slippage_cost", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("funding_accrued", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("liquidation_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("entry_candle_open_time", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("entry_regime", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("trailing_active", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_positions_entry_order", "orders", ["entry_order_id"], ["id"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("filled_quantity", sa.Float(), nullable=True))
        batch.add_column(sa.Column("filled_price", sa.Float(), nullable=True))
        batch.add_column(sa.Column("fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("slippage_cost", sa.Float(), nullable=True))
        batch.add_column(sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("order_kind", sa.String(length=16), nullable=False, server_default="market"))

    op.create_table(
        "funding_payments",
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("position_id", sa.Uuid(), sa.ForeignKey("positions.id"), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("funding_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("funding_rate", sa.Float(), nullable=False),
        sa.Column("position_notional", sa.Float(), nullable=False),
        sa.Column("payment", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("position_id", "funding_time_ms", name="uq_funding_payment_position_time"),
    )
    op.create_index("ix_funding_payments_agent", "funding_payments", ["agent_id"])

    # Historical data may contain >1 open position for one agent (the old code
    # only guarded this in Python). Close the older duplicates' bookkeeping flag
    # deterministically BEFORE adding the unique index — keep the newest open one.
    bind = op.get_bind()
    dup_agents = [r[0] for r in bind.execute(sa.text(
        "SELECT agent_id FROM positions WHERE is_open = :t GROUP BY agent_id HAVING COUNT(*) > 1"
    ), {"t": True}).fetchall()]
    for agent_id in dup_agents:
        rows = bind.execute(sa.text(
            "SELECT id FROM positions WHERE agent_id = :a AND is_open = :t ORDER BY opened_at DESC"
        ), {"a": agent_id, "t": True}).fetchall()
        for (pid,) in rows[1:]:
            bind.execute(sa.text("UPDATE positions SET is_open = :f WHERE id = :i"), {"f": False, "i": pid})

    op.create_index(
        "uq_position_one_open_per_agent", "positions", ["agent_id"], unique=True,
        sqlite_where=sa.text("is_open = 1"), postgresql_where=sa.text("is_open"),
    )


def downgrade() -> None:
    op.drop_index("uq_position_one_open_per_agent", table_name="positions")
    op.drop_index("ix_funding_payments_agent", table_name="funding_payments")
    op.drop_table("funding_payments")
    with op.batch_alter_table("orders") as batch:
        for col in ("order_kind", "reduce_only", "slippage_cost", "fee", "filled_price", "filled_quantity"):
            batch.drop_column(col)
    with op.batch_alter_table("positions") as batch:
        batch.drop_constraint("fk_positions_entry_order", type_="foreignkey")
        for col in ("trailing_active", "entry_regime", "entry_candle_open_time", "liquidation_price",
                    "funding_accrued", "entry_slippage_cost", "entry_fee", "entry_order_id"):
            batch.drop_column(col)
