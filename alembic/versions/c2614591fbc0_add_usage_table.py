"""add usage table

Revision ID: c2614591fbc0
Revises: d100c986ae3d
Create Date: 2026-10-02 17:35:14.003482

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2614591fbc0'
down_revision: Union[str, Sequence[str], None] = 'd100c986ae3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(), nullable=False),
        sa.Column('runs_count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usage_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_date'), ['date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usage_date'))
        batch_op.drop_index(batch_op.f('ix_usage_user_id'))
    op.drop_table('usage')
