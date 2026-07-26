"""add durable daily Tarot draws

Revision ID: d7e8f9a0b1c2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d7e8f9a0b1c2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_tarot_draws",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("arcana_number", sa.Integer()),
        sa.Column("interpretation", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_detail", sa.String(length=256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "local_date", name="uq_daily_tarot_draws_user_local_date"),
        sa.CheckConstraint("status IN ('pending', 'generating', 'completed', 'failed')", name="ck_daily_tarot_draws_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_daily_tarot_draws_attempt_count"),
        sa.CheckConstraint(
            "arcana_number IS NULL OR arcana_number BETWEEN 1 AND 22",
            name="ck_daily_tarot_draws_arcana_number",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND interpretation IS NULL AND claimed_at IS NULL "
            "AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL "
            "AND error_detail IS NULL AND attempt_count = 0) OR "
            "(status = 'generating' AND arcana_number IS NOT NULL "
            "AND interpretation IS NULL AND claimed_at IS NOT NULL "
            "AND completed_at IS NULL AND failed_at IS NULL AND error_code IS NULL "
            "AND error_detail IS NULL AND attempt_count >= 1) OR "
            "(status = 'completed' AND arcana_number IS NOT NULL "
            "AND interpretation IS NOT NULL AND length(trim(interpretation)) > 0 "
            "AND claimed_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failed_at IS NULL AND error_code IS NULL AND error_detail IS NULL "
            "AND attempt_count >= 1) OR "
            "(status = 'failed' AND arcana_number IS NOT NULL "
            "AND interpretation IS NULL AND claimed_at IS NOT NULL "
            "AND completed_at IS NULL AND failed_at IS NOT NULL "
            "AND error_code IS NOT NULL AND attempt_count >= 1)",
            name="ck_daily_tarot_draws_state",
        ),
    )
    op.create_index(
        "ix_daily_tarot_draws_user_local_date",
        "daily_tarot_draws",
        ["user_id", "local_date"],
    )
    op.create_index(
        "ix_daily_tarot_draws_status_claimed_at",
        "daily_tarot_draws",
        ["status", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_tarot_draws_status_claimed_at", table_name="daily_tarot_draws")
    op.drop_index("ix_daily_tarot_draws_user_local_date", table_name="daily_tarot_draws")
    op.drop_table("daily_tarot_draws")
