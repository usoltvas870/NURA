"""add minimal persisted Telegram broadcast campaign contour

Revision ID: c6d7e8f9a0b1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "editorial_messages_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE users SET editorial_messages_enabled = false "
            "WHERE notification_prefs IS NOT NULL "
            "AND notification_prefs ? 'news' "
            "AND lower(notification_prefs ->> 'news') = 'false'"
        )
    )

    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("campaign_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("content_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("text_snapshot", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=True),
        sa.Column("media_file_id", sa.String(length=256), nullable=True),
        sa.Column("cta_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("segment_type", sa.String(length=64), nullable=False),
        sa.Column("segment_parameters", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("attribution_window_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column("launched_by", sa.String(length=64), nullable=True),
        sa.Column("tested_version", sa.Integer(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_message_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preview_version", sa.Integer(), nullable=True),
        sa.Column("preview_count", sa.Integer(), nullable=True),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("launch_idempotency_hash", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("delivered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("suppressed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("campaign_type IN ('editorial', 'commercial')", name="ck_broadcast_campaigns_type"),
        sa.CheckConstraint("status IN ('draft', 'tested', 'queued', 'sending', 'completed', 'canceled', 'failed')", name="ck_broadcast_campaigns_status"),
        sa.CheckConstraint("content_version >= 1", name="ck_broadcast_campaigns_version"),
        sa.CheckConstraint("attribution_window_days BETWEEN 1 AND 30", name="ck_broadcast_campaigns_attribution_window"),
        sa.CheckConstraint("selected_count >= 0 AND delivered_count >= 0 AND blocked_count >= 0 AND suppressed_count >= 0 AND failed_count >= 0", name="ck_broadcast_campaigns_counts"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("launch_idempotency_hash"),
    )
    op.create_index("ix_broadcast_campaigns_public_id", "broadcast_campaigns", ["public_id"], unique=True)
    op.create_index("ix_broadcast_campaigns_status_created", "broadcast_campaigns", ["status", "created_at"], unique=False)

    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("click_token", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("media_message_id", sa.BigInteger(), nullable=True),
        sa.Column("text_message_id", sa.BigInteger(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'sending', 'delivered', 'failed_retryable', 'failed_terminal', 'blocked', 'suppressed_opt_out', 'suppressed_frequency', 'canceled')", name="ck_broadcast_deliveries_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_broadcast_deliveries_attempts"),
        sa.ForeignKeyConstraint(["campaign_id"], ["broadcast_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_broadcast_deliveries_campaign_user"),
        sa.UniqueConstraint("click_token"),
    )
    op.create_index("ix_broadcast_deliveries_click_token", "broadcast_deliveries", ["click_token"], unique=True)
    op.create_index("ix_broadcast_deliveries_campaign_status", "broadcast_deliveries", ["campaign_id", "status", "created_at"], unique=False)
    op.create_index("ix_broadcast_deliveries_user_delivered", "broadcast_deliveries", ["user_id", "delivered_at"], unique=False)
    op.create_index("ix_broadcast_deliveries_retry", "broadcast_deliveries", ["status", "retry_not_before", "claimed_at"], unique=False)

    op.create_table(
        "broadcast_cta_clicks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cta_key", sa.String(length=16), nullable=False),
        sa.Column("destination", sa.String(length=32), nullable=False),
        sa.Column("first_clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("click_count", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("click_count BETWEEN 1 AND 1000000", name="ck_broadcast_cta_clicks_count"),
        sa.ForeignKeyConstraint(["campaign_id"], ["broadcast_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delivery_id"], ["broadcast_deliveries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", "cta_key", name="uq_broadcast_cta_clicks_delivery_key"),
    )
    op.create_index("ix_broadcast_cta_clicks_campaign_clicked", "broadcast_cta_clicks", ["campaign_id", "last_clicked_at"], unique=False)
    op.create_index("ix_broadcast_cta_clicks_user_clicked", "broadcast_cta_clicks", ["user_id", "last_clicked_at"], unique=False)

    op.create_table(
        "broadcast_cta_click_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("click_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cta_key", sa.String(length=16), nullable=False),
        sa.Column("destination", sa.String(length=32), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attribution_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["click_id"], ["broadcast_cta_clicks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["broadcast_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delivery_id"], ["broadcast_deliveries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_cta_click_events_campaign_clicked", "broadcast_cta_click_events", ["campaign_id", "clicked_at"], unique=False)
    op.create_index("ix_broadcast_cta_click_events_user_clicked", "broadcast_cta_click_events", ["user_id", "clicked_at"], unique=False)

    op.create_table(
        "telegram_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.String(length=64), server_default="system", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("reason IN ('bot_blocked', 'chat_not_found', 'operator')", name="ck_telegram_suppressions_reason"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_telegram_suppressions_user"),
    )
    op.create_index("ix_telegram_suppressions_active", "telegram_suppressions", ["active", "reason"], unique=False)

    op.create_table(
        "broadcast_audit_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["broadcast_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_audit_campaign_created", "broadcast_audit_entries", ["campaign_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_broadcast_audit_campaign_created", table_name="broadcast_audit_entries")
    op.drop_table("broadcast_audit_entries")
    op.drop_index("ix_telegram_suppressions_active", table_name="telegram_suppressions")
    op.drop_table("telegram_suppressions")
    op.drop_index("ix_broadcast_cta_click_events_user_clicked", table_name="broadcast_cta_click_events")
    op.drop_index("ix_broadcast_cta_click_events_campaign_clicked", table_name="broadcast_cta_click_events")
    op.drop_table("broadcast_cta_click_events")
    op.drop_index("ix_broadcast_cta_clicks_user_clicked", table_name="broadcast_cta_clicks")
    op.drop_index("ix_broadcast_cta_clicks_campaign_clicked", table_name="broadcast_cta_clicks")
    op.drop_table("broadcast_cta_clicks")
    op.drop_index("ix_broadcast_deliveries_retry", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_user_delivered", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_campaign_status", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_click_token", table_name="broadcast_deliveries")
    op.drop_table("broadcast_deliveries")
    op.drop_index("ix_broadcast_campaigns_status_created", table_name="broadcast_campaigns")
    op.drop_index("ix_broadcast_campaigns_public_id", table_name="broadcast_campaigns")
    op.drop_table("broadcast_campaigns")
    op.drop_column("users", "editorial_messages_enabled")
