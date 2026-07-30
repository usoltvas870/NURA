"""add durable chat delivery progress and web acknowledgement

Revision ID: b4c5d6e7f8a9
Revises: f9a0b1c2d3e4
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_message_usages", sa.Column("delivery_status", sa.String(length=16), nullable=False, server_default="pending"))
    op.add_column("chat_message_usages", sa.Column("delivery_total_chunks", sa.Integer(), nullable=True))
    op.add_column("chat_message_usages", sa.Column("delivery_next_chunk_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("chat_message_usages", sa.Column("delivery_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("chat_message_usages", sa.Column("delivery_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_message_usages", sa.Column("delivery_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_message_usages", sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_message_usages", sa.Column("delivery_retryable", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("chat_message_usages", sa.Column("delivery_error_code", sa.String(length=64), nullable=True))
    op.add_column("chat_message_usages", sa.Column("telegram_chat_id_snapshot", sa.BigInteger(), nullable=True))
    op.create_check_constraint("ck_chat_message_usages_delivery_status", "chat_message_usages", "delivery_status IN ('pending', 'queued', 'sending', 'retryable', 'delivered', 'awaiting_ack', 'failed')")
    op.create_check_constraint("ck_chat_message_usages_delivery_attempt_count", "chat_message_usages", "delivery_attempt_count >= 0")
    op.create_index("ix_chat_message_usages_delivery_claim", "chat_message_usages", ["delivery_status", "delivery_claimed_at"])
    op.execute("UPDATE chat_message_usages SET delivery_status = 'delivered', delivery_retryable = false, delivery_completed_at = consumed_at WHERE status = 'consumed'")
    op.execute("UPDATE chat_message_usages SET status = 'released', released_at = now(), release_reason = 'legacy_delivery_unrecoverable', error_code = 'legacy_delivery_unrecoverable', response_text = NULL, result_ready_at = NULL, delivery_status = 'failed', delivery_retryable = false, delivery_failed_at = now(), delivery_error_code = 'legacy_delivery_unrecoverable' WHERE status = 'result_ready'")


def downgrade() -> None:
    op.drop_index("ix_chat_message_usages_delivery_claim", table_name="chat_message_usages")
    op.drop_constraint("ck_chat_message_usages_delivery_attempt_count", "chat_message_usages", type_="check")
    op.drop_constraint("ck_chat_message_usages_delivery_status", "chat_message_usages", type_="check")
    for column in ("telegram_chat_id_snapshot", "delivery_error_code", "delivery_retryable", "delivery_failed_at", "delivery_completed_at", "delivery_claimed_at", "delivery_attempt_count", "delivery_next_chunk_index", "delivery_total_chunks", "delivery_status"):
        op.drop_column("chat_message_usages", column)
