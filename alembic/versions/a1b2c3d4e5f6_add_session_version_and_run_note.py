"""add session_version to users and note to runs

Revision ID: a1b2c3d4e5f6
Revises: d041bbaef980
Create Date: 2026-10-09 02:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = ('d041bbaef980', 'f9024451f825')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add session_version (int, default 1, not null) to users,
    and note (text, nullable) to runs."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('session_version', sa.Integer(), nullable=False, server_default='1')
        )

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('note', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Remove session_version from users and note from runs."""
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_column('note')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_version')
