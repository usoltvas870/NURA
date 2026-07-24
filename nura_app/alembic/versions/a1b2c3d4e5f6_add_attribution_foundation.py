"""add attribution foundation

Revision ID: b1c2d3e4f5a6
Revises: d1e2f3a4b5c6
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1c2d3e4f5a6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attribution_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("campaign", sa.String(length=128), nullable=False),
        sa.Column("content_id", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_attribution_links_code", "attribution_links", ["code"], unique=True)
    op.create_table(
        "attribution_touches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribution_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_start_parameter", sa.String(length=66), nullable=False),
        sa.Column("normalized_code", sa.String(length=24), nullable=False),
        sa.Column("resolution_status", sa.String(length=16), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("campaign", sa.String(length=128), nullable=True),
        sa.Column("content_id", sa.String(length=128), nullable=True),
        sa.Column("topic", sa.String(length=128), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("visit_count", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["attribution_link_id"], ["attribution_links.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_code", name="uq_attribution_touches_user_code"),
    )
    op.create_index("ix_attribution_touches_user_id", "attribution_touches", ["user_id"])
    op.create_index("ix_attribution_touches_link_id", "attribution_touches", ["attribution_link_id"])
    op.create_index("ix_attribution_touches_first_seen_at", "attribution_touches", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_attribution_touches_first_seen_at", table_name="attribution_touches")
    op.drop_index("ix_attribution_touches_link_id", table_name="attribution_touches")
    op.drop_index("ix_attribution_touches_user_id", table_name="attribution_touches")
    op.drop_table("attribution_touches")
    op.drop_index("ix_attribution_links_code", table_name="attribution_links")
    op.drop_table("attribution_links")
