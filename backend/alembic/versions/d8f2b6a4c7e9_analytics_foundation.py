"""analytics foundation: trade_analytics, strategy_regime_matrix, fitness_forward_performance + additive indexes

Revision ID: d8f2b6a4c7e9
Revises: b7d1f3a9c5e2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d8f2b6a4c7e9"
down_revision = "b7d1f3a9c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_analytics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trade_id", sa.Uuid(), sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("family", sa.String(16), nullable=True),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=True),
        sa.Column("regime", sa.String(32), nullable=True),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("signal_bar_open_time_ms", sa.BigInteger(), nullable=True),
        sa.Column("signal_close_time_ms", sa.BigInteger(), nullable=True),
        sa.Column("entry_delay_seconds", sa.Float(), nullable=True),
        sa.Column("expected_entry_price", sa.Float(), nullable=True),
        sa.Column("entry_slippage_bps", sa.Float(), nullable=True),
        sa.Column("signal_confidence", sa.Float(), nullable=True),
        sa.Column("setup_strength", sa.Float(), nullable=True),
        sa.Column("council_bias", sa.String(16), nullable=True),
        sa.Column("council_confidence", sa.Float(), nullable=True),
        sa.Column("council_status", sa.String(16), nullable=True),
        sa.Column("risk_amount", sa.Float(), nullable=True),
        sa.Column("planned_risk_amount", sa.Float(), nullable=True),
        sa.Column("expected_r", sa.Float(), nullable=True),
        sa.Column("planned_stop_bps", sa.Float(), nullable=True),
        sa.Column("planned_tp_bps", sa.Float(), nullable=True),
        sa.Column("leverage", sa.Float(), nullable=False),
        sa.Column("position_notional", sa.Float(), nullable=False),
        sa.Column("mfe_price", sa.Float(), nullable=False),
        sa.Column("mae_price", sa.Float(), nullable=False),
        sa.Column("mfe_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("mae_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("time_to_mfe_seconds", sa.Integer(), nullable=False),
        sa.Column("time_to_mae_seconds", sa.Integer(), nullable=False),
        sa.Column("mfe_r", sa.Float(), nullable=True),
        sa.Column("mae_r", sa.Float(), nullable=True),
        sa.Column("mfe_bps", sa.Float(), nullable=False),
        sa.Column("mae_bps", sa.Float(), nullable=False),
        sa.Column("max_unrealized_profit", sa.Float(), nullable=False),
        sa.Column("max_unrealized_loss", sa.Float(), nullable=False),
        sa.Column("mfe_before_mae", sa.Boolean(), nullable=True),
        sa.Column("exit_delay_seconds", sa.Float(), nullable=True),
        sa.Column("exit_slippage_bps", sa.Float(), nullable=True),
        sa.Column("post_exit_mfe_bps_30", sa.Float(), nullable=True),
        sa.Column("post_exit_mae_bps_30", sa.Float(), nullable=True),
        sa.Column("left_on_table_r", sa.Float(), nullable=True),
        sa.Column("trade_quality_class", sa.String(32), nullable=False),
        sa.Column("regime_episode_id", sa.Integer(), nullable=True),
        sa.Column("peak_crosscheck_ok", sa.Boolean(), nullable=True),
        sa.Column("trough_crosscheck_ok", sa.Boolean(), nullable=True),
        sa.Column("computation_version", sa.String(16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_trade_analytics_trade", "trade_analytics", ["trade_id"], unique=True)
    op.create_index("ix_trade_analytics_agent", "trade_analytics", ["agent_id"])
    op.create_index("ix_trade_analytics_family_regime", "trade_analytics", ["family", "regime"])
    op.create_index("ix_trade_analytics_regime", "trade_analytics", ["regime"])
    op.create_index("ix_trade_analytics_version", "trade_analytics", ["strategy_version_id"])
    op.create_index("ix_trade_analytics_class", "trade_analytics", ["trade_quality_class"])

    op.create_table(
        "strategy_regime_matrix",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("window_key", sa.String(16), nullable=False),
        sa.Column("granularity", sa.String(16), nullable=False),
        sa.Column("dim_id", sa.String(64), nullable=False),
        sa.Column("dim_label", sa.String(64), nullable=True),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("win_count", sa.Integer(), nullable=False),
        sa.Column("loss_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("win_rate_ci_low", sa.Float(), nullable=True),
        sa.Column("win_rate_ci_high", sa.Float(), nullable=True),
        sa.Column("gross_pnl", sa.Float(), nullable=False),
        sa.Column("fees", sa.Float(), nullable=False),
        sa.Column("funding", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("avg_trade_pnl", sa.Float(), nullable=True),
        sa.Column("expectancy", sa.Float(), nullable=True),
        sa.Column("expectancy_ci_low", sa.Float(), nullable=True),
        sa.Column("expectancy_ci_high", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("avg_winner", sa.Float(), nullable=True),
        sa.Column("avg_loser", sa.Float(), nullable=True),
        sa.Column("avg_holding_seconds", sa.Float(), nullable=True),
        sa.Column("max_drawdown_currency", sa.Float(), nullable=False),
        sa.Column("mfe_r_mean", sa.Float(), nullable=True),
        sa.Column("mfe_r_median", sa.Float(), nullable=True),
        sa.Column("mfe_r_p90", sa.Float(), nullable=True),
        sa.Column("mae_r_mean", sa.Float(), nullable=True),
        sa.Column("mae_r_median", sa.Float(), nullable=True),
        sa.Column("mae_r_p90", sa.Float(), nullable=True),
        sa.Column("tp_first_pct", sa.Float(), nullable=True),
        sa.Column("sl_first_pct", sa.Float(), nullable=True),
        sa.Column("reversal_pct", sa.Float(), nullable=True),
        sa.Column("cost_eaten_pct", sa.Float(), nullable=True),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.Column("evidence_state", sa.String(12), nullable=False),
        sa.Column("under_sampled", sa.Boolean(), nullable=False),
        sa.Column("gross_edge", sa.Boolean(), nullable=False),
        sa.Column("net_edge", sa.Boolean(), nullable=False),
        sa.Column("computation_version", sa.String(16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_srm_cell", "strategy_regime_matrix", ["window_key", "granularity", "dim_id", "regime"], unique=True)
    op.create_index("ix_srm_dim", "strategy_regime_matrix", ["granularity", "dim_id"])

    op.create_table(
        "fitness_forward_performance",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("snapshot_source", sa.String(12), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fitness_at_t", sa.Float(), nullable=False),
        sa.Column("fitness_components_at_t", sa.JSON(), nullable=False),
        sa.Column("horizon_minutes", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_planned", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_actual", sa.DateTime(timezone=True), nullable=False),
        sa.Column("censor_reason", sa.String(24), nullable=False),
        sa.Column("window_coverage", sa.Float(), nullable=False),
        sa.Column("future_trade_count", sa.Integer(), nullable=False),
        sa.Column("future_net_pnl", sa.Float(), nullable=True),
        sa.Column("future_net_bps", sa.Float(), nullable=True),
        sa.Column("future_expectancy", sa.Float(), nullable=True),
        sa.Column("future_win_rate", sa.Float(), nullable=True),
        sa.Column("future_max_drawdown_currency", sa.Float(), nullable=True),
        sa.Column("computation_version", sa.String(16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_ffp_agent_asof_horizon", "fitness_forward_performance",
                    ["agent_id", "as_of", "horizon_minutes"], unique=True)
    op.create_index("ix_ffp_asof_horizon", "fitness_forward_performance", ["as_of", "horizon_minutes"])

    # ---- additive read-path indexes on RAW tables (no data change) -------- #
    # The analytics join trades -> positions for the risk plan and the persisted extremes.
    op.create_index("ix_trades_position", "trades", ["position_id"])
    # Fitness cohort scans (dimension 3) filter/sort by as_of.
    op.create_index("ix_fitness_scores_agent_asof", "fitness_scores", ["agent_id", "as_of"])
    op.create_index("ix_fitness_scores_asof", "fitness_scores", ["as_of"])

    # ---- DB-level immutability for the evidence table (created LAST: SQLite
    # ---- batch mode rebuilds tables and drops triggers) -------------------- #
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION forbid_ffp_change() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'fitness_forward_performance rows are write-once evidence';
            END; $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER fitness_forward_performance_write_once "
                   "BEFORE UPDATE OR DELETE ON fitness_forward_performance "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_ffp_change()")
    else:
        op.execute("CREATE TRIGGER fitness_forward_performance_no_update BEFORE UPDATE ON fitness_forward_performance "
                   "BEGIN SELECT RAISE(ABORT, 'fitness_forward_performance rows are write-once evidence'); END")
        op.execute("CREATE TRIGGER fitness_forward_performance_no_delete BEFORE DELETE ON fitness_forward_performance "
                   "BEGIN SELECT RAISE(ABORT, 'fitness_forward_performance rows are write-once evidence'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS fitness_forward_performance_write_once ON fitness_forward_performance")
        op.execute("DROP FUNCTION IF EXISTS forbid_ffp_change()")
    else:
        op.execute("DROP TRIGGER IF EXISTS fitness_forward_performance_no_update")
        op.execute("DROP TRIGGER IF EXISTS fitness_forward_performance_no_delete")
    op.drop_index("ix_fitness_scores_asof", "fitness_scores")
    op.drop_index("ix_fitness_scores_agent_asof", "fitness_scores")
    op.drop_index("ix_trades_position", "trades")
    op.drop_table("fitness_forward_performance")
    op.drop_table("strategy_regime_matrix")
    op.drop_table("trade_analytics")