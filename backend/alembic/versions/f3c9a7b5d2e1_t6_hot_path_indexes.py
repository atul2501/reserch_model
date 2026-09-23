"""hot-path indexes (agent_id, generation, status, candle time, strategy, created_at)

Revision ID: f3c9a7b5d2e1
Revises: e2b8d4f6a1c3
"""
from __future__ import annotations

from alembic import op

revision = "f3c9a7b5d2e1"
down_revision = "e2b8d4f6a1c3"
branch_labels = None
depends_on = None

_INDEXES = [
    ("ix_agents_generation_status", "agents", ["generation", "status"]),
    ("ix_agents_strategy_version", "agents", ["strategy_version_id"]),
    ("ix_fitness_scores_agent", "fitness_scores", ["agent_id"]),
    ("ix_performance_metrics_agent", "performance_metrics", ["agent_id"]),
    ("ix_stage_metrics_version_stage", "stage_metrics", ["strategy_version_id", "stage"]),
    ("ix_evolution_events_created", "evolution_events", ["created_at"]),
    ("ix_council_decisions_candle", "council_decisions", ["market_candle_open_time"]),
    ("ix_agent_corr_a", "agent_correlations", ["agent_id_a"]),
    ("ix_agent_corr_b", "agent_correlations", ["agent_id_b"]),
    ("ix_trades_agent_closed", "trades", ["agent_id", "closed_at"]),
    ("ix_trades_closed_at", "trades", ["closed_at"]),
    ("ix_trades_stage", "trades", ["stage"]),
    ("ix_decisions_strategy_version", "decisions", ["strategy_version_id"]),
    ("ix_decisions_created_at", "decisions", ["created_at"]),
    ("ix_orders_status", "orders", ["status"]),
    ("ix_orders_decision", "orders", ["decision_id"]),
    ("ix_strategy_versions_generation", "strategy_versions", ["generation"]),
    ("ix_strategy_versions_stage", "strategy_versions", ["stage"]),
    ("ix_strategy_versions_champion_status", "strategy_versions", ["champion_status"]),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
