"""add durable one-time full Matrix order checkout

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("checkout_token", sa.String(length=64), nullable=True),
        sa.Column("checkout_expires_at", sa.DateTime(timezone=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_id_snapshot", sa.BigInteger()),
        sa.Column("product_code", sa.String(length=32), nullable=False, server_default="full_matrix"),
        sa.Column("amount_kopecks", sa.Integer(), nullable=False, server_default="89000"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="created"),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("payment_started_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
        sa.Column("activation_started_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_detail", sa.String(length=256)),
        sa.Column("customer_reference_hash", sa.String(length=128)),
        sa.Column("anonymized_at", sa.DateTime(timezone=True)),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("anonymization_reason", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_orders_public_id"),
        sa.UniqueConstraint("checkout_token", name="uq_orders_checkout_token"),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        sa.UniqueConstraint("report_id", name="uq_orders_report_id"),
        sa.CheckConstraint("amount_kopecks > 0", name="ck_orders_amount_positive"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_orders_currency_rub"),
        sa.CheckConstraint("product_code = 'full_matrix'", name="ck_orders_product_full_matrix"),
        sa.CheckConstraint("status IN ('created', 'pending', 'paid', 'failed', 'canceled', 'refunded')", name="ck_orders_status"),
        sa.CheckConstraint("(status IN ('paid', 'refunded')) = (paid_at IS NOT NULL)", name="ck_orders_paid_at_status"),
        sa.CheckConstraint("(status = 'refunded') = (refunded_at IS NOT NULL)", name="ck_orders_refunded_at_status"),
        sa.CheckConstraint("(status = 'canceled') = (canceled_at IS NOT NULL)", name="ck_orders_canceled_at_status"),
    )
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index("ix_orders_pending", "orders", ["status", "updated_at"])
    op.create_index("ix_orders_retain_until", "orders", ["retain_until"])
    op.create_index("ix_orders_checkout_token", "orders", ["checkout_token"])
    op.create_table(
        "payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="yookassa"),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("amount_kopecks", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
        sa.Column("confirmation_url", sa.Text()),
        sa.Column("fiscal_email", sa.String(length=320)),
        sa.Column("cancellation_code", sa.String(length=64)),
        sa.Column("cancellation_party", sa.String(length=32)),
        sa.Column("provider_metadata", postgresql.JSONB()),
        sa.Column("test_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
        sa.Column("anonymized_at", sa.DateTime(timezone=True)),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("customer_reference_hash", sa.String(length=128)),
        sa.Column("anonymization_reason", sa.String(length=64)),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_attempts_idempotency_key"),
        sa.UniqueConstraint("provider", "provider_payment_id", name="uq_payment_attempts_provider_id"),
        sa.CheckConstraint("amount_kopecks > 0", name="ck_payment_attempts_amount_positive"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_payment_attempts_currency_rub"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'canceled', 'refunded', 'failed')", name="ck_payment_attempts_status"),
        sa.CheckConstraint("(status IN ('succeeded', 'refunded')) = (paid_at IS NOT NULL)", name="ck_payment_attempts_paid_at_status"),
        sa.CheckConstraint("(status = 'refunded') = (refunded_at IS NOT NULL)", name="ck_payment_attempts_refunded_at_status"),
        sa.CheckConstraint("(status = 'canceled') = (canceled_at IS NOT NULL)", name="ck_payment_attempts_canceled_at_status"),
    )
    op.create_index("ix_payment_attempts_order_status", "payment_attempts", ["order_id", "status"])
    op.create_index("ix_payment_attempts_retain_until", "payment_attempts", ["retain_until"])
    op.create_foreign_key("fk_orders_active_payment", "orders", "payment_attempts", ["active_payment_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="yookassa"),
        sa.Column("provider_event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_object_id", sa.String(length=100), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=100)),
        sa.Column("order_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payment_attempt_id", postgresql.UUID(as_uuid=True)),
        sa.Column("dedup_key", sa.String(length=128), nullable=False),
        sa.Column("provider_status", sa.String(length=32), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_status", sa.String(length=16), nullable=False, server_default="received"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("error_detail", sa.String(length=256)),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("anonymized_at", sa.DateTime(timezone=True)),
        sa.Column("anonymization_reason", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_attempt_id"], ["payment_attempts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_payment_events_dedup_key"),
        sa.CheckConstraint("provider = 'yookassa'", name="ck_payment_events_provider"),
        sa.CheckConstraint("processing_status IN ('received', 'processing', 'processed', 'failed')", name="ck_payment_events_processing_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_payment_events_attempt_count"),
        sa.CheckConstraint("processing_status != 'processed' OR processed_at IS NOT NULL", name="ck_payment_events_processed_at"),
        sa.CheckConstraint("processing_status != 'failed' OR (failed_at IS NOT NULL AND error_code IS NOT NULL)", name="ck_payment_events_failed_at"),
        sa.CheckConstraint("processing_status != 'processed' OR retryable = false", name="ck_payment_events_processed_not_retryable"),
        sa.CheckConstraint("processing_status NOT IN ('received', 'processing') OR (processed_at IS NULL AND failed_at IS NULL)", name="ck_payment_events_nonterminal_timestamps"),
    )
    op.create_index("ix_payment_events_attempt_created", "payment_events", ["payment_attempt_id", "created_at"])
    op.create_index("ix_payment_events_provider_object", "payment_events", ["provider", "provider_object_id", "provider_event_type"])
    op.create_index("ix_payment_events_provider_payment", "payment_events", ["provider_payment_id"])
    op.create_index("ix_payment_events_status_claim", "payment_events", ["processing_status", "claimed_at"])
    op.create_index("ix_payment_events_order", "payment_events", ["order_id"])
    op.create_index("ix_payment_events_received", "payment_events", ["received_at"])
    op.create_index("ix_payment_events_retain_until", "payment_events", ["retain_until"])
    op.add_column("reports", sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_reports_order", "reports", "orders", ["order_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_reports_order_id", "reports", ["order_id"])
    op.create_index("ix_reports_order_id", "reports", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_order_id", table_name="reports")
    op.drop_constraint("uq_reports_order_id", "reports", type_="unique")
    op.drop_constraint("fk_reports_order", "reports", type_="foreignkey")
    op.drop_column("reports", "order_id")
    op.drop_index("ix_payment_events_received", table_name="payment_events")
    op.drop_index("ix_payment_events_order", table_name="payment_events")
    op.drop_index("ix_payment_events_status_claim", table_name="payment_events")
    op.drop_index("ix_payment_events_provider_payment", table_name="payment_events")
    op.drop_index("ix_payment_events_provider_object", table_name="payment_events")
    op.drop_index("ix_payment_events_retain_until", table_name="payment_events")
    op.drop_index("ix_payment_events_attempt_created", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_constraint("fk_orders_active_payment", "orders", type_="foreignkey")
    op.drop_index("ix_payment_attempts_retain_until", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_order_status", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index("ix_orders_checkout_token", table_name="orders")
    op.drop_index("ix_orders_retain_until", table_name="orders")
    op.drop_index("ix_orders_pending", table_name="orders")
    op.drop_index("ix_orders_user_status", table_name="orders")
    op.drop_table("orders")
