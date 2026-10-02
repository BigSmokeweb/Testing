"""add sites table

Revision ID: d100c986ae3d
Revises: 6c68ae18edbc
Create Date: 2026-10-02 17:21:00.413812

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd100c986ae3d'
down_revision: Union[str, Sequence[str], None] = '6c68ae18edbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('verify_token', sa.String(), nullable=False),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sites_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sites_verify_token'), ['verify_token'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('sites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sites_verify_token'))
        batch_op.drop_index(batch_op.f('ix_sites_user_id'))
    op.drop_table('sites')
