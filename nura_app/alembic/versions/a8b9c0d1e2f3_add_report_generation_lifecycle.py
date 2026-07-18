"""add report generation lifecycle foundation

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(
            sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "payment_state",
                sa.String(length=32),
                nullable=False,
                server_default="awaiting_payment",
            )
        )
        batch_op.add_column(
            sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "generation_state",
                sa.String(length=32),
                nullable=False,
                server_default="not_requested",
            )
        )
        batch_op.add_column(
            sa.Column("generation_enqueued_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("generation_failed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "generation_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("generation_error_category", sa.String(length=128), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_reports_payment_id_payments", "payments", ["payment_id"], ["id"]
        )
        batch_op.create_unique_constraint("uq_reports_payment_id", ["payment_id"])
        batch_op.create_index("ix_reports_payment_id", ["payment_id"])

    op.execute(
        """
        UPDATE reports
        SET payment_state = 'legacy_unlinked',
            generation_state = 'completed',
            generated_at = created_at,
            generation_attempts = 0
        """
    )

    op.create_table(
        "report_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "job_type",
            sa.String(length=32),
            nullable=False,
            server_default="full_report",
        ),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default="pending_dispatch",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=128), nullable=True),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id", "job_type", name="uq_report_generation_jobs_report_job_type"
        ),
    )
    op.create_index(
        "ix_report_generation_jobs_state_next_attempt_created",
        "report_generation_jobs",
        ["state", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_report_generation_jobs_report_id", "report_generation_jobs", ["report_id"]
    )
    op.create_index(
        "ix_report_generation_jobs_celery_task_id",
        "report_generation_jobs",
        ["celery_task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_report_generation_jobs_celery_task_id", table_name="report_generation_jobs"
    )
    op.drop_index(
        "ix_report_generation_jobs_report_id", table_name="report_generation_jobs"
    )
    op.drop_index(
        "ix_report_generation_jobs_state_next_attempt_created",
        table_name="report_generation_jobs",
    )
    op.drop_table("report_generation_jobs")

    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_index("ix_reports_payment_id")
        batch_op.drop_constraint("uq_reports_payment_id", type_="unique")
        batch_op.drop_constraint("fk_reports_payment_id_payments", type_="foreignkey")
        batch_op.drop_column("generation_error_category")
        batch_op.drop_column("generation_attempts")
        batch_op.drop_column("generation_failed_at")
        batch_op.drop_column("generated_at")
        batch_op.drop_column("generation_started_at")
        batch_op.drop_column("generation_enqueued_at")
        batch_op.drop_column("generation_state")
        batch_op.drop_column("payment_confirmed_at")
        batch_op.drop_column("payment_state")
        batch_op.drop_column("payment_id")
