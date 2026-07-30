"""add durable text progress to full-report Telegram delivery

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "full_report_telegram_deliveries",
        sa.Column("delivery_format_version", sa.String(length=32), nullable=False, server_default="full-text-pdf-v1"),
    )
    op.add_column("full_report_telegram_deliveries", sa.Column("text_payload_sha256", sa.String(length=64)))
    op.add_column("full_report_telegram_deliveries", sa.Column("text_chunks_snapshot", postgresql.JSONB()))
    op.add_column(
        "full_report_telegram_deliveries",
        sa.Column("total_text_chunks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("full_report_telegram_deliveries", sa.Column("text_message_ids", postgresql.JSONB()))
    op.add_column(
        "full_report_telegram_deliveries",
        sa.Column("text_status", sa.String(length=24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "full_report_telegram_deliveries",
        sa.Column("document_status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    # Existing completed rows are truthfully PDF-only. They are intentionally not
    # enqueued for an unsolicited retro-send; a later explicit manual resend gets v1.
    op.execute(
        "UPDATE full_report_telegram_deliveries "
        "SET delivery_format_version = 'pdf-only-v0', text_status = 'legacy_not_delivered', "
        "document_status = 'sent' WHERE status = 'completed'"
    )
    op.drop_constraint("ck_full_report_delivery_state", "full_report_telegram_deliveries", type_="check")
    op.create_check_constraint(
        "ck_full_report_delivery_text_status",
        "full_report_telegram_deliveries",
        "text_status IN ('pending', 'sent', 'legacy_not_delivered')",
    )
    op.create_check_constraint(
        "ck_full_report_delivery_document_status",
        "full_report_telegram_deliveries",
        "document_status IN ('pending', 'sent')",
    )
    op.create_check_constraint(
        "ck_full_report_delivery_total_text_chunks",
        "full_report_telegram_deliveries",
        "total_text_chunks >= 0",
    )
    op.create_check_constraint(
        "ck_full_report_delivery_text_payload_sha256",
        "full_report_telegram_deliveries",
        "text_payload_sha256 IS NULL OR (length(text_payload_sha256) = 64 AND text_payload_sha256 ~ '^[0-9a-f]{64}$')",
    )
    op.create_check_constraint(
        "ck_full_report_delivery_state",
        "full_report_telegram_deliveries",
        "(status = 'queued' AND claimed_at IS NULL AND sent_at IS NULL AND failed_at IS NULL) OR "
        "(status = 'sending' AND claimed_at IS NOT NULL AND attempt_count > 0 AND sent_at IS NULL AND failed_at IS NULL) OR "
        "(status = 'completed' AND claimed_at IS NULL AND sent_at IS NOT NULL AND failed_at IS NULL "
        "AND telegram_document_message_id IS NOT NULL AND document_status = 'sent' AND retryable = false "
        "AND (text_status = 'sent' OR delivery_format_version = 'pdf-only-v0')) OR "
        "(status = 'failed' AND claimed_at IS NULL AND failed_at IS NOT NULL AND sent_at IS NULL AND error_code IS NOT NULL) OR "
        "(status = 'canceled' AND claimed_at IS NULL AND sent_at IS NULL AND retryable = false)",
    )
    op.create_index(
        "ix_full_report_delivery_status_text_document",
        "full_report_telegram_deliveries",
        ["status", "text_status", "document_status"],
    )
    # Legacy PDF-only delivery allowed an automatic and manual row to be active
    # together. Keep the oldest in-flight/retryable row and cancel only the
    # redundant unsent ledger rows before enforcing one transport path per report.
    op.execute(
        "WITH ranked AS ("
        " SELECT id, row_number() OVER (PARTITION BY report_id ORDER BY "
        " CASE WHEN status = 'sending' THEN 0 WHEN status = 'queued' THEN 1 ELSE 2 END, "
        " queued_at, id) AS position "
        " FROM full_report_telegram_deliveries "
        " WHERE status IN ('queued', 'sending') OR (status = 'failed' AND retryable = true)"
        ") UPDATE full_report_telegram_deliveries AS delivery "
        " SET status = 'canceled', retryable = false, claimed_at = NULL, failed_at = NULL, "
        " error_code = 'delivery_canceled', error_detail = NULL "
        " FROM ranked WHERE delivery.id = ranked.id AND ranked.position > 1"
    )
    op.create_index(
        "uq_full_report_delivery_active_report",
        "full_report_telegram_deliveries",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'sending') OR (status = 'failed' AND retryable = true)"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_full_report_delivery_active_report", table_name="full_report_telegram_deliveries")
    op.drop_index("ix_full_report_delivery_status_text_document", table_name="full_report_telegram_deliveries")
    op.drop_constraint("ck_full_report_delivery_state", "full_report_telegram_deliveries", type_="check")
    op.drop_constraint("ck_full_report_delivery_text_payload_sha256", "full_report_telegram_deliveries", type_="check")
    op.drop_constraint("ck_full_report_delivery_total_text_chunks", "full_report_telegram_deliveries", type_="check")
    op.drop_constraint("ck_full_report_delivery_document_status", "full_report_telegram_deliveries", type_="check")
    op.drop_constraint("ck_full_report_delivery_text_status", "full_report_telegram_deliveries", type_="check")
    for name in (
        "document_status", "text_status", "text_message_ids", "total_text_chunks",
        "text_chunks_snapshot", "text_payload_sha256", "delivery_format_version",
    ):
        op.drop_column("full_report_telegram_deliveries", name)
    op.create_check_constraint(
        "ck_full_report_delivery_state",
        "full_report_telegram_deliveries",
        "(status = 'queued' AND claimed_at IS NULL AND sent_at IS NULL AND failed_at IS NULL) OR "
        "(status = 'sending' AND claimed_at IS NOT NULL AND attempt_count > 0 AND sent_at IS NULL AND failed_at IS NULL) OR "
        "(status = 'completed' AND claimed_at IS NULL AND sent_at IS NOT NULL AND failed_at IS NULL "
        "AND telegram_document_message_id IS NOT NULL AND retryable = false) OR "
        "(status = 'failed' AND claimed_at IS NULL AND failed_at IS NOT NULL AND sent_at IS NULL AND error_code IS NOT NULL) OR "
        "(status = 'canceled' AND claimed_at IS NULL AND sent_at IS NULL AND retryable = false)",
    )
