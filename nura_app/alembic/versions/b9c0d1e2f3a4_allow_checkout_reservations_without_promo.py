"""allow checkout reservations without a promo code

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from alembic import op
import sqlalchemy as sa


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("promo_reservations") as batch_op:
        batch_op.alter_column(
            "promo_code_id",
            existing_type=sa.UUID(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("promo_reservations") as batch_op:
        batch_op.alter_column(
            "promo_code_id",
            existing_type=sa.UUID(),
            nullable=False,
        )
