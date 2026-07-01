"""add auth and guest profile tables

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("auth_method", sa.String(20), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("vk_id", sa.String(64), nullable=True))

    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_index("ix_users_vk_id", "users", ["vk_id"])

    op.create_index(
        "uq_user_email_notnull",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_user_phone_notnull",
        "users",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.create_index(
        "uq_user_vk_id_notnull",
        "users",
        ["vk_id"],
        unique=True,
        postgresql_where=sa.text("vk_id IS NOT NULL"),
    )

    op.create_table(
        "guest_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("guest_token", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("birth_date", sa.String(10), nullable=True),
        sa.Column("quiz_answers", postgresql.JSONB(), nullable=True),
        sa.Column("report_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "merged_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_guest_profiles_guest_token",
        "guest_profiles",
        ["guest_token"],
        unique=True,
    )
    op.create_index(
        "ix_guest_profiles_expires_at",
        "guest_profiles",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_guest_profiles_expires_at", table_name="guest_profiles")
    op.drop_index("ix_guest_profiles_guest_token", table_name="guest_profiles")
    op.drop_table("guest_profiles")

    op.drop_index("uq_user_vk_id_notnull", table_name="users")
    op.drop_index("uq_user_phone_notnull", table_name="users")
    op.drop_index("uq_user_email_notnull", table_name="users")

    op.drop_index("ix_users_vk_id", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")

    op.drop_column("users", "vk_id")
    op.drop_column("users", "phone_verified")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "auth_method")
    op.drop_column("users", "phone")