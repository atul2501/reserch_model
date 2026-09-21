"""stage metrics

Revision ID: 1b91ce59e177
Revises: 804c94da430e
Create Date: 2026-09-21 00:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '1b91ce59e177'
down_revision: Union[str, None] = '804c94da430e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# strategy_stage_enum was already created by the initial schema migration
# (backing StrategyVersion.stage) — reuse it here without re-issuing CREATE TYPE.
_strategy_stage_enum = postgresql.ENUM(
    'RESEARCH', 'BACKTEST', 'WALK_FORWARD', 'OUT_OF_SAMPLE', 'PAPER', 'SHADOW',
    'SMALL_LIVE', 'APPROVED_LIVE', 'REJECTED',
    name='strategy_stage_enum',
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        'stage_metrics',
        sa.Column('strategy_version_id', sa.UUID(), nullable=False),
        sa.Column('stage', _strategy_stage_enum, nullable=False),
        sa.Column('net_return_pct', sa.Float(), nullable=False),
        sa.Column('max_drawdown_pct', sa.Float(), nullable=False),
        sa.Column('win_rate', sa.Float(), nullable=True),
        sa.Column('profit_factor', sa.Float(), nullable=True),
        sa.Column('trade_count', sa.Integer(), nullable=False),
        sa.Column('oos_score', sa.Float(), nullable=True),
        sa.Column('walk_forward_consistency', sa.Float(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['strategy_version_id'], ['strategy_versions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_stage_metrics_version_stage_computed_at',
        'stage_metrics',
        ['strategy_version_id', 'stage', 'computed_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_stage_metrics_version_stage_computed_at', table_name='stage_metrics')
    op.drop_table('stage_metrics')
