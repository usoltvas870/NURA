import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import (
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
)
from core.repositories.report_lifecycle import (
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
)
from core.services.report_generation_dispatcher import (
    PublishResult,
    ReportGenerationDispatcher,
    report_generation_task_id,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class FakePublisher:
    def __init__(self, responses: list[PublishResult | Exception]):
        self._responses = deque(responses)
        self.calls: list[tuple[uuid.UUID, uuid.UUID, str]] = []
        self.active_session_count: Callable[[], int] | None = None

    async def publish(
        self, *, job_id: uuid.UUID, report_id: uuid.UUID, task_id: str
    ) -> PublishResult:
        if self.active_session_count is not None:
            assert self.active_session_count() == 0
        self.calls.append((job_id, report_id, task_id))
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class TrackingSessionFactory:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory
        self.active_session_count = 0

    def __call__(self):
        factory = self
        session_context = self._session_factory()

        class _TrackedSessionContext:
            async def __aenter__(self):
                session = await session_context.__aenter__()
                factory.active_session_count += 1
                return session

            async def __aexit__(self, exc_type, exc, traceback):
                factory.active_session_count -= 1
                return await session_context.__aexit__(exc_type, exc, traceback)

        return _TrackedSessionContext()


class FailQueuedCommitSession(AsyncSession):
    fail_next_queued_flush = True

    async def flush(self, objects=None) -> None:
        await super().flush(objects)
        has_queued_transition = any(
            (
                isinstance(instance, Report)
                and instance.generation_state == ReportGenerationState.QUEUED
            )
            or (
                isinstance(instance, ReportGenerationJob)
                and instance.state == ReportGenerationJobState.QUEUED
            )
            for instance in self.sync_session.identity_map.values()
        )
        if type(self).fail_next_queued_flush and has_queued_transition:
            type(self).fail_next_queued_flush = False
            raise RuntimeError("simulated_commit_failure")


async def _create_paid_pending_job(
    session: AsyncSession, user_id: uuid.UUID, token: str
) -> tuple[Report, ReportGenerationJob]:
    payment = Payment(
        id=uuid.uuid4(), user_id=user_id, amount=890, payment_type="web_matrix"
    )
    report = Report(
        id=uuid.uuid4(),
        user_id=user_id,
        report_type="full",
        token=token,
        payment_id=payment.id,
        payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
        payment_confirmed_at=_now(),
        generation_state=ReportGenerationState.PENDING_DISPATCH,
    )
    job = ReportGenerationJob(
        id=uuid.uuid4(),
        report_id=report.id,
        job_type="full_report",
        state=ReportGenerationJobState.PENDING_DISPATCH,
    )
    session.add_all([payment, report, job])
    await session.commit()
    return report, job


async def _snapshots(
    session_factory: async_sessionmaker, report_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Report, ReportGenerationJob]:
    async with session_factory() as session:
        report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        assert report is not None
        assert job is not None
        return report, job


@pytest.mark.asyncio
async def test_dispatcher_publishes_outside_transaction_and_uses_stable_safe_task_id(
    db_engine, db_session, test_user, caplog
):
    first_report, first_job = await _create_paid_pending_job(
        db_session, test_user.id, "dispatcher-success-first"
    )
    second_report, second_job = await _create_paid_pending_job(
        db_session, test_user.id, "dispatcher-success-second"
    )
    base_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    factory = TrackingSessionFactory(base_factory)
    publisher = FakePublisher([PublishResult.accepted(), PublishResult.accepted()])
    publisher.active_session_count = lambda: factory.active_session_count
    dispatcher = ReportGenerationDispatcher(factory, publisher)
    now = _now()

    result = await dispatcher.dispatch_batch(now=now, limit=10)

    assert result.selected == result.claimed == result.published == 2
    assert result.retryable_failed == result.terminal_failed == result.claim_conflicts == 0
    assert {call[0] for call in publisher.calls} == {first_job.id, second_job.id}
    assert all(call[2].startswith("nura-report-v1-") for call in publisher.calls)
    assert all(str(call[0]) not in call[2] for call in publisher.calls)
    assert all(str(call[1]) not in call[2] for call in publisher.calls)
    assert all(report_generation_task_id(call[0]) == call[2] for call in publisher.calls)
    assert report_generation_task_id(first_job.id) == report_generation_task_id(first_job.id)
    assert publisher.calls[0][2] != publisher.calls[1][2]

    task_ids_by_job_id = {job_id: task_id for job_id, _, task_id in publisher.calls}
    for report_id, job_id in (
        (first_report.id, first_job.id),
        (second_report.id, second_job.id),
    ):
        report, job = await _snapshots(base_factory, report_id, job_id)
        assert report.generation_state == ReportGenerationState.QUEUED
        assert job.state == ReportGenerationJobState.QUEUED
        assert job.celery_task_id == task_ids_by_job_id[job_id]
        assert job.attempts == 1
        assert job.published_at is not None

    assert (await dispatcher.dispatch_batch(now=now, limit=10)).selected == 0
    assert len(publisher.calls) == 2
    assert "dispatcher-success" not in caplog.text


@pytest.mark.asyncio
async def test_dispatcher_continues_batch_for_retryable_terminal_and_success(
    db_engine, db_session, test_user
):
    reports_and_jobs = [
        await _create_paid_pending_job(db_session, test_user.id, f"dispatcher-batch-{i}")
        for i in range(3)
    ]
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    publisher = FakePublisher(
        [
            PublishResult.accepted(),
            PublishResult.retryable(ReportGenerationErrorCategory.DISPATCH_FAILED),
            PublishResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL),
        ]
    )
    dispatcher = ReportGenerationDispatcher(factory, publisher)
    now = _now()

    result = await dispatcher.dispatch_batch(now=now, limit=10)

    assert (result.selected, result.claimed, result.published) == (3, 3, 1)
    assert (result.retryable_failed, result.terminal_failed) == (1, 1)
    reports_by_job_id = {job.id: report for report, job in reports_and_jobs}
    queued_report, queued_job = await _snapshots(
        factory, reports_by_job_id[publisher.calls[0][0]].id, publisher.calls[0][0]
    )
    retry_report, retry_job = await _snapshots(
        factory, reports_by_job_id[publisher.calls[1][0]].id, publisher.calls[1][0]
    )
    terminal_report, terminal_job = await _snapshots(
        factory, reports_by_job_id[publisher.calls[2][0]].id, publisher.calls[2][0]
    )
    assert queued_report.generation_state == ReportGenerationState.QUEUED
    assert queued_job.state == ReportGenerationJobState.QUEUED
    assert retry_report.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert retry_job.state == ReportGenerationJobState.FAILED_RETRYABLE
    assert _as_utc(retry_job.next_attempt_at) == now + timedelta(seconds=30)
    assert retry_job.attempts == 1
    assert terminal_report.generation_state == ReportGenerationState.FAILED_TERMINAL
    assert terminal_job.state == ReportGenerationJobState.FAILED_TERMINAL
    assert terminal_job.attempts == 1


