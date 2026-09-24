"""frozen OOS holdout epochs, OOS provenance, immutability triggers

Revision ID: e4a8c2d6f0b3
Revises: d3f7b1c9e5a2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e4a8c2d6f0b3"
down_revision = "d3f7b1c9e5a2"
branch_labels = None
depends_on = None

_SEALED = ("start_ms", "end_ms", "n_candles", "dataset_fingerprint", "train_end_ms", "validation_end_ms",
           "oos_start_ms", "oos_end_ms", "oos_fingerprint", "symbol", "timeframe")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    with op.batch_alter_table("research_epochs") as batch:
        batch.add_column(sa.Column("oos_start_ms", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("oos_end_ms", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("oos_fingerprint", sa.String(length=64), nullable=True))
        # Legacy (rolling-window) epochs are NOT active holdouts: the pipeline seals a fresh, frozen epoch.
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("renewal_reason", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("supersedes_epoch_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("experiments") as batch:
        batch.add_column(sa.Column("engine_version", sa.String(length=32), nullable=False, server_default=""))
        batch.add_column(sa.Column("parameter_hash", sa.String(length=64), nullable=False, server_default=""))
    with op.batch_alter_table("oos_evaluations") as batch:
        batch.add_column(sa.Column("lineage_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("code_version", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("random_seed", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"))

    # ---- DB-level immutability (created LAST: SQLite batch mode rebuilds tables and drops triggers) ----
    if is_pg:
        sealed_check = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in _SEALED)
        op.execute(f"""
            CREATE OR REPLACE FUNCTION forbid_sealed_epoch_change() RETURNS trigger AS $$
            BEGIN
                IF {sealed_check} THEN
                    RAISE EXCEPTION 'research_epochs: the sealed OOS holdout cannot be edited';
                END IF;
                RETURN NEW;
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER research_epochs_sealed BEFORE UPDATE ON research_epochs "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_sealed_epoch_change()")
        op.execute("""
            CREATE OR REPLACE FUNCTION forbid_research_delete() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% rows can never be deleted', TG_TABLE_NAME;
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER research_epochs_no_delete BEFORE DELETE ON research_epochs "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_research_delete()")
        op.execute("CREATE TRIGGER experiments_no_delete BEFORE DELETE ON experiments "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_research_delete()")
        op.execute("""
            CREATE OR REPLACE FUNCTION forbid_oos_change() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'oos_evaluations rows are write-once';
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER oos_evaluations_write_once BEFORE UPDATE OR DELETE ON oos_evaluations "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_oos_change()")
    else:
        when = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _SEALED)
        op.execute(f"CREATE TRIGGER research_epochs_sealed BEFORE UPDATE ON research_epochs WHEN {when} "
                   "BEGIN SELECT RAISE(ABORT, 'research_epochs: the sealed OOS holdout cannot be edited'); END")
        op.execute("CREATE TRIGGER research_epochs_no_delete BEFORE DELETE ON research_epochs "
                   "BEGIN SELECT RAISE(ABORT, 'research_epochs rows can never be deleted'); END")
        op.execute("CREATE TRIGGER experiments_no_delete BEFORE DELETE ON experiments "
                   "BEGIN SELECT RAISE(ABORT, 'experiments rows can never be deleted'); END")
        op.execute("CREATE TRIGGER oos_evaluations_no_update BEFORE UPDATE ON oos_evaluations "
                   "BEGIN SELECT RAISE(ABORT, 'oos_evaluations rows are write-once'); END")
        op.execute("CREATE TRIGGER oos_evaluations_no_delete BEFORE DELETE ON oos_evaluations "
                   "BEGIN SELECT RAISE(ABORT, 'oos_evaluations rows are write-once'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for t, tbl in (("research_epochs_sealed", "research_epochs"), ("research_epochs_no_delete", "research_epochs"),
                       ("experiments_no_delete", "experiments"), ("oos_evaluations_write_once", "oos_evaluations")):
            op.execute(f"DROP TRIGGER IF EXISTS {t} ON {tbl}")
        for fn in ("forbid_sealed_epoch_change", "forbid_research_delete", "forbid_oos_change"):
            op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
    else:
        for t in ("research_epochs_sealed", "research_epochs_no_delete", "experiments_no_delete",
                  "oos_evaluations_no_update", "oos_evaluations_no_delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {t}")
    with op.batch_alter_table("oos_evaluations") as batch:
        for c in ("provenance", "random_seed", "code_version", "lineage_id"):
            batch.drop_column(c)
    with op.batch_alter_table("experiments") as batch:
        batch.drop_column("parameter_hash")
        batch.drop_column("engine_version")
    with op.batch_alter_table("research_epochs") as batch:
        for c in ("superseded_at", "supersedes_epoch_id", "renewal_reason", "sealed_at", "active", "oos_fingerprint",
                  "oos_end_ms", "oos_start_ms"):
            batch.drop_column(c)
