"""link payments to promo codes

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("amount_kopecks", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("promo_consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("promo_reserved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "promo_codes",
        sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_payments_promo_code_id_promo_codes",
        "payments",
        "promo_codes",
        ["promo_code_id"],
        ["id"],
    )
    op.create_index("ix_payments_promo_code_id", "payments", ["promo_code_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_promo_code_id", table_name="payments")
    op.drop_constraint(
        "fk_payments_promo_code_id_promo_codes",
        "payments",
        type_="foreignkey",
    )
    op.drop_column("payments", "promo_consumed_at")
    op.drop_column("payments", "promo_reserved_at")
    op.drop_column("payments", "promo_code_id")
    op.drop_column("payments", "amount_kopecks")
    op.drop_column("promo_codes", "reserved_count")
