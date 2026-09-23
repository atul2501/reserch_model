"""system_status: runtime snapshot published by the worker for the API/dashboard

Revision ID: b5e2f9a3c7d4
Revises: a4d1e8c2b9f7
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b5e2f9a3c7d4"
down_revision = "a4d1e8c2b9f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_status",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_status")
