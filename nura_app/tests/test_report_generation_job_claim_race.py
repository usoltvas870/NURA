import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import (
    Base,
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    User,
)
from core.repositories.report_lifecycle import ReportGenerationJobRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _create_paid_pending_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    token: str,
    *,
    job_state: str = ReportGenerationJobState.PENDING_DISPATCH,
    next_attempt_at: datetime | None = None,
    report_payment_state: str = ReportPaymentState.PAYMENT_CONFIRMED,
    report_generation_state: str = ReportGenerationState.PENDING_DISPATCH,
    job_type: str = "full_report",
    claimed_at: datetime | None = None,
    published_at: datetime | None = None,
    celery_task_id: str | None = None,
) -> tuple[Report, ReportGenerationJob]:
    payment = Payment(
        id=uuid.uuid4(), user_id=user_id, amount=890, payment_type="web_matrix"
    )
    report = Report(
        id=uuid.uuid4(),
        user_id=user_id,
        report_type="full",
        token=token,
        payment_id=payment.id if report_payment_state == ReportPaymentState.PAYMENT_CONFIRMED else None,
        payment_state=report_payment_state,
        payment_confirmed_at=(
            _now()
            if report_payment_state == ReportPaymentState.PAYMENT_CONFIRMED
            else None
        ),
        generation_state=report_generation_state,
    )
    job = ReportGenerationJob(
        id=uuid.uuid4(),
        report_id=report.id,
        job_type=job_type,
        state=job_state,
        next_attempt_at=next_attempt_at,
        claimed_at=claimed_at,
        published_at=published_at,
        celery_task_id=celery_task_id,
    )
    session.add_all([payment, report, job])
    await session.commit()
    return report, job


@pytest.mark.asyncio
async def test_two_dispatchers_cannot_claim_same_generation_job(tmp_path, caplog):
    database_path = tmp_path / "generation_claim_race.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}", poolclass=NullPool
    )
    checked_out_connections: set[int] | None = None

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA busy_timeout=300")

    @event.listens_for(engine.sync_engine, "checkout")
    def record_physical_connection(
        dbapi_connection, connection_record, connection_proxy
    ):
        if checked_out_connections is not None:
            checked_out_connections.add(id(dbapi_connection))

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.run_sync(Base.metadata.create_all)

        cycle_results: list[tuple[int, int]] = []
        for cycle in range(10):
            async with session_factory() as seed_session:
                user = User(
                    id=uuid.uuid4(),
                    name=f"Claim race {cycle}",
                    birth_date=f"01.01.{1990 + cycle}",
                )
                seed_session.add(user)
                await seed_session.commit()
                report, job = await _create_paid_pending_job(
                    seed_session, user.id, f"claim-race-report-{cycle}"
                )

            barrier = asyncio.Barrier(2)
            critical_boundary_calls = 0

            async def wait_before_atomic_update() -> None:
                nonlocal critical_boundary_calls
                critical_boundary_calls += 1
                await asyncio.wait_for(barrier.wait(), timeout=2)

            first_session = AsyncSession(bind=engine, expire_on_commit=False)
            second_session = AsyncSession(bind=engine, expire_on_commit=False)
            assert id(first_session) != id(second_session)
            first_repo = ReportGenerationJobRepository(
                first_session, wait_before_atomic_update
            )
            second_repo = ReportGenerationJobRepository(
                second_session, wait_before_atomic_update
            )
            checked_out_connections = set()

            async def claim(repo: ReportGenerationJobRepository, session: AsyncSession):
                outcome = await repo.claim_job_for_dispatch(job.id, _now())
                await session.commit()
                return outcome

            try:
                outcomes = await asyncio.gather(
                    claim(first_repo, first_session),
                    claim(second_repo, second_session),
                )
                assert critical_boundary_calls == 2
                assert checked_out_connections is not None
                assert len(checked_out_connections) >= 2
                assert outcomes.count("claimed") == 1
                assert outcomes.count("generation_job_claim_conflict") == 1

                loser_session = (
                    first_session
                    if outcomes[0] == "generation_job_claim_conflict"
                    else second_session
                )
                loser_job = await loser_session.get(ReportGenerationJob, job.id)
                loser_report = await loser_session.get(Report, report.id)
                assert loser_job is not None
                assert loser_report is not None
                assert loser_job.state == ReportGenerationJobState.DISPATCHING
                assert loser_job.claimed_at is not None
                assert loser_job.attempts == 0
                assert loser_job.published_at is None
                assert loser_job.celery_task_id is None
                assert loser_report.generation_state == ReportGenerationState.PENDING_DISPATCH
                assert (
                    await loser_session.execute(
                        select(ReportGenerationJob).where(
                            ReportGenerationJob.report_id == report.id
                        )
                    )
                ).scalars().all() == [loser_job]
                repeat = await ReportGenerationJobRepository(
                    loser_session
                ).claim_job_for_dispatch(job.id, _now())
                assert repeat == "generation_job_claim_conflict"
                assert (await loser_session.get(ReportGenerationJob, job.id)).claimed_at == loser_job.claimed_at
                cycle_results.append((outcomes.count("claimed"), outcomes.count("generation_job_claim_conflict")))
            finally:
                await first_session.close()
                await second_session.close()
                checked_out_connections = None

        assert cycle_results == [(1, 1)] * 10
        assert "claim-race-report" not in caplog.text
        assert "database is locked" not in caplog.text.lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatchable_query_and_invalid_claim_protection(db_session, test_user):
    now = _now()
    _, pending = await _create_paid_pending_job(
        db_session, test_user.id, "dispatchable-pending"
    )
    _, due_retry = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "dispatchable-retry",
        job_state=ReportGenerationJobState.FAILED_RETRYABLE,
        next_attempt_at=now - timedelta(seconds=1),
    )
    _, future_retry = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "future-retry",
        job_state=ReportGenerationJobState.FAILED_RETRYABLE,
        next_attempt_at=now + timedelta(minutes=1),
    )
    _, queued = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "queued-job",
        job_state=ReportGenerationJobState.QUEUED,
    )
    _, dispatching = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "dispatching-job",
        job_state=ReportGenerationJobState.DISPATCHING,
    )
    _, completed_job = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "completed-job",
        job_state=ReportGenerationJobState.COMPLETED,
    )
    _, terminal_job = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "terminal-job",
        job_state=ReportGenerationJobState.FAILED_TERMINAL,
    )
    _, other_type = await _create_paid_pending_job(
        db_session, test_user.id, "other-type-job", job_type="other_type"
    )
    _, unpaid = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "unpaid-report-job",
        report_payment_state=ReportPaymentState.AWAITING_PAYMENT,
    )
    _, legacy = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "legacy-report-job",
        report_payment_state=ReportPaymentState.LEGACY_UNLINKED,
    )
    _, completed_report = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "completed-report-job",
        report_generation_state=ReportGenerationState.COMPLETED,
    )
    repository = ReportGenerationJobRepository(db_session)

    dispatchable = await repository.list_dispatchable_jobs(now, limit=10)
    assert [job.id for job in dispatchable] == [pending.id, due_retry.id]
    assert [job.id for job in await repository.list_dispatchable_jobs(now, limit=1)] == [pending.id]

    for job in (
        queued,
        dispatching,
        completed_job,
        terminal_job,
        future_retry,
        other_type,
        unpaid,
        legacy,
        completed_report,
    ):
        assert await repository.claim_job_for_dispatch(job.id, now) == "generation_job_claim_conflict"
    assert await repository.claim_job_for_dispatch(due_retry.id, now) == "claimed"
    await db_session.commit()
    assert due_retry.state == ReportGenerationJobState.DISPATCHING
    assert due_retry.next_attempt_at is None
    assert due_retry.attempts == 0
    assert await repository.get_lifecycle_snapshot(pending.id) is not None


