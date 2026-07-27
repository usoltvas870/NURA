"""add canonical full-report PDF artifact and Telegram delivery

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None

_SHA256_HEX_CHECK = "length(artifact_sha256) = 64 AND " + " AND ".join(
    f"substr(artifact_sha256, {position}, 1) IN "
    "('0','1','2','3','4','5','6','7','8','9','a','b','c','d','e','f')"
    for position in range(1, 65)
)


def upgrade() -> None:
    op.add_column("reports", sa.Column("artifact_bytes", sa.LargeBinary()))
    op.add_column("reports", sa.Column("artifact_sha256", sa.String(length=64)))
    op.add_column("reports", sa.Column("artifact_size_bytes", sa.Integer()))
    op.add_column("reports", sa.Column("artifact_mime_type", sa.String(length=64)))
    op.add_column("reports", sa.Column("artifact_completed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "full_report_telegram_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_reason", sa.String(length=16), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_chat_id_snapshot", sa.BigInteger()),
        sa.Column("telegram_document_message_id", sa.BigInteger()), sa.Column("telegram_caption_message_id", sa.BigInteger()),
        sa.Column("telegram_file_id", sa.String(length=256)), sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_detail", sa.String(length=256)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "delivery_reason", "request_key", name="uq_full_report_delivery_request"),
        sa.CheckConstraint("delivery_reason IN ('automatic', 'manual')", name="ck_full_report_delivery_reason"),
        sa.CheckConstraint("status IN ('queued', 'sending', 'completed', 'failed', 'canceled')", name="ck_full_report_delivery_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_full_report_delivery_attempt_count"),
        sa.CheckConstraint("artifact_size_bytes > 0", name="ck_full_report_delivery_artifact_size"),
        sa.CheckConstraint(
            _SHA256_HEX_CHECK,
            name="ck_full_report_delivery_artifact_sha256",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND claimed_at IS NULL AND sent_at IS NULL AND failed_at IS NULL) OR "
            "(status = 'sending' AND claimed_at IS NOT NULL AND attempt_count > 0 AND sent_at IS NULL AND failed_at IS NULL) OR "
            "(status = 'completed' AND claimed_at IS NULL AND sent_at IS NOT NULL AND failed_at IS NULL "
            "AND telegram_document_message_id IS NOT NULL AND retryable = false) OR "
            "(status = 'failed' AND claimed_at IS NULL AND failed_at IS NOT NULL AND sent_at IS NULL "
            "AND error_code IS NOT NULL) OR "
            "(status = 'canceled' AND claimed_at IS NULL AND sent_at IS NULL AND retryable = false)",
            name="ck_full_report_delivery_state",
        ),
    )
    op.create_index(
        "uq_full_report_delivery_automatic_report",
        "full_report_telegram_deliveries",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("delivery_reason = 'automatic'"),
    )
    op.create_index("ix_full_report_delivery_report_id", "full_report_telegram_deliveries", ["report_id"])
    op.create_index("ix_full_report_delivery_order_id", "full_report_telegram_deliveries", ["order_id"])
    op.create_index("ix_full_report_delivery_user_id", "full_report_telegram_deliveries", ["user_id"])
    op.create_index("ix_full_report_delivery_status_claimed_at", "full_report_telegram_deliveries", ["status", "claimed_at"])
    op.create_index("ix_full_report_delivery_queued_at", "full_report_telegram_deliveries", ["queued_at"])
    op.create_index("ix_full_report_delivery_request_key", "full_report_telegram_deliveries", ["request_key"])


def downgrade() -> None:
    op.drop_index("ix_full_report_delivery_request_key", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_queued_at", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_status_claimed_at", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_user_id", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_order_id", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_report_id", table_name="full_report_telegram_deliveries")
    op.drop_index("uq_full_report_delivery_automatic_report", table_name="full_report_telegram_deliveries")
    op.drop_table("full_report_telegram_deliveries")
    for name in ("artifact_completed_at", "artifact_mime_type", "artifact_size_bytes", "artifact_sha256", "artifact_bytes"):
        op.drop_column("reports", name)
