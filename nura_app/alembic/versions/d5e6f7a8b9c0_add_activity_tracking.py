"""add_activity_tracking

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_last_activity_at",
        "users",
        ["last_activity_at"],
    )
    op.add_column(
        "users",
        sa.Column(
            "account_status",
            sa.String(20),
            server_default="active",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE users SET last_activity_at = created_at WHERE last_activity_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "account_status")
    op.drop_index("ix_users_last_activity_at", table_name="users")
    op.drop_column("users", "last_activity_at")
