"""widen fitness_forward_performance.snapshot_source to fit its own documented values

Revision ID: c1d5e9a3f7b2
Revises: d8f2b6a4c7e9

The column was declared VARCHAR(12), but its own comment documents two legal
values: "recorded" (8 chars) and "reconstructed" (13 chars) - the second does
not fit. Invisible on SQLite (no VARCHAR length enforcement); a real
INSERT-time failure on Postgres, caught by a SQLite -> Postgres migration
dry run (scripts/migrate_sqlite_to_postgres.py) once real "reconstructed"
rows (written by app/analytics/analytics_store.py's fitness-forward refresh)
were copied across.

SQLite is skipped deliberately, not just left alone by inaction: SQLite has no
native ALTER COLUMN, so alembic's batch mode implements one by rebuilding the
table (create new, copy rows, drop old, rename). That would silently drop this
table's hand-written write-once triggers (fitness_forward_performance_no_update
/_no_delete, added in d8f2b6a4c7e9) - confirmed by tests/test_analytics_migration.py
failing exactly that way when this migration first ran unconditional batch mode
on SQLite. Since SQLite never enforced the length in the first place, skipping it
there changes nothing observable and keeps the triggers intact; the real fix
lands on Postgres, which supports an in-place ALTER COLUMN TYPE with no rebuild.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c1d5e9a3f7b2"
down_revision = "d8f2b6a4c7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    with op.batch_alter_table("fitness_forward_performance") as batch:
        batch.alter_column("snapshot_source", existing_type=sa.String(length=12), type_=sa.String(length=16), existing_nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    with op.batch_alter_table("fitness_forward_performance") as batch:
        batch.alter_column("snapshot_source", existing_type=sa.String(length=16), type_=sa.String(length=12), existing_nullable=False)
