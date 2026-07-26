"""add durable lifetime chat message usage ledger

Revision ID: d6e7f8a9b0c1
Revises: d2e3f4a5b6c7
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d6e7f8a9b0c1"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_message_usages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="reserved"),
        sa.Column("billable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=64), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("result_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("channel IN ('telegram', 'web')", name="ck_chat_message_usages_channel"),
        sa.CheckConstraint("status IN ('reserved', 'result_ready', 'consumed', 'released')", name="ck_chat_message_usages_status"),
        sa.CheckConstraint(
            "(status IN ('reserved', 'released') AND response_text IS NULL) OR "
            "(status IN ('result_ready', 'consumed') AND response_text IS NOT NULL)",
            name="ck_chat_message_usages_response_state",
        ),
        sa.CheckConstraint(
            "(status = 'reserved' AND consumed_at IS NULL AND released_at IS NULL AND result_ready_at IS NULL) OR "
            "(status = 'result_ready' AND consumed_at IS NULL AND released_at IS NULL AND result_ready_at IS NOT NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND released_at IS NULL AND result_ready_at IS NOT NULL) OR "
            "(status = 'released' AND consumed_at IS NULL AND released_at IS NOT NULL AND result_ready_at IS NULL)",
            name="ck_chat_message_usages_timestamps_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "request_key", name="uq_chat_message_usages_user_request"),
    )
    op.create_index("ix_chat_message_usages_user_status", "chat_message_usages", ["user_id", "status"])
    op.create_index("ix_chat_message_usages_stale_reserved", "chat_message_usages", ["status", "reserved_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_message_usages_stale_reserved", table_name="chat_message_usages")
    op.drop_index("ix_chat_message_usages_user_status", table_name="chat_message_usages")
    op.drop_table("chat_message_usages")