@pytest.mark.asyncio
async def test_dispatcher_timeout_uses_backoff_and_reuses_task_id_on_retry(
    db_engine, db_session, test_user
):
    report, job = await _create_paid_pending_job(
        db_session, test_user.id, "dispatcher-timeout"
    )
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    publisher = FakePublisher([TimeoutError("publisher timeout")])
    dispatcher = ReportGenerationDispatcher(factory, publisher)
    now = _now()

    assert (await dispatcher.dispatch_batch(now=now, limit=1)).retryable_failed == 1
    _, failed_job = await _snapshots(factory, report.id, job.id)
    assert failed_job.state == ReportGenerationJobState.FAILED_RETRYABLE
    assert _as_utc(failed_job.next_attempt_at) == now + timedelta(seconds=30)
    assert failed_job.last_error_category == ReportGenerationErrorCategory.DISPATCH_FAILED

    retry_publisher = FakePublisher([PublishResult.accepted()])
    retry_dispatcher = ReportGenerationDispatcher(factory, retry_publisher)
    assert (
        await retry_dispatcher.dispatch_batch(
            now=failed_job.next_attempt_at, limit=1
        )
    ).published == 1
    _, queued_job = await _snapshots(factory, report.id, job.id)
    assert queued_job.celery_task_id == publisher.calls[0][2]
    assert queued_job.celery_task_id == retry_publisher.calls[0][2]
    assert queued_job.attempts == 2


@pytest.mark.asyncio
async def test_crashed_claim_is_recovered_then_dispatched_with_same_task_id(
    db_engine, db_session, test_user
):
    report, job = await _create_paid_pending_job(
        db_session, test_user.id, "dispatcher-crashed-claim"
    )
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    claimed_at = _now()
    async with factory() as session:
        repository = ReportGenerationJobRepository(session)
        assert await repository.claim_job_for_dispatch(job.id, claimed_at) == "claimed"
        await session.commit()
    async with factory() as session:
        recovered = await ReportGenerationJobRepository(
            session
        ).mark_stale_dispatch_claim_retryable(
            job.id,
            claimed_at + timedelta(seconds=1),
            claimed_at + timedelta(seconds=2),
            claimed_at + timedelta(seconds=32),
        )
        assert recovered
        await session.commit()

    publisher = FakePublisher([PublishResult.accepted()])
    result = await ReportGenerationDispatcher(factory, publisher).dispatch_batch(
        now=claimed_at + timedelta(seconds=32), limit=1
    )
    assert result.published == 1
    _, queued_job = await _snapshots(factory, report.id, job.id)
    assert queued_job.celery_task_id == report_generation_task_id(job.id)
    assert len(publisher.calls) == 1


@pytest.mark.asyncio
async def test_accepted_publish_commit_failure_leaves_recoverable_claim(
    db_engine, db_session, test_user
):
    report, job = await _create_paid_pending_job(
        db_session, test_user.id, "dispatcher-commit-failure"
    )
    normal_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    FailQueuedCommitSession.fail_next_queued_flush = True
    failing_factory = async_sessionmaker(
        db_engine, class_=FailQueuedCommitSession, expire_on_commit=False
    )
    publisher = FakePublisher([PublishResult.accepted()])
    now = _now()

    result = await ReportGenerationDispatcher(failing_factory, publisher).dispatch_batch(
        now=now, limit=1
    )
    assert (result.published, result.retryable_failed) == (0, 1)
    pending_report, dispatching_job = await _snapshots(normal_factory, report.id, job.id)
    assert pending_report.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert dispatching_job.state == ReportGenerationJobState.DISPATCHING
    assert dispatching_job.celery_task_id is None

    async with normal_factory() as session:
        assert await ReportGenerationJobRepository(
            session
        ).mark_stale_dispatch_claim_retryable(
            job.id,
            now + timedelta(seconds=1),
            now + timedelta(seconds=2),
            now + timedelta(seconds=32),
        )
        await session.commit()
    retry_publisher = FakePublisher([PublishResult.accepted()])
    assert (
        await ReportGenerationDispatcher(normal_factory, retry_publisher).dispatch_batch(
            now=now + timedelta(seconds=32), limit=1
        )
    ).published == 1
    _, queued_job = await _snapshots(normal_factory, report.id, job.id)
    assert queued_job.celery_task_id == publisher.calls[0][2]
    assert queued_job.celery_task_id == retry_publisher.calls[0][2]
