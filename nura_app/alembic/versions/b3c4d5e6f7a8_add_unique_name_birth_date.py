"""add unique constraint on user name and birth_date

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_user_name_birth_date",
        "users",
        ["name", "birth_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_name_birth_date", "users", type_="unique")
