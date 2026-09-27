"""index fitness_scores.as_of - dashboard ranking-stability and fitness-component queries

Revision ID: e5f8a2c4b7d3
Revises: c1d5e9a3f7b2

Purely additive: one new index, no column/table changes. The new /analytics observability
dashboard (app/analytics/dashboard_service.py) reconstructs "ranking as of a past date" by
filtering FitnessScore.as_of <= boundary across the whole population, and rolls up fitness
components per generation - both currently only indexed on agent_id, so either query would be
a full-table scan across the population's entire fitness history as it grows.
"""
from __future__ import annotations

from alembic import op

revision = "e5f8a2c4b7d3"
down_revision = "c1d5e9a3f7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_fitness_scores_as_of", "fitness_scores", ["as_of"])


def downgrade() -> None:
    op.drop_index("ix_fitness_scores_as_of", table_name="fitness_scores")
