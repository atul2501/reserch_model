"""Database-level invariants (spec phase 26). Python validation alone is not enough: a bug, a migration script or a
manual UPDATE must not be able to write a negative balance, an impossible quantity or a FILLED order without a fill.

The list below is attached to the SQLAlchemy metadata (so `create_all` - and therefore the unit tests - enforce it) and a
frozen copy lives in the migration `b7d1f3a9c5e2_db_check_constraints`; tests/test_db_constraints.py asserts the two
stay identical. Conditions use portable SQL (booleans as bare/NOT, no dialect functions).
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, text

# (table, constraint name, condition that every row must satisfy)
CHECKS: list[tuple[str, str, str]] = [
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


def attach_constraints(metadata) -> None:
    """Idempotently attaches every CHECK and the extra partial unique indexes to `metadata`'s tables."""
    for table, name, condition in CHECKS:
        t = metadata.tables[table]
        if not any(getattr(c, "name", None) == name for c in t.constraints):
            t.append_constraint(CheckConstraint(text(condition), name=name))
    orders = metadata.tables["orders"]
    if not any(i.name == "uq_order_one_pending_entry_per_agent" for i in orders.indexes):
        Index(
            "uq_order_one_pending_entry_per_agent", orders.c.agent_id, unique=True,
            sqlite_where=text("status = 'PENDING' AND reduce_only = 0"),
            postgresql_where=text("status = 'PENDING' AND NOT reduce_only"),
        )
