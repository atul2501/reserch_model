"""adversarial reports carry their reproducibility provenance

Revision ID: c9e5a3b7d1f2
Revises: b8d4f2a6c9e1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c9e5a3b7d1f2"
down_revision = "b8d4f2a6c9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("adversarial_test_reports") as batch:
        batch.add_column(sa.Column("experiment_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("random_seed", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("scenario_config", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("dataset_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("code_version", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("adversarial_test_reports") as batch:
        batch.drop_column("code_version")
        batch.drop_column("dataset_fingerprint")
        batch.drop_column("scenario_config")
        batch.drop_column("random_seed")
        batch.drop_column("experiment_id")
