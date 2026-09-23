"""decisions.market_context nullable (no longer duplicated per agent)

Revision ID: c6f3a1b8d5e2
Revises: b5e2f9a3c7d4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c6f3a1b8d5e2"
down_revision = "b5e2f9a3c7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.alter_column("market_context", existing_type=sa.JSON(), nullable=True)


def downgrade() -> None:
    # Historical rows may now hold NULL: restore an empty object before re-adding NOT NULL.
    op.execute(sa.text("UPDATE decisions SET market_context = '{}' WHERE market_context IS NULL"))
    with op.batch_alter_table("decisions") as batch:
        batch.alter_column("market_context", existing_type=sa.JSON(), nullable=False)
