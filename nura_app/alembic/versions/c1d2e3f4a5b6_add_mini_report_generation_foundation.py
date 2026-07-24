"""add mini report generation foundation

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mini_report_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generation_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND guest_profile_id IS NULL) OR "
            "(user_id IS NULL AND guest_profile_id IS NOT NULL)",
            name="ck_mini_report_generations_exactly_one_owner",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guest_profile_id"], ["guest_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_mini_report_generations_user_fingerprint_version",
        "mini_report_generations",
        ["user_id", "fingerprint", "generation_version"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_mini_report_generations_guest_fingerprint_version",
        "mini_report_generations",
        ["guest_profile_id", "fingerprint", "generation_version"],
        unique=True,
        postgresql_where=sa.text("guest_profile_id IS NOT NULL"),
    )
    op.create_index("ix_mini_report_generations_status", "mini_report_generations", ["status"])
    op.create_index("ix_mini_report_generations_report_id", "mini_report_generations", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_mini_report_generations_report_id", table_name="mini_report_generations")
    op.drop_index("ix_mini_report_generations_status", table_name="mini_report_generations")
    op.drop_index(
        "uq_mini_report_generations_guest_fingerprint_version",
        table_name="mini_report_generations",
    )
    op.drop_index(
        "uq_mini_report_generations_user_fingerprint_version",
        table_name="mini_report_generations",
    )
    op.drop_table("mini_report_generations")
