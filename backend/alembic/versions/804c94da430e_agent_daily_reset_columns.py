"""agent daily reset columns

Revision ID: 804c94da430e
Revises: 961c3ba1bb6b
Create Date: 2026-09-21 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '804c94da430e'
down_revision: Union[str, None] = '961c3ba1bb6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('day_start_equity', sa.Float(), nullable=True))
    op.add_column('agents', sa.Column('day_start_date', sa.Date(), nullable=True))
    op.execute("UPDATE agents SET day_start_equity = equity, day_start_date = CURRENT_DATE")
    op.alter_column('agents', 'day_start_equity', nullable=False)
    op.alter_column('agents', 'day_start_date', nullable=False)


def downgrade() -> None:
    op.drop_column('agents', 'day_start_date')
    op.drop_column('agents', 'day_start_equity')
