"""add durable promo reservations

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("promo_reservations", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("promo_codes.id"), nullable=False), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False), sa.Column("payment_type", sa.String(20), nullable=False), sa.Column("final_amount_kopecks", sa.Integer(), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True), sa.Column("report_token", sa.String(64), nullable=True), sa.Column("state", sa.String(20), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("provider_payment_id", sa.String(100), unique=True), sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), unique=True), sa.Column("consumed_at", sa.DateTime(timezone=True)), sa.Column("released_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_promo_reservations_state_expires_at", "promo_reservations", ["state", "expires_at"])

def downgrade() -> None:
    op.drop_index("ix_promo_reservations_state_expires_at", table_name="promo_reservations")
    op.drop_table("promo_reservations")
