"""drop redundant fitness_scores indexes; sync ix_trades_position into the model

Revision ID: f4669ea054ae
Revises: e5f8a2c4b7d3

Phase 2 forensic audit (2026-09-30) found the running schema had drifted from what
app.models declares. Evidence gathered before touching anything (pg_stat_user_indexes
on the live dev DB, restored production dump's schema, and each index's originating
migration):

  - ix_fitness_scores_asof (as_of) is an exact duplicate of ix_fitness_scores_as_of
    (as_of) - added by two migrations that didn't know about each other
    (d8f2b6a4c7e9 added the former, e5f8a2c4b7d3 later added the latter believing
    no as_of index existed yet). Real usage confirms it: 0 scans on
    ix_fitness_scores_asof vs 234 on ix_fitness_scores_as_of - the planner settled
    on the newer one; the older one is pure dead weight on every insert.
  - ix_fitness_scores_agent (agent_id) is redundant with the composite
    ix_fitness_scores_agent_asof (agent_id, as_of): a btree composite index already
    serves leading-column-only lookups. Same evidence: 0 scans vs 113.
  - ix_trades_position (position_id) IS real and used (30 scans) but was never
    declared in the Trade model's __table_args__ - left alone here; app/models/
    trading.py now declares it so the drift check stops wanting to remove it.

Purely index-level: no column, table, constraint or data changes.
"""
from __future__ import annotations

from alembic import op

revision = "f4669ea054ae"
down_revision = "e5f8a2c4b7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_fitness_scores_asof", table_name="fitness_scores")
    op.drop_index("ix_fitness_scores_agent", table_name="fitness_scores")


def downgrade() -> None:
    op.create_index("ix_fitness_scores_agent", "fitness_scores", ["agent_id"])
    op.create_index("ix_fitness_scores_asof", "fitness_scores", ["as_of"])
