"""add tarot fields to users and payment_type to payments

Revision ID: add_tarot_and_payment_type
Revises: e47590a5c5c1
Create Date: 2026-05-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_tarot_and_payment_type"
down_revision: Union[str, None] = "e47590a5c5c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "tarot_subscription",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "tarot_subscription_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "payments",
        sa.Column(
            "payment_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'subscription'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("payments", "payment_type")
    op.drop_column("users", "tarot_subscription_until")
    op.drop_column("users", "tarot_subscription")