@pytest.mark.asyncio
async def test_stale_dispatch_claim_recovery_is_safe_and_retryable(db_session, test_user):
    now = _now()
    old_claimed_at = now - timedelta(minutes=10)
    report, stale_job = await _create_paid_pending_job(
        db_session,
        test_user.id,
        "stale-claim-job",
        job_state=ReportGenerationJobState.DISPATCHING,
        claimed_at=old_claimed_at,
    )
    repository = ReportGenerationJobRepository(db_session)
    next_attempt_at = now + timedelta(minutes=1)
    assert await repository.mark_stale_dispatch_claim_retryable(
        stale_job.id, now - timedelta(minutes=5), now, next_attempt_at
    )
    await db_session.commit()
    await db_session.refresh(stale_job)
    assert stale_job.state == ReportGenerationJobState.FAILED_RETRYABLE
    assert stale_job.claimed_at is not None
    assert _as_utc(stale_job.claimed_at) == old_claimed_at
    assert stale_job.attempts == 0
    assert stale_job.next_attempt_at is not None
    assert _as_utc(stale_job.next_attempt_at) == next_attempt_at
    assert stale_job.last_error_category == "dispatch_claim_expired"
    assert report.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert await repository.claim_job_for_dispatch(stale_job.id, next_attempt_at) == "claimed"
    await db_session.commit()

    protected_jobs: list[ReportGenerationJob] = []
    for suffix, kwargs in (
        ("fresh", {"claimed_at": now}),
        ("published", {"claimed_at": old_claimed_at, "published_at": now}),
        ("task", {"claimed_at": old_claimed_at, "celery_task_id": "published-task"}),
        ("completed", {"job_state": ReportGenerationJobState.COMPLETED}),
        ("terminal", {"job_state": ReportGenerationJobState.FAILED_TERMINAL}),
        (
            "completed-report",
            {"report_generation_state": ReportGenerationState.COMPLETED},
        ),
    ):
        _, job = await _create_paid_pending_job(
            db_session,
            test_user.id,
            f"stale-protected-{suffix}",
            job_state=kwargs.pop("job_state", ReportGenerationJobState.DISPATCHING),
            **kwargs,
        )
        protected_jobs.append(job)
    for job in protected_jobs:
        assert not await repository.mark_stale_dispatch_claim_retryable(
            job.id, now - timedelta(minutes=5), now, next_attempt_at
        )
    await db_session.commit()
    assert all(job.last_error_category is None for job in protected_jobs)
