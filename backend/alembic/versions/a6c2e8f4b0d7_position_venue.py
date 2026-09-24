"""positions carry the venue that opened them (paper/shadow must never mix)

Revision ID: a6c2e8f4b0d7
Revises: f5b9d3e7a1c4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a6c2e8f4b0d7"
down_revision = "f5b9d3e7a1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    venue = sa.Enum("PAPER", "SHADOW", "LIVE", name="execution_venue_enum", create_type=False)
    with op.batch_alter_table("positions") as batch:
        batch.add_column(sa.Column("venue", venue, nullable=False, server_default="PAPER"))


def downgrade() -> None:
    with op.batch_alter_table("positions") as batch:
        batch.drop_column("venue")
