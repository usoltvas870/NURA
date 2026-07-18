import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    User,
)
from core.repositories.report_lifecycle import (
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
    ReportLifecycleRepository,
)
from core.services.report_lifecycle import ReportLifecycleService


class FlushFailsOnceSession(AsyncSession):
    fail_next_flush = True

    async def flush(self, *args, **kwargs) -> None:
        if type(self).fail_next_flush:
            type(self).fail_next_flush = False
            raise RuntimeError("controlled_lifecycle_flush_failure")
        await super().flush(*args, **kwargs)


async def _report(session: AsyncSession, user_id: uuid.UUID, token: str) -> Report:
    report = Report(
        id=uuid.uuid4(),
        user_id=user_id,
        report_type="full",
        token=token,
    )
    session.add(report)
    await session.commit()
    return report


async def _payment(session: AsyncSession, user_id: uuid.UUID) -> Payment:
    payment = Payment(
        id=uuid.uuid4(),
        user_id=user_id,
        amount=890,
        payment_type="web_matrix",
    )
    session.add(payment)
    await session.commit()
    return payment


@pytest.mark.asyncio
async def test_report_payment_confirmation_is_idempotent_and_isolated(
    db_session, test_user
):
    report = await _report(db_session, test_user.id, "payment-confirmation-report")
    payment = await _payment(db_session, test_user.id)
    repository = ReportLifecycleRepository(db_session)
    confirmed_at = datetime(2026, 7, 17, tzinfo=timezone.utc)

    confirmed = await repository.confirm_report_payment(
        report.id, payment.id, confirmed_at
    )
    await db_session.commit()
    repeated = await repository.confirm_report_payment(
        report.id, payment.id, confirmed_at + timedelta(minutes=1)
    )
    await db_session.commit()

    assert confirmed.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
    assert repeated.payment_id == payment.id
    assert repeated.payment_confirmed_at == confirmed_at
    assert payment.status == "pending"
    assert await repository.get_by_token_and_user_id(report.token, test_user.id) is not None
    assert await repository.get_by_token_and_user_id(report.token, uuid.uuid4()) is None

    foreign_user = User(id=uuid.uuid4(), name="Foreign", birth_date="02.02.1990")
    db_session.add(foreign_user)
    await db_session.commit()
    foreign_payment = await _payment(db_session, foreign_user.id)
    foreign_check_report = await _report(
        db_session, test_user.id, "foreign-payment-report"
    )
    with pytest.raises(ValueError, match="invalid_report_payment"):
        await repository.confirm_report_payment(foreign_check_report.id, foreign_payment.id)

    another_report = await _report(db_session, test_user.id, "payment-conflict-report")
    with pytest.raises(ValueError, match="report_payment_conflict"):
        await repository.confirm_report_payment(another_report.id, payment.id)

    legacy = await _report(db_session, test_user.id, "legacy-payment-report")
    legacy.payment_state = ReportPaymentState.LEGACY_UNLINKED
    legacy.generation_state = ReportGenerationState.COMPLETED
    await db_session.commit()
    with pytest.raises(ValueError, match="invalid_report_payment_transition"):
        await repository.confirm_report_payment(legacy.id, payment.id)


@pytest.mark.asyncio
async def test_confirm_and_prepare_generation_is_atomic_and_idempotent(
    db_session, test_user
):
    report = await _report(db_session, test_user.id, "prepare-generation-report")
    payment = await _payment(db_session, test_user.id)
    service = ReportLifecycleService(db_session)
    confirmed_at = datetime(2026, 7, 17, 1, tzinfo=timezone.utc)

    confirmed, job = await service.confirm_payment_and_prepare_generation(
        report.id, payment.id, confirmed_at
    )
    await db_session.commit()
    repeated, repeated_job = await service.confirm_payment_and_prepare_generation(
        report.id, payment.id, confirmed_at + timedelta(minutes=1)
    )
    await db_session.commit()

    assert confirmed.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert job.state == ReportGenerationJobState.PENDING_DISPATCH
    assert repeated_job.id == job.id
    assert repeated.payment_confirmed_at == confirmed_at
    assert repeated.generation_attempts == 0
    assert (
        len(
            (
                await db_session.execute(
                    select(ReportGenerationJob).where(
                        ReportGenerationJob.report_id == report.id
                    )
                )
            ).scalars().all()
        )
        == 1
    )

    other_payment = await _payment(db_session, test_user.id)
    with pytest.raises(ValueError, match="report_payment_conflict"):
        await service.confirm_payment_and_prepare_generation(report.id, other_payment.id)

    completed = await _report(db_session, test_user.id, "completed-no-job-report")
    completed.payment_id = other_payment.id
    completed.payment_state = ReportPaymentState.PAYMENT_CONFIRMED
    completed.payment_confirmed_at = confirmed_at
    completed.generation_state = ReportGenerationState.COMPLETED
    await db_session.commit()
    with pytest.raises(ValueError, match="invalid_report_generation_transition"):
        await service.confirm_payment_and_prepare_generation(completed.id, other_payment.id)

    terminal = await _report(db_session, test_user.id, "terminal-no-job-report")
    terminal_payment = await _payment(db_session, test_user.id)
    terminal.payment_id = terminal_payment.id
    terminal.payment_state = ReportPaymentState.PAYMENT_CONFIRMED
    terminal.payment_confirmed_at = confirmed_at
    terminal.generation_state = ReportGenerationState.FAILED_TERMINAL
    await db_session.commit()
    with pytest.raises(ValueError, match="invalid_report_generation_transition"):
        await service.confirm_payment_and_prepare_generation(terminal.id, terminal_payment.id)


