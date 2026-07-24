"""add telegram mini report delivery

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_report_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mini_report_generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="mini_initial"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("text_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("document_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("text_message_ids", postgresql.JSONB()),
        sa.Column("document_message_id", sa.BigInteger()),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mini_report_generation_id"], ["mini_report_generations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mini_report_generation_id", "user_id", "purpose", name="uq_telegram_report_deliveries_generation_user_purpose"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'partially_delivered', 'delivered', 'failed')",
            name="ck_telegram_report_deliveries_status",
        ),
        sa.CheckConstraint(
            "text_status IN ('pending', 'sent')",
            name="ck_telegram_report_deliveries_text_status",
        ),
        sa.CheckConstraint(
            "document_status IN ('pending', 'sent')",
            name="ck_telegram_report_deliveries_document_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_report_deliveries_attempt_count",
        ),
    )
    op.create_index("ix_telegram_report_deliveries_status", "telegram_report_deliveries", ["status"])
    op.create_index(
        "ix_telegram_report_deliveries_status_claimed_at",
        "telegram_report_deliveries",
        ["status", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_report_deliveries_status_claimed_at",
        table_name="telegram_report_deliveries",
    )
    op.drop_index("ix_telegram_report_deliveries_status", table_name="telegram_report_deliveries")
    op.drop_table("telegram_report_deliveries")
