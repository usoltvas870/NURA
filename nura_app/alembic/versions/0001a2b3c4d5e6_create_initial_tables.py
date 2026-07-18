"""create initial tables: users, reports, payments

This migration represents the exact schema that existed before Alembic
was introduced.  It is the root revision of the linear migration chain.

Revision ID: 0001a2b3c4d5e6
Revises: (none)
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001a2b3c4d5e6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("birth_date", sa.String(10), nullable=True),
        sa.Column("main_archetype", sa.String(64), nullable=True),
        sa.Column("main_archetype_number", sa.Integer(), nullable=True),
        sa.Column(
            "subscription_status",
            sa.String(20),
            nullable=False,
            server_default="free",
        ),
        sa.Column("subscription_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_method_id", sa.String(100), nullable=True),
        sa.Column(
            "has_tarot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "report_type",
            sa.String(20),
            nullable=False,
            server_default="mini",
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("matrix_data", postgresql.JSONB(), nullable=True),
        sa.Column("ai_analysis", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("yookassa_id", sa.String(100), unique=True, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("reports")
    op.drop_table("users")