@pytest.mark.asyncio
async def test_flush_failure_rolls_back_all_lifecycle_changes_and_reuses_session(
    db_engine, test_user
):
    FlushFailsOnceSession.fail_next_flush = True
    session = FlushFailsOnceSession(bind=db_engine, expire_on_commit=False)
    session_id = id(session)
    try:
        report = await _report(session, test_user.id, "rollback-foundation-report")
        payment = await _payment(session, test_user.id)
        report_id = report.id
        payment_id = payment.id
        service = ReportLifecycleService(session)

        with pytest.raises(RuntimeError, match="controlled_lifecycle_flush_failure"):
            await service.confirm_payment_and_prepare_generation(report_id, payment_id)
        await session.rollback()

        assert id(session) == session_id
        assert session.is_active and not session.in_transaction()
        stored = await session.get(Report, report_id)
        jobs = (
            await session.execute(
                select(ReportGenerationJob).where(
                    ReportGenerationJob.report_id == report_id
                )
            )
        ).scalars().all()
        assert stored is not None
        assert stored.payment_id is None
        assert stored.payment_state == ReportPaymentState.AWAITING_PAYMENT
        assert stored.payment_confirmed_at is None
        assert stored.generation_state == ReportGenerationState.NOT_REQUESTED
        assert jobs == []

        retried, job = await service.confirm_payment_and_prepare_generation(
            report_id, payment_id
        )
        await session.commit()
        assert retried.generation_state == ReportGenerationState.PENDING_DISPATCH
        assert job.report_id == report_id
        assert id(session) == session_id
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_report_generation_transitions_are_conditional_and_terminal(
    db_session, test_user
):
    report = await _report(db_session, test_user.id, "report-transition-report")
    payment = await _payment(db_session, test_user.id)
    service = ReportLifecycleService(db_session)
    repository = ReportLifecycleRepository(db_session)
    prepared, job = await service.confirm_payment_and_prepare_generation(report.id, payment.id)
    await db_session.commit()

    with pytest.raises(ValueError, match="invalid_report_generation_transition"):
        repository.mark_report_running(prepared)
    repository.mark_report_queued(prepared)
    await db_session.commit()
    queued_at = prepared.generation_enqueued_at
    repository.mark_report_queued(prepared, datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert prepared.generation_enqueued_at == queued_at
    repository.mark_report_running(prepared)
    await db_session.commit()
    assert prepared.generation_attempts == 1
    repository.mark_report_running(prepared)
    assert prepared.generation_attempts == 1
    repository.mark_report_completed(prepared)
    await db_session.commit()
    completed_at = prepared.generated_at
    repository.mark_report_completed(prepared)
    assert prepared.generated_at == completed_at
    for transition in (
        lambda: repository.mark_report_queued(prepared),
        lambda: repository.mark_report_running(prepared),
        lambda: repository.mark_report_failed_retryable(
            prepared, ReportGenerationErrorCategory.AI_TIMEOUT
        ),
    ):
        with pytest.raises(ValueError, match="invalid_report_generation_transition"):
            transition()

    retryable = await _report(db_session, test_user.id, "retryable-report")
    retry_payment = await _payment(db_session, test_user.id)
    retryable.payment_id = retry_payment.id
    retryable.payment_state = ReportPaymentState.PAYMENT_CONFIRMED
    retryable.payment_confirmed_at = datetime.now(timezone.utc)
    retryable.generation_state = ReportGenerationState.QUEUED
    await db_session.commit()
    unsafe_category = f"SELECT {uuid.uuid4()} report-token traceback"
    with pytest.raises(ValueError, match="invalid_generation_error_category") as error:
        repository.mark_report_failed_retryable(retryable, unsafe_category)
    assert unsafe_category not in str(error.value)
    assert retryable.generation_error_category is None
    repository.mark_report_failed_retryable(
        retryable, ReportGenerationErrorCategory.AI_PROVIDER_UNAVAILABLE
    )
    await db_session.commit()
    attempts_before_retry = retryable.generation_attempts
    repository.retry_report_generation(retryable)
    assert retryable.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert retryable.generation_attempts == attempts_before_retry
    retryable.generation_state = ReportGenerationState.FAILED_RETRYABLE
    repository.mark_report_failed_terminal(
        retryable, ReportGenerationErrorCategory.UNKNOWN_INTERNAL
    )
    await db_session.commit()
    with pytest.raises(ValueError, match="invalid_report_generation_transition"):
        repository.retry_report_generation(retryable)

    unpaid = await _report(db_session, test_user.id, "unpaid-transition-report")
    with pytest.raises(ValueError, match="invalid_report_generation_transition"):
        repository.mark_report_queued(unpaid)
    assert job.state == ReportGenerationJobState.PENDING_DISPATCH


@pytest.mark.asyncio
async def test_job_transitions_and_safe_error_categories(db_session, test_user):
    report = await _report(db_session, test_user.id, "job-transition-report")
    payment = await _payment(db_session, test_user.id)
    service = ReportLifecycleService(db_session)
    _, job = await service.confirm_payment_and_prepare_generation(report.id, payment.id)
    await db_session.commit()
    repository = ReportGenerationJobRepository(db_session)

    repository.claim_dispatch(job)
    await db_session.commit()
    claimed_at = job.claimed_at
    repository.claim_dispatch(job)
    assert job.claimed_at == claimed_at
    repository.mark_job_queued(job, "celery-task-1")
    await db_session.commit()
    assert job.attempts == 1
    repository.mark_job_queued(job, "celery-task-1")
    assert job.attempts == 1
    with pytest.raises(ValueError, match="generation_job_task_conflict"):
        repository.mark_job_queued(job, "celery-task-2")
    repository.mark_job_completed(job)
    await db_session.commit()
    repository.mark_job_completed(job)
    with pytest.raises(ValueError, match="invalid_generation_job_transition"):
        repository.claim_dispatch(job)

    retry_job = ReportGenerationJob(
        id=uuid.uuid4(),
        report_id=report.id,
        job_type="retry-dispatch",
        state=ReportGenerationJobState.DISPATCHING,
    )
    db_session.add(retry_job)
    await db_session.commit()
    next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    repository.mark_job_failed_retryable(
        retry_job,
        ReportGenerationErrorCategory.DISPATCH_FAILED,
        next_attempt_at,
    )
    await db_session.commit()
    attempts_before_retry = retry_job.attempts
    repository.retry_dispatch(retry_job)
    assert retry_job.state == ReportGenerationJobState.PENDING_DISPATCH
    assert retry_job.attempts == attempts_before_retry
    retry_job.state = ReportGenerationJobState.FAILED_RETRYABLE
    repository.mark_job_failed_terminal(
        retry_job, ReportGenerationErrorCategory.UNKNOWN_INTERNAL
    )
    await db_session.commit()
    with pytest.raises(ValueError, match="invalid_generation_job_transition"):
        repository.retry_dispatch(retry_job)

    unsafe = ReportGenerationJob(
        id=uuid.uuid4(),
        report_id=report.id,
        job_type="unsafe-category",
        state=ReportGenerationJobState.DISPATCHING,
    )
    db_session.add(unsafe)
    await db_session.commit()
    unsafe_value = f"SELECT {uuid.uuid4()} report-token traceback"
    with pytest.raises(ValueError, match="invalid_generation_error_category") as error:
        repository.mark_job_failed_retryable(
            unsafe, unsafe_value, datetime.now(timezone.utc)
        )
    assert unsafe_value not in str(error.value)
    assert unsafe.last_error_category is None


@pytest.mark.asyncio
async def test_paired_report_job_transitions_are_atomic_and_isolated(
    db_session, test_user
):
    report = await _report(db_session, test_user.id, "paired-transition-report")
    other_report = await _report(db_session, test_user.id, "other-paired-report")
    payment = await _payment(db_session, test_user.id)
    other_payment = await _payment(db_session, test_user.id)
    service = ReportLifecycleService(db_session)
    _, job = await service.confirm_payment_and_prepare_generation(report.id, payment.id)
    _, other_job = await service.confirm_payment_and_prepare_generation(
        other_report.id, other_payment.id
    )
    await db_session.commit()

    jobs = ReportGenerationJobRepository(db_session)
    jobs.claim_dispatch(job)
    await db_session.commit()
    queued_report, queued_job = await service.mark_generation_queued(
        report.id, "paired-task"
    )
    await db_session.commit()
    assert queued_report.generation_state == ReportGenerationState.QUEUED
    assert queued_job.state == ReportGenerationJobState.QUEUED
    assert other_job.state == ReportGenerationJobState.PENDING_DISPATCH

    reports = ReportLifecycleRepository(db_session)
    reports.mark_report_running(queued_report)
    await db_session.commit()
    completed_report, completed_job = await service.mark_generation_completed(report.id)
    await db_session.commit()
    assert completed_report.generation_state == ReportGenerationState.COMPLETED
    assert completed_job.state == ReportGenerationJobState.COMPLETED

    other_report_id = other_report.id
    with pytest.raises(ValueError, match="invalid_generation_job_transition"):
        await service.mark_generation_queued(other_report.id, "wrong-job-state")
    await db_session.rollback()
    untouched_other = await reports.get_lifecycle_snapshot(other_report_id)
    assert untouched_other is not None
    assert untouched_other.generation_state == ReportGenerationState.PENDING_DISPATCH
