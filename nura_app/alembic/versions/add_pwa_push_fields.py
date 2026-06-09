"""add pwa push fields

Revision ID: a1b2c3d4e5f6
Revises: 5a8cac04bf5e
Create Date: 2026-06-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5a8cac04bf5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('has_pwa_push', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('users', sa.Column('push_endpoint', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('push_p256dh', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('push_auth', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'push_auth')
    op.drop_column('users', 'push_p256dh')
    op.drop_column('users', 'push_endpoint')
    op.drop_column('users', 'has_pwa_push')
