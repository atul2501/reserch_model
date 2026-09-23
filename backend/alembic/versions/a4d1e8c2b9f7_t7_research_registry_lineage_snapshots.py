"""research registry, OOS lockbox, strategy lineage, richer snapshots, immutability triggers

Revision ID: a4d1e8c2b9f7
Revises: f3c9a7b5d2e1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a4d1e8c2b9f7"
down_revision = "f3c9a7b5d2e1"
branch_labels = None
depends_on = None


def _ts_cols():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.create_table(
        "research_epochs",
        sa.Column("epoch_id", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("n_candles", sa.Integer(), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
        sa.Column("train_end_ms", sa.BigInteger(), nullable=False),
        sa.Column("validation_end_ms", sa.BigInteger(), nullable=False),
        sa.Column("oos_locked", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_ts_cols(),
        sa.UniqueConstraint("dataset_fingerprint", name="uq_epoch_fingerprint"),
    )
    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
        sa.Column("epoch_id", sa.String(64), nullable=True),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=True),
        sa.Column("train_period", sa.JSON(), nullable=False),
        sa.Column("validation_period", sa.JSON(), nullable=False),
        sa.Column("oos_period", sa.JSON(), nullable=False),
        sa.Column("strategy_version_id", sa.Uuid(), sa.ForeignKey("strategy_versions.id"), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
    )
    op.create_index("ix_experiments_kind_created", "experiments", ["kind", "created_at"])
    op.create_index("ix_experiments_version", "experiments", ["strategy_version_id"])
    op.create_table(
        "oos_evaluations",
        sa.Column("strategy_version_id", sa.Uuid(), sa.ForeignKey("strategy_versions.id"), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.String(64), nullable=False),
        sa.Column("oos_score", sa.Float(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        *_ts_cols(),
        sa.UniqueConstraint("strategy_version_id", "dataset_fingerprint", name="uq_oos_once_per_version_dataset"),
    )

    # Lineage: every existing strategy is its own founder (history preserved, nothing deleted).
    with op.batch_alter_table("strategies") as batch:
        batch.add_column(sa.Column("lineage_id", sa.Uuid(), nullable=True))
    op.create_index("ix_strategies_lineage_id", "strategies", ["lineage_id"])
    op.execute("UPDATE strategies SET lineage_id = id WHERE lineage_id IS NULL")

    with op.batch_alter_table("strategy_versions") as batch:
        batch.add_column(sa.Column("parent_b_strategy_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("experiment_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_sv_parent_b", "strategy_versions", ["parent_b_strategy_version_id"], ["id"])
    op.execute("UPDATE strategy_versions SET stage_entered_at = created_at WHERE stage_entered_at IS NULL")

    with op.batch_alter_table("agent_snapshots") as batch:
        batch.alter_column("software_version", existing_type=sa.String(32), type_=sa.String(64), existing_nullable=False)
        batch.alter_column("schema_version", existing_type=sa.String(32), type_=sa.String(64), existing_nullable=False)
        batch.add_column(sa.Column("strategy_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("strategy_version_number", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("experiment_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("dataset_fingerprint", sa.String(64), nullable=True))

    with op.batch_alter_table("fitness_scores") as batch:
        batch.add_column(sa.Column("correlation_penalty", sa.Float(), nullable=True))
        batch.add_column(sa.Column("expectancy_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("regime_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("adversarial_score", sa.Float(), nullable=True))

    if is_pg:
        op.execute("ALTER TYPE agent_status_enum ADD VALUE IF NOT EXISTS 'RETIRED'")

    # ---- DB-level immutability (created LAST: SQLite batch mode rebuilds tables and drops triggers) ----
    if is_pg:
        op.execute("""
            CREATE OR REPLACE FUNCTION forbid_immutable_change() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER agent_snapshots_immutable BEFORE UPDATE OR DELETE ON agent_snapshots
            FOR EACH ROW EXECUTE FUNCTION forbid_immutable_change();
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION forbid_dna_change() RETURNS trigger AS $$
            BEGIN
                IF NEW.dna::text IS DISTINCT FROM OLD.dna::text THEN
                    RAISE EXCEPTION 'strategy_versions.dna is immutable';
                END IF;
                RETURN NEW;
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER strategy_versions_dna_immutable BEFORE UPDATE ON strategy_versions
            FOR EACH ROW EXECUTE FUNCTION forbid_dna_change();
        """)
    else:
        op.execute("CREATE TRIGGER agent_snapshots_no_update BEFORE UPDATE ON agent_snapshots "
                   "BEGIN SELECT RAISE(ABORT, 'agent_snapshots rows are immutable'); END")
        op.execute("CREATE TRIGGER agent_snapshots_no_delete BEFORE DELETE ON agent_snapshots "
                   "BEGIN SELECT RAISE(ABORT, 'agent_snapshots rows are immutable'); END")
        op.execute("CREATE TRIGGER strategy_versions_dna_immutable BEFORE UPDATE OF dna ON strategy_versions "
                   "WHEN NEW.dna IS NOT OLD.dna BEGIN SELECT RAISE(ABORT, 'strategy_versions.dna is immutable'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS strategy_versions_dna_immutable ON strategy_versions")
        op.execute("DROP TRIGGER IF EXISTS agent_snapshots_immutable ON agent_snapshots")
        op.execute("DROP FUNCTION IF EXISTS forbid_dna_change()")
        op.execute("DROP FUNCTION IF EXISTS forbid_immutable_change()")
    else:
        op.execute("DROP TRIGGER IF EXISTS strategy_versions_dna_immutable")
        op.execute("DROP TRIGGER IF EXISTS agent_snapshots_no_delete")
        op.execute("DROP TRIGGER IF EXISTS agent_snapshots_no_update")

    with op.batch_alter_table("fitness_scores") as batch:
        for col in ("adversarial_score", "regime_score", "expectancy_score", "correlation_penalty"):
            batch.drop_column(col)
    with op.batch_alter_table("agent_snapshots") as batch:
        for col in ("dataset_fingerprint", "experiment_id", "strategy_version_number", "strategy_id"):
            batch.drop_column(col)
    with op.batch_alter_table("strategy_versions") as batch:
        batch.drop_constraint("fk_sv_parent_b", type_="foreignkey")
        for col in ("stage_entered_at", "experiment_id", "parent_b_strategy_version_id"):
            batch.drop_column(col)
    op.drop_index("ix_strategies_lineage_id", table_name="strategies")
    with op.batch_alter_table("strategies") as batch:
        batch.drop_column("lineage_id")
    op.drop_table("oos_evaluations")
    op.drop_index("ix_experiments_version", table_name="experiments")
    op.drop_index("ix_experiments_kind_created", table_name="experiments")
    op.drop_table("experiments")
    op.drop_table("research_epochs")
    # NOTE: PostgreSQL cannot drop a value from an enum type; 'RETIRED' stays in agent_status_enum (harmless).
