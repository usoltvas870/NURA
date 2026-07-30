import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, inspect
from sqlalchemy.exc import IntegrityError

from core.models import (
    Base,
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
)


LEGACY_REVISION = "f7a8b9c0d1e2"
PRE_LEGACY_REVISION = "e6f7a8b9c0d1"
# c0d1e2f3a4b5 is PostgreSQL-only FK normalization; SQLite round-trip stops at the previous revision.
SQLITE_COMPATIBLE_HEAD = "b9c0d1e2f3a4"
REPORT_LIFECYCLE_COLUMNS = {
    "payment_id",
    "payment_state",
    "payment_confirmed_at",
    "generation_state",
    "generation_enqueued_at",
    "generation_started_at",
    "generated_at",
    "generation_failed_at",
    "generation_attempts",
    "generation_error_category",
}


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def _create_pre_legacy_schema(database_path: Path) -> None:
    legacy_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name in {"promo_reservations", "report_generation_jobs"}:
            continue
        if table.name == "reports":
            Table(
                "reports",
                legacy_metadata,
                *[
                    column._copy()
                    for column in table.columns
                    if column.name not in REPORT_LIFECYCLE_COLUMNS
                ],
            )
            continue
        table.to_metadata(legacy_metadata)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        legacy_metadata.create_all(engine)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_placeholder_report_and_job_schema_contract(db_session, db_engine, test_user):
    user_id = test_user.id
    placeholder = Report(
        user_id=user_id,
        report_type="full",
        token="report-lifecycle-placeholder",
    )
    db_session.add(placeholder)
    await db_session.commit()
    await db_session.refresh(placeholder)

    assert placeholder.matrix_data is None
    assert placeholder.ai_analysis is None
    assert placeholder.kitchen_analysis is None
    assert placeholder.payment_id is None
    assert placeholder.payment_state == ReportPaymentState.AWAITING_PAYMENT
    assert placeholder.payment_confirmed_at is None
    assert placeholder.generation_state == ReportGenerationState.NOT_REQUESTED
    assert placeholder.generation_attempts == 0
    assert placeholder.generated_at is None
    assert placeholder.generation_enqueued_at is None
    assert placeholder.generation_started_at is None
    assert placeholder.generation_failed_at is None

    payment = Payment(
        user_id=user_id,
        amount=890,
        payment_type="matrix",
    )
    db_session.add(payment)
    await db_session.commit()

    placeholder.payment_id = payment.id
    await db_session.commit()
    report_id = placeholder.id

    conflicting_report = Report(
        user_id=user_id,
        report_type="full",
        token="report-lifecycle-payment-conflict",
        payment_id=payment.id,
    )
    db_session.add(conflicting_report)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    duplicate_token = Report(
        user_id=user_id,
        report_type="full",
        token="report-lifecycle-placeholder",
    )
    db_session.add(duplicate_token)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    job = ReportGenerationJob(report_id=report_id)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    assert job.job_type == "full_report"
    assert job.state == ReportGenerationJobState.PENDING_DISPATCH
    assert job.attempts == 0
    assert job.next_attempt_at is None
    assert job.claimed_at is None
    assert job.published_at is None
    assert job.completed_at is None
    assert job.failed_at is None

    db_session.add(ReportGenerationJob(report_id=report_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    alternate_job = ReportGenerationJob(
        report_id=report_id,
        job_type="regenerate_full_report",
    )
    db_session.add(alternate_job)
    await db_session.commit()

    assert Report.__table__.c.generation_error_category.type.length == 128
    assert ReportGenerationJob.__table__.c.last_error_category.type.length == 128
    assert "user_id" not in ReportGenerationJob.__table__.c
    assert "token" not in ReportGenerationJob.__table__.c
    assert "payload" not in ReportGenerationJob.__table__.c
    assert "payment_id" not in ReportGenerationJob.__table__.c
    assert "provider_payment_id" not in ReportGenerationJob.__table__.c
    assert "birth_date" not in ReportGenerationJob.__table__.c

    async with db_engine.connect() as connection:
        report_indexes = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_indexes("reports")
        )
        job_indexes = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_indexes(
                "report_generation_jobs"
            )
        )
        job_foreign_keys = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_foreign_keys(
                "report_generation_jobs"
            )
        )

    assert any(index["name"] == "ix_reports_payment_id" for index in report_indexes)
    assert any(
        index["name"] == "ix_report_generation_jobs_state_next_attempt_created"
        and index["column_names"] == ["state", "next_attempt_at", "created_at"]
        for index in job_indexes
    )
    assert any(
        index["name"] == "ix_report_generation_jobs_report_id" for index in job_indexes
    )
    assert any(
        index["name"] == "ix_report_generation_jobs_celery_task_id" for index in job_indexes
    )
    assert any(
        foreign_key["constrained_columns"] == ["report_id"]
        and foreign_key["referred_table"] == "reports"
        for foreign_key in job_foreign_keys
    )


