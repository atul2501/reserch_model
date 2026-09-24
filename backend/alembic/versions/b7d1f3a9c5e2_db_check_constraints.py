"""database CHECK constraints + one-pending-entry-per-agent (impossible states cannot be written)

Revision ID: b7d1f3a9c5e2
Revises: a6c2e8f4b0d7

PRE-FLIGHT: before changing anything this migration counts, per constraint, the existing rows that would violate it and
ABORTS (no partial change) listing every offender. It never edits data on its own: an operator inspects and repairs the
rows, then re-runs `alembic upgrade head`.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b7d1f3a9c5e2"
down_revision = "a6c2e8f4b0d7"
branch_labels = None
depends_on = None

# FROZEN copy of app/models/constraints.py::CHECKS (tests/test_db_constraints.py asserts they are identical).
CHECKS = [
    # --- agents: an account cannot be negative, capital is positive, counters never go below zero
    ("agents", "ck_agents_balance_nonneg", "balance >= 0"),
    ("agents", "ck_agents_starting_positive", "starting_balance > 0"),
    ("agents", "ck_agents_bad_debt_nonneg", "bad_debt >= 0"),
    ("agents", "ck_agents_fees_nonneg", "fees_paid >= 0"),
    ("agents", "ck_agents_counters_nonneg", "trade_count >= 0 AND daily_trade_count >= 0"),
    # --- positions: impossible quantities / prices / margins, and an open position has no close time
    ("positions", "ck_positions_quantity_positive", "quantity > 0"),
    ("positions", "ck_positions_entry_price_positive", "entry_price > 0"),
    ("positions", "ck_positions_leverage_positive", "leverage > 0"),
    ("positions", "ck_positions_margin_nonneg", "initial_margin >= 0 AND maintenance_margin >= 0"),
    ("positions", "ck_positions_exit_attempts_nonneg", "exit_attempts >= 0"),
    ("positions", "ck_positions_open_closed_consistent",
     "(is_open AND closed_at IS NULL) OR (NOT is_open AND closed_at IS NOT NULL)"),
    # --- orders: quantities/notionals, and a valid state machine (a FILLED order HAS a fill; a PENDING one has none)
    ("orders", "ck_orders_quantity_nonneg", "quantity >= 0"),
    ("orders", "ck_orders_notional_nonneg",
     "(requested_notional IS NULL OR requested_notional >= 0) AND (approved_notional IS NULL OR approved_notional >= 0)"),
    ("orders", "ck_orders_leverage_positive", "leverage > 0"),
    ("orders", "ck_orders_fill_fields_nonneg", "(filled_quantity IS NULL OR filled_quantity >= 0) AND (fee IS NULL OR fee >= 0)"),
    ("orders", "ck_orders_filled_has_a_fill",
     "status NOT IN ('FILLED', 'PARTIALLY_FILLED') OR "
     "(filled_price IS NOT NULL AND filled_price > 0 AND filled_quantity IS NOT NULL AND filled_quantity > 0)"),
    ("orders", "ck_orders_pending_is_unfilled", "status <> 'PENDING' OR (filled_price IS NULL AND filled_at IS NULL)"),
    # --- trades
    ("trades", "ck_trades_quantity_positive", "quantity > 0"),
    ("trades", "ck_trades_prices_positive", "entry_price > 0 AND exit_price > 0"),
    ("trades", "ck_trades_fees_and_bad_debt_nonneg", "fees >= 0 AND bad_debt >= 0"),
    ("trades", "ck_trades_holding_nonneg", "holding_seconds >= 0"),
    ("funding_payments", "ck_funding_payments_notional_nonneg", "position_notional >= 0"),
    # --- market data
    ("market_candles", "ck_candles_ohlcv_sane", "high >= low AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0"),
    # --- worker
    ("worker_cycles", "ck_worker_cycles_status",
     "status IN ('STARTED', 'COMPLETED', 'FAILED', 'FAILED_PERMANENT', 'SKIPPED_CATCHUP')"),
    ("worker_cycles", "ck_worker_cycles_attempts_positive", "attempts >= 1"),
    ("worker_leases", "ck_worker_leases_epoch_nonneg", "epoch >= 0"),
    ("stage_metrics", "ck_stage_metrics_trade_count_nonneg", "trade_count >= 0"),
]


PENDING_INDEX = "uq_order_one_pending_entry_per_agent"


def _pending_predicate(is_pg: bool) -> str:
    return "status = 'PENDING' AND NOT reduce_only" if is_pg else "status = 'PENDING' AND reduce_only = 0"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    offenders: list[str] = []
    for table, name, condition in CHECKS:
        n = bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE NOT ({condition})")).scalar_one()
        if n:
            offenders.append(f"{name}: {n} row(s) in {table} violate ({condition})")
    dup = bind.execute(sa.text(
        f"SELECT count(*) FROM (SELECT agent_id FROM orders WHERE {_pending_predicate(is_pg)} "
        "GROUP BY agent_id HAVING count(*) > 1) d"
    )).scalar_one()
    if dup:
        offenders.append(f"{PENDING_INDEX}: {dup} agent(s) have more than one PENDING entry order")
    if offenders:
        raise RuntimeError(
            "refusing to add database constraints: existing rows violate them (nothing was changed). Repair these rows, "
            "then re-run the migration:\n  - " + "\n  - ".join(offenders)
        )

    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, name, condition in CHECKS:
        by_table.setdefault(table, []).append((name, condition))
    for table, items in by_table.items():
        with op.batch_alter_table(table) as batch:
            for name, condition in items:
                batch.create_check_constraint(name, sa.text(condition))

    op.create_index(
        PENDING_INDEX, "orders", ["agent_id"], unique=True,
        postgresql_where=sa.text(_pending_predicate(True)), sqlite_where=sa.text(_pending_predicate(False)),
    )


def downgrade() -> None:
    op.drop_index(PENDING_INDEX, table_name="orders")
    by_table: dict[str, list[str]] = {}
    for table, name, _ in CHECKS:
        by_table.setdefault(table, []).append(name)
    for table, names in by_table.items():
        with op.batch_alter_table(table) as batch:
            for name in names:
                batch.drop_constraint(name, type_="check")