def test_migration_backfills_legacy_reports_and_round_trips(tmp_path, monkeypatch):
    database_path = tmp_path / "report-lifecycle.sqlite"
    config = _alembic_config(database_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")

    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads == ["c5d6e7f8a9b0"]

    _create_pre_legacy_schema(database_path)
    command.stamp(config, PRE_LEGACY_REVISION)
    command.upgrade(config, LEGACY_REVISION)

    legacy_user_id = uuid.uuid4().hex
    legacy_report_id = uuid.uuid4().hex
    created_at = "2026-07-16 10:11:12.000000"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, name, birth_date, subscription_status, tarot_subscription,
                has_matrix, compatibility_used, has_pwa_push, email_verified,
                phone_verified, account_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_user_id,
                "Legacy user",
                "01.01.1990",
                "free",
                0,
                0,
                0,
                0,
                0,
                0,
                "active",
            ),
        )
        connection.execute(
            """
            INSERT INTO reports (
                id, user_id, report_type, token, matrix_data, ai_analysis,
                kitchen_analysis, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_report_id,
                legacy_user_id,
                "full",
                "legacy-report-token",
                '{"legacy": true}',
                '{"analysis": "preserved"}',
                '{"kitchen": "preserved"}',
                created_at,
            ),
        )

    command.upgrade(config, SQLITE_COMPATIBLE_HEAD)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
        report_columns = {column["name"] for column in inspector.get_columns("reports")}
        job_columns = {
            column["name"]
            for column in inspector.get_columns("report_generation_jobs")
        }
        job_indexes = {
            index["name"] for index in inspector.get_indexes("report_generation_jobs")
        }
    finally:
        engine.dispose()

    assert REPORT_LIFECYCLE_COLUMNS <= report_columns
    assert {
        "id",
        "report_id",
        "job_type",
        "state",
        "attempts",
        "next_attempt_at",
        "claimed_at",
        "published_at",
        "completed_at",
        "failed_at",
        "last_error_category",
        "celery_task_id",
        "created_at",
        "updated_at",
    } <= job_columns
    assert "ix_report_generation_jobs_state_next_attempt_created" in job_indexes

    with sqlite3.connect(database_path) as connection:
        report = connection.execute(
            """
            SELECT token, user_id, matrix_data, ai_analysis, kitchen_analysis,
                   payment_id, payment_state, generation_state, generated_at,
                   generation_attempts
            FROM reports WHERE id = ?
            """,
            (legacy_report_id,),
        ).fetchone()
        jobs = connection.execute("SELECT COUNT(*) FROM report_generation_jobs").fetchone()

    assert report == (
        "legacy-report-token",
        legacy_user_id,
        '{"legacy": true}',
        '{"analysis": "preserved"}',
        '{"kitchen": "preserved"}',
        None,
        ReportPaymentState.LEGACY_UNLINKED,
        ReportGenerationState.COMPLETED,
        created_at,
        0,
    )
    assert jobs == (0,)

    placeholder_id = uuid.uuid4().hex
    job_id = uuid.uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO reports (id, user_id, report_type, token) VALUES (?, ?, ?, ?)",
            (placeholder_id, legacy_user_id, "full", "migrated-placeholder-token"),
        )
        placeholder_defaults = connection.execute(
            """
            SELECT payment_state, generation_state, generation_attempts
            FROM reports WHERE id = ?
            """,
            (placeholder_id,),
        ).fetchone()
        connection.execute(
            "INSERT INTO report_generation_jobs (id, report_id) VALUES (?, ?)",
            (job_id, placeholder_id),
        )
        job_defaults = connection.execute(
            """
            SELECT job_type, state, attempts
            FROM report_generation_jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO report_generation_jobs (id, report_id) VALUES (?, ?)",
                (uuid.uuid4().hex, placeholder_id),
            )

    assert placeholder_defaults == (
        ReportPaymentState.AWAITING_PAYMENT,
        ReportGenerationState.NOT_REQUESTED,
        0,
    )
    assert job_defaults == ("full_report", ReportGenerationJobState.PENDING_DISPATCH, 0)

    command.downgrade(config, LEGACY_REVISION)
    command.upgrade(config, SQLITE_COMPATIBLE_HEAD)

    with sqlite3.connect(database_path) as connection:
        report_after_repeat_upgrade = connection.execute(
            """
            SELECT token, user_id, matrix_data, ai_analysis, kitchen_analysis,
                   payment_id, payment_state, generation_state, generated_at
            FROM reports WHERE id = ?
            """,
            (legacy_report_id,),
        ).fetchone()

    assert report_after_repeat_upgrade == (
        "legacy-report-token",
        legacy_user_id,
        '{"legacy": true}',
        '{"analysis": "preserved"}',
        '{"kitchen": "preserved"}',
        None,
        ReportPaymentState.LEGACY_UNLINKED,
        ReportGenerationState.COMPLETED,
        created_at,
    )
