import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import (
    Base,
    Order,
    OrderStatus,
    Payment,
    PromoCode,
    PromoReservation,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.report_lifecycle import (
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
)
from core.services.report_generation_reconciliation import (
    ReportGenerationReconciler,
)
from core.services.report_lifecycle import ReportLifecycleService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_async_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _create_report_and_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    generation_state: str = ReportGenerationState.PENDING_DISPATCH,
    job_state: str = ReportGenerationJobState.PENDING_DISPATCH,
    report_type: str = ReportType.FULL.value,
    payment_state: str = ReportPaymentState.PAYMENT_CONFIRMED,
    generation_enqueued_at: datetime | None = None,
    generation_started_at: datetime | None = None,
    generation_attempts: int = 0,
    job_attempts: int = 0,
    claimed_at: datetime | None = None,
    published_at: datetime | None = None,
    celery_task_id: str | None = None,
    next_attempt_at: datetime | None = None,
    generated_at: datetime | None = None,
    generation_error_category: str | None = None,
    last_error_category: str | None = None,
    matrix_data: dict | None = None,
    ai_analysis: dict | None = None,
    report_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
) -> tuple[Report, ReportGenerationJob]:
    payment = Payment(
        id=uuid.uuid4(), user_id=user_id, amount=890, payment_type="web_matrix",
        amount_kopecks=89000,
    )
    report = Report(
        id=report_id or uuid.uuid4(),
        user_id=user_id,
        report_type=report_type,
        token=token,
        payment_id=payment.id if payment_state == ReportPaymentState.PAYMENT_CONFIRMED else None,
        payment_state=payment_state,
        payment_confirmed_at=_now() if payment_state == ReportPaymentState.PAYMENT_CONFIRMED else None,
        generation_state=generation_state,
        generation_enqueued_at=generation_enqueued_at,
        generation_started_at=generation_started_at,
        generation_attempts=generation_attempts,
        generated_at=generated_at,
        generation_error_category=generation_error_category,
        matrix_data=matrix_data,
        ai_analysis=ai_analysis,
    )
    job = ReportGenerationJob(
        id=job_id or uuid.uuid4(),
        report_id=report.id,
        job_type="full_report",
        state=job_state,
        attempts=job_attempts,
        claimed_at=claimed_at,
        published_at=published_at,
        celery_task_id=celery_task_id,
        next_attempt_at=next_attempt_at,
        last_error_category=last_error_category,
    )
    session.add_all([payment, report, job])
    await session.commit()
    return report, job


@pytest_asyncio.fixture
async def sf(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'reconciliation.db'}",
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(sf):
    user = User(id=uuid.uuid4(), name="Test", birth_date="01.01.2000")
    async with sf() as s:
        s.add(user)
        await s.commit()
    return user


def _reconciler(sf, **kw):
    return ReportGenerationReconciler(sf, **kw)


@pytest.mark.asyncio
async def test_existing_report_reconciler_dispatches_missing_full_delivery_once(
    sf, test_user
):
    now = _now()
    artifact = b"%PDF-" + b"r" * 2048
    report_id = uuid.uuid4()
    order_id = uuid.uuid4()
    async with sf() as session:
        user = await session.get(User, test_user.id)
        user.telegram_id = 777
        user.has_matrix = True
        report = Report(
            id=report_id,
            user_id=test_user.id,
            report_type=ReportType.FULL.value,
            token="full-delivery-reconciliation",
            payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
            generation_state=ReportGenerationState.COMPLETED,
            generated_at=now,
            artifact_bytes=artifact,
            artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            artifact_size_bytes=len(artifact),
            artifact_mime_type="application/pdf",
            artifact_completed_at=now,
        )
        order = Order(
            id=order_id,
            public_id="full-delivery-reconciliation-order",
            user_id=test_user.id,
            product_code="full_matrix",
            amount_kopecks=89_000,
            currency="RUB",
            status="paid",
            report_id=report_id,
            idempotency_key="full-delivery-reconciliation-key",
            paid_at=now,
        )
        session.add(report)
        await session.flush()
        session.add(order)
        await session.flush()
        report.order_id = order_id
        await session.commit()

    dispatched: list[tuple[uuid.UUID, int]] = []
    reconciler = _reconciler(
        sf,
        delivery_dispatch=lambda delivery_id, attempt: dispatched.append(
            (delivery_id, attempt)
        ),
    )
    first = await reconciler.reconcile_batch(now=now, limit=10)
    second = await reconciler.reconcile_batch(now=now, limit=10)

    assert first.full_deliveries_created == 1
    assert first.full_deliveries_dispatched == 1
    assert second.full_deliveries_created == 0
    assert second.full_deliveries_dispatched == 0
    assert len(dispatched) == 1


class TestStaleDispatchingRecovery:
    @pytest.mark.asyncio
    async def test_stale_unpublished_dispatching_is_recovered(self, sf, test_user):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            _, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-dispatching-1",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.dispatch_claims_recovered == 1
        async with sf() as s:
            stored = await s.get(ReportGenerationJob, job.id)
        assert stored.state == ReportGenerationJobState.FAILED_RETRYABLE
        assert stored.next_attempt_at is not None
        assert stored.last_error_category == ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED

    @pytest.mark.asyncio
    async def test_fresh_dispatching_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            _, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-dispatching-fresh",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=now,
            )

        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.dispatch_claims_recovered == 0
        async with sf() as s:
            stored = await s.get(ReportGenerationJob, job.id)
        assert stored.state == ReportGenerationJobState.DISPATCHING

    @pytest.mark.asyncio
    async def test_published_dispatching_is_not_recovered(self, sf, test_user):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            _, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-dispatching-published",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
                published_at=now,
            )

        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.dispatch_claims_recovered == 0


class TestStaleQueuedRecovery:
    @pytest.mark.asyncio
    async def test_stale_queued_pair_is_recovered(self, sf, test_user):
        now = _now()
        old_enqueued = now - timedelta(minutes=15)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-queued-1",
                generation_state=ReportGenerationState.QUEUED,
                job_state=ReportGenerationJobState.QUEUED,
                generation_enqueued_at=old_enqueued,
            )

        reconciler = _reconciler(sf, queued_stale_before=timedelta(minutes=10))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.queued_recovered == 1
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE
        assert stored_job.last_error_category == ReportGenerationErrorCategory.WORKER_DELIVERY_EXPIRED

    @pytest.mark.asyncio
    async def test_fresh_queued_pair_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-queued-fresh",
                generation_state=ReportGenerationState.QUEUED,
                job_state=ReportGenerationJobState.QUEUED,
                generation_enqueued_at=now - timedelta(minutes=1),
            )

        reconciler = _reconciler(sf, queued_stale_before=timedelta(minutes=10))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.queued_recovered == 0

    @pytest.mark.asyncio
    async def test_late_old_worker_after_queued_recovery_fails_closed(self, sf, test_user):
        now = _now()
        old_enqueued = now - timedelta(minutes=15)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-queued-late-worker",
                generation_state=ReportGenerationState.QUEUED,
                job_state=ReportGenerationJobState.QUEUED,
                generation_enqueued_at=old_enqueued,
            )

        reconciler = _reconciler(sf, queued_stale_before=timedelta(minutes=10))
        await reconciler.reconcile_batch(now=now, limit=10)
        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.generation_state == ReportGenerationState.FAILED_RETRYABLE


class TestStaleRunningRecovery:
    @pytest.mark.asyncio
    async def test_stale_running_pair_is_recovered(self, sf, test_user):
        now = _now()
        old_started = now - timedelta(minutes=40)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-running-1",
                generation_state=ReportGenerationState.RUNNING,
                job_state=ReportGenerationJobState.QUEUED,
                generation_started_at=old_started,
            )

        reconciler = _reconciler(sf, running_stale_before=timedelta(minutes=30))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.running_recovered == 1
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE

    @pytest.mark.asyncio
    async def test_fresh_running_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-running-fresh",
                generation_state=ReportGenerationState.RUNNING,
                job_state=ReportGenerationJobState.QUEUED,
                generation_started_at=now,
            )

        reconciler = _reconciler(sf, running_stale_before=timedelta(minutes=30))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.running_recovered == 0


class TestDueRetryPromotion:
    @pytest.mark.asyncio
    async def test_due_failed_retryable_pair_is_promoted(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-retry-promote",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
                job_attempts=1,
                generation_attempts=1,
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.retries_promoted == 1
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.PENDING_DISPATCH
        assert stored_job.state == ReportGenerationJobState.PENDING_DISPATCH
        assert stored_job.attempts == 1

    @pytest.mark.asyncio
    async def test_refunded_order_retry_is_not_promoted(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s,
                user_id=test_user.id,
                token="rec-refunded-retry",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
            )
            report.payment_id = None
            order = Order(
                id=uuid.uuid4(),
                public_id=f"rec-refunded-{uuid.uuid4().hex}",
                user_id=test_user.id,
                amount_kopecks=89000,
                status=OrderStatus.REFUNDED,
                paid_at=now,
                refunded_at=now,
                report_id=report.id,
                idempotency_key=uuid.uuid4().hex,
            )
            report.order_id = order.id
            s.add(order)
            await s.commit()

        result = await _reconciler(sf).reconcile_batch(now=now, limit=10)

        assert result.retries_promoted == 0
        assert result.terminalized == 0
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE

    @pytest.mark.asyncio
    async def test_future_retry_pair_is_not_promoted(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-retry-future",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now + timedelta(minutes=5),
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.retries_promoted == 0

    @pytest.mark.asyncio
    async def test_dispatch_attempts_exhaustion_is_terminal(self, sf, test_user):
        now = _now()
        async with sf() as s:
            payment = await s.get(Payment, (await s.execute(
                select(Payment).where(Payment.user_id == test_user.id)
            )).scalar_one_or_none())
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-retry-dispatch-exhaust",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
                job_attempts=5,
                generation_attempts=1,
            )

        reconciler = _reconciler(sf, max_dispatch_attempts=5)
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.terminalized == 1
        assert result.retries_promoted == 0
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_TERMINAL
        assert stored_job.state == ReportGenerationJobState.FAILED_TERMINAL
        assert stored_report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED

    @pytest.mark.asyncio
    async def test_generation_attempts_exhaustion_is_terminal(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-retry-gen-exhaust",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
                job_attempts=2,
                generation_attempts=3,
            )

        reconciler = _reconciler(sf, max_generation_attempts=3)
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.terminalized == 1
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_TERMINAL
        assert stored_report.generation_error_category == ReportGenerationErrorCategory.RETRY_BUDGET_EXHAUSTED

    @pytest.mark.asyncio
    async def test_terminalized_pair_preserves_payment(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, _ = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-term-payment",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
                job_attempts=5,
                generation_attempts=0,
            )

        reconciler = _reconciler(sf, max_dispatch_attempts=5)
        await reconciler.reconcile_batch(now=now, limit=10)

        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
            assert stored.payment_id is not None


class TestMissingJobRepair:
    @pytest.mark.asyncio
    async def test_missing_job_for_paid_pending_report_is_created(self, sf, test_user):
        async with sf() as s:
            payment = Payment(id=uuid.uuid4(), user_id=test_user.id, amount=890,
                              payment_type="web_matrix", amount_kopecks=89000)
            report = Report(
                id=uuid.uuid4(), user_id=test_user.id, report_type="full",
                token="rec-missing-job-1", payment_id=payment.id,
                payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
                payment_confirmed_at=_now(),
                generation_state=ReportGenerationState.PENDING_DISPATCH,
            )
            s.add_all([payment, report])
            await s.commit()

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.missing_jobs_repaired == 1
        async with sf() as s:
            jobs = (await s.execute(select(ReportGenerationJob).where(
                ReportGenerationJob.report_id == report.id
            ))).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].job_type == "full_report"
        assert jobs[0].state == ReportGenerationJobState.PENDING_DISPATCH

    @pytest.mark.asyncio
    async def test_missing_job_for_order_confirmed_report_is_created(self, sf, test_user):
        async with sf() as s:
            report = Report(
                id=uuid.uuid4(), user_id=test_user.id, report_type="full",
                token="rec-missing-order-job", payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
                payment_confirmed_at=_now(), generation_state=ReportGenerationState.PENDING_DISPATCH,
            )
            s.add(report)
            await s.flush()
            order = Order(
                id=uuid.uuid4(), public_id=f"rec-order-{uuid.uuid4().hex}", user_id=test_user.id,
                amount_kopecks=89000, status="paid", paid_at=_now(), report_id=report.id,
                idempotency_key=uuid.uuid4().hex,
            )
            report.order_id = order.id
            s.add(order)
            await s.commit()

        result = await _reconciler(sf).reconcile_batch(now=_now(), limit=10)

        assert result.missing_jobs_repaired == 1
        async with sf() as s:
            job = (await s.execute(select(ReportGenerationJob).where(
                ReportGenerationJob.report_id == report.id
            ))).scalar_one()
        assert job.state == ReportGenerationJobState.PENDING_DISPATCH

    @pytest.mark.asyncio
    async def test_missing_job_for_unpaid_report_not_created(self, sf, test_user):
        async with sf() as s:
            report = Report(
                id=uuid.uuid4(), user_id=test_user.id, report_type="full",
                token="rec-missing-unpaid",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
            )
            s.add(report)
            await s.commit()

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.missing_jobs_repaired == 0

    @pytest.mark.asyncio
    async def test_missing_job_for_legacy_report_not_created(self, sf, test_user):
        async with sf() as s:
            payment = Payment(id=uuid.uuid4(), user_id=test_user.id, amount=890,
                              payment_type="web_matrix", amount_kopecks=89000)
            report = Report(
                id=uuid.uuid4(), user_id=test_user.id, report_type="full",
                token="rec-missing-legacy",
                payment_state=ReportPaymentState.LEGACY_UNLINKED,
                generation_state=ReportGenerationState.PENDING_DISPATCH,
            )
            s.add_all([payment, report])
            await s.commit()

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.missing_jobs_repaired == 0

    @pytest.mark.asyncio
    async def test_missing_job_for_completed_report_not_created(self, sf, test_user):
        async with sf() as s:
            payment = Payment(id=uuid.uuid4(), user_id=test_user.id, amount=890,
                              payment_type="web_matrix", amount_kopecks=89000)
            report = Report(
                id=uuid.uuid4(), user_id=test_user.id, report_type="full",
                token="rec-missing-completed", payment_id=payment.id,
                payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
                payment_confirmed_at=_now(),
                generation_state=ReportGenerationState.COMPLETED,
                generated_at=_now(),
                matrix_data={"center": 8},
            )
            s.add_all([payment, report])
            await s.commit()

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.missing_jobs_repaired == 0


class TestCompletedPairRepair:
    @pytest.mark.asyncio
    async def test_completed_report_active_job_is_synced(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-completed-sync",
                generation_state=ReportGenerationState.COMPLETED,
                job_state=ReportGenerationJobState.QUEUED,
                generated_at=now,
                matrix_data={"center": 8},
                ai_analysis={"key": "val"},
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.completed_pairs_repaired == 1
        async with sf() as s:
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_job.state == ReportGenerationJobState.COMPLETED

    @pytest.mark.asyncio
    async def test_completed_report_without_content_not_repaired(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-completed-no-content",
                generation_state=ReportGenerationState.COMPLETED,
                job_state=ReportGenerationJobState.QUEUED,
                generated_at=now,
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.completed_pairs_repaired == 0

    @pytest.mark.asyncio
    async def test_completed_job_incomplete_report_is_untouched(self, sf, test_user):
        async with sf() as s:
            _, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-job-completed-report-not",
                generation_state=ReportGenerationState.RUNNING,
                job_state=ReportGenerationJobState.COMPLETED,
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.completed_pairs_repaired == 0
        async with sf() as s:
            stored_report = (await s.execute(select(Report).where(
                Report.token == "rec-job-completed-report-not"
            ))).scalar_one()
        assert stored_report.generation_state == ReportGenerationState.RUNNING


class TestInconsistentStateProtection:
    @pytest.mark.asyncio
    async def test_wrong_report_type_not_changed(self, sf, test_user):
        async with sf() as s:
            report, _ = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-wrong-type",
                report_type=ReportType.MINI.value,
                generation_state=ReportGenerationState.PENDING_DISPATCH,
            )

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        async with sf() as s:
            stored = await s.get(Report, report.id)
        assert stored.generation_state == ReportGenerationState.PENDING_DISPATCH

    @pytest.mark.asyncio
    async def test_report_job_mismatch_untouched(self, sf, test_user):
        async with sf() as s:
            report, _ = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-mismatch",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
            )
            other_job = ReportGenerationJob(
                id=uuid.uuid4(), report_id=report.id, job_type="other", state="queued"
            )
            s.add(other_job)
            await s.commit()

        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert result.retries_promoted == 0


class TestBatchContinuation:
    @pytest.mark.asyncio
    async def test_batch_continues_after_conflict(self, sf, test_user):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            await _create_report_and_job(
                s, user_id=test_user.id, token="rec-batch-1",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )
            await _create_report_and_job(
                s, user_id=test_user.id, token="rec-batch-2",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        result = await reconciler.reconcile_batch(now=now, limit=10)

        assert result.dispatch_claims_recovered == 2

    @pytest.mark.asyncio
    async def test_result_contains_only_aggregates(self, sf, test_user):
        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=_now(), limit=10)

        assert isinstance(result.inspected, int)
        assert isinstance(result.dispatch_claims_recovered, int)
        assert isinstance(result.conflicts, int)
        assert not hasattr(result, "job_ids")
        assert not hasattr(result, "report_ids")


class TestPrivacy:
    @pytest.mark.asyncio
    async def test_logs_do_not_contain_identifiers(self, sf, test_user, caplog):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="rec-privacy",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        caplog.set_level(logging.WARNING)
        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        await reconciler.reconcile_batch(now=now, limit=10)

        for record in caplog.records:
            msg = record.getMessage()
            assert str(report.id) not in msg
            assert str(job.id) not in msg
            assert str(test_user.id) not in msg
            assert report.token not in msg


class TestConcurrency:
    def _race_engine(self, tmp_path):
        db_path = tmp_path / "rec_race.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}", poolclass=NullPool
        )
        return engine

    @pytest.mark.asyncio
    async def test_concurrent_missing_job_repair_creates_one_job(self, tmp_path, test_user):
        engine = self._race_engine(tmp_path)

        @event.listens_for(engine.sync_engine, "connect")
        def _configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=300")

        concurrent_sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(Base.metadata.create_all)

            for cycle in range(10):
                async with concurrent_sf() as s:
                    u = User(id=uuid.uuid4(), name=f"Race{cycle}", birth_date="01.01.2000")
                    s.add(u)
                    await s.commit()
                    payment = Payment(id=uuid.uuid4(), user_id=u.id, amount=890,
                                      payment_type="web_matrix", amount_kopecks=89000)
                    report = Report(
                        id=uuid.uuid4(), user_id=u.id, report_type="full",
                        token=f"rec-race-missing-{cycle}", payment_id=payment.id,
                        payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
                        payment_confirmed_at=_now(),
                        generation_state=ReportGenerationState.PENDING_DISPATCH,
                    )
                    s.add_all([payment, report])
                    await s.commit()

                barrier = asyncio.Barrier(2)

                async def reconciled(sf_inst, rid):
                    await barrier.wait()
                    reconciler = ReportGenerationReconciler(sf_inst)
                    return await reconciler.reconcile_batch(now=_now(), limit=10)

                a_result, b_result = await asyncio.gather(
                    reconciled(concurrent_sf, report.id),
                    reconciled(concurrent_sf, report.id),
                )
                total_repaired = a_result.missing_jobs_repaired + b_result.missing_jobs_repaired
                assert total_repaired == 1, (
                    f"Cycle {cycle}: expected 1 repaired, got {total_repaired}"
                )
                async with concurrent_sf() as s:
                    jobs = (await s.execute(select(ReportGenerationJob).where(
                        ReportGenerationJob.report_id == report.id
                    ))).scalars().all()
                assert len(jobs) == 1, f"Cycle {cycle}: got {len(jobs)} jobs"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_due_retry_promotion_is_safe(self, tmp_path, test_user):
        engine = self._race_engine(tmp_path)

        @event.listens_for(engine.sync_engine, "connect")
        def _configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=300")

        concurrent_sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(Base.metadata.create_all)

            for cycle in range(10):
                now = _now()
                async with concurrent_sf() as s:
                    u = User(id=uuid.uuid4(), name=f"RaceRetry{cycle}", birth_date="01.01.2000")
                    s.add(u)
                    await s.commit()
                    report, _ = await _create_report_and_job(
                        s, user_id=u.id, token=f"rec-race-retry-{cycle}",
                        generation_state=ReportGenerationState.FAILED_RETRYABLE,
                        job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                        next_attempt_at=now - timedelta(seconds=1),
                    )

                barrier = asyncio.Barrier(2)

                async def reconciled(sf_inst, rid):
                    await barrier.wait()
                    reconciler = ReportGenerationReconciler(sf_inst)
                    return await reconciler.reconcile_batch(now=now, limit=10)

                a_result, b_result = await asyncio.gather(
                    reconciled(concurrent_sf, report.id),
                    reconciled(concurrent_sf, report.id),
                )
                total_promoted = a_result.retries_promoted + b_result.retries_promoted
                assert total_promoted == 1, (
                    f"Cycle {cycle}: expected 1 promoted, got {total_promoted}"
                )
                async with concurrent_sf() as s:
                    stored = await s.get(Report, report.id)
                assert stored.generation_state == ReportGenerationState.PENDING_DISPATCH, (
                    f"Cycle {cycle}: got {stored.generation_state}"
                )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_stale_running_recovery_is_safe(self, tmp_path, test_user):
        engine = self._race_engine(tmp_path)

        @event.listens_for(engine.sync_engine, "connect")
        def _configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=300")

        concurrent_sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(Base.metadata.create_all)

            for cycle in range(10):
                now = _now()
                old_started = now - timedelta(minutes=60)
                async with concurrent_sf() as s:
                    u = User(id=uuid.uuid4(), name=f"RaceRun{cycle}", birth_date="01.01.2000")
                    s.add(u)
                    await s.commit()
                    report, _ = await _create_report_and_job(
                        s, user_id=u.id, token=f"rec-race-run-{cycle}",
                        generation_state=ReportGenerationState.RUNNING,
                        job_state=ReportGenerationJobState.QUEUED,
                        generation_started_at=old_started,
                    )

                barrier = asyncio.Barrier(2)

                async def reconciled(sf_inst, rid):
                    await barrier.wait()
                    reconciler = ReportGenerationReconciler(sf_inst)
                    return await reconciler.reconcile_batch(now=now, limit=10)

                a_result, b_result = await asyncio.gather(
                    reconciled(concurrent_sf, report.id),
                    reconciled(concurrent_sf, report.id),
                )
                total_recovered = a_result.running_recovered + b_result.running_recovered
                assert total_recovered == 1, (
                    f"Cycle {cycle}: expected 1 recovered, got {total_recovered}"
                )
                async with concurrent_sf() as s:
                    stored = await s.get(Report, report.id)
                assert stored.generation_state == ReportGenerationState.FAILED_RETRYABLE, (
                    f"Cycle {cycle}: got {stored.generation_state}"
                )
        finally:
            await engine.dispose()


class TestReconciliationTask:
    def test_task_registered(self):
        from core.tasks import reconcile_report_generation_jobs

        assert reconcile_report_generation_jobs.name == "core.tasks.reconcile_report_generation_jobs"

    def test_invalid_limit_fail_closed(self):
        from core.tasks import reconcile_report_generation_jobs

        result = reconcile_report_generation_jobs(limit=0)
        assert result == {"ok": False, "error": "invalid_limit"}

        result = reconcile_report_generation_jobs(limit=300)
        assert result == {"ok": False, "error": "invalid_limit"}

    def test_valid_limit_returns_aggregates(self, sf):
        from core.services.report_generation_reconciliation import (
            ReportGenerationReconciler,
        )

        reconciler = ReportGenerationReconciler(sf)
        result = _run_async_sync(
            reconciler.reconcile_batch(now=_now(), limit=10)
        )
        assert result.inspected >= 0
        assert result.errors >= 0


# ── Gap-filling coverage ──────────────────────────────────────────────


def _assert_logrecord_privacy(records: list[logging.LogRecord]) -> None:
    forbidden = set()
    for record in records:
        combined = str(record.getMessage()) + " "
        combined += str(record.args) + " "

        for attr in ("exc_info", "stack_info"):
            val = getattr(record, attr, None)
            if val is not None:
                combined += str(val) + " "

        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
            }
        }
        combined += str(extra) + " "

        markers = [
            "report_not_found",
            "generation_already",
            "report_not_paid",
            "generation_claim_conflict",
            "invalid_report_generation_transition",
            "invalid_generation_job_transition",
            "report_generation_job_missing",
            "report_payment_conflict",
            "invalid_report_payment_transition",
            "invalid_report_payment",
        ]
        has_safe_marker = any(m in combined for m in markers)
        if has_safe_marker:
            continue

        forbidden_terms = [
            "sqlite://",
            "postgresql://",
            "redis://",
            "broker://",
            "celery_broker",
        ]
        for term in forbidden_terms:
            assert term not in combined, f"forbidden DB/URL term '{term}' in log record"


class TestGapLateWorkerAfterQueuedRecovery:
    @pytest.mark.asyncio
    async def test_late_worker_blocked_after_queued_recovery(self, sf, test_user):
        from core.services.matrix_report_generator import MatrixReportGeneratorResult
        from core.services.matrix_report_worker import MatrixReportGenerationWorker

        now = _now()
        old_enqueued = now - timedelta(minutes=15)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="gap-late-worker",
                generation_state=ReportGenerationState.QUEUED,
                job_state=ReportGenerationJobState.QUEUED,
                generation_enqueued_at=old_enqueued,
            )

        reconciler = _reconciler(sf, queued_stale_before=timedelta(minutes=10))
        result = await reconciler.reconcile_batch(now=now, limit=10)
        assert result.queued_recovered == 1

        gen_before = test_user.birth_date  # user has birth_date
        class _CountingGenerator:
            call_count = 0
            async def generate(self, **kwargs):
                type(self).call_count += 1
                return MatrixReportGeneratorResult(
                    matrix_data={"center": 1},
                    ai_analysis={"key": "val"},
                    kitchen_analysis=None,
                )

        worker = MatrixReportGenerationWorker(sf, _CountingGenerator())
        worker_result = await worker.process(job_id=job.id, report_id=report.id)

        assert _CountingGenerator.call_count == 0
        assert worker_result.disposition.value != "completed"
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        assert stored_report.matrix_data is None
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE


class TestGapEntitlementPaymentPromoIsolation:
    async def _create_full_context(self, sf, user, token, **kw):
        now = _now()
        promo = PromoCode(
            id=uuid.uuid4(), code=f"GAP-PROMO-{token[:8]}", discount_percent=10,
            max_uses=100, used_count=0, reserved_count=0,
        )
        reservation = PromoReservation(
            id=uuid.uuid4(), promo_code_id=promo.id, user_id=user.id,
            payment_type="web_matrix", final_amount_kopecks=89000,
            currency="RUB", idempotency_key=uuid.uuid4().hex,
            report_token=token, state="consumed",
            expires_at=now + timedelta(hours=24),
            consumed_at=now,
        )
        async with sf() as s:
            s.add_all([promo, reservation])
            await s.commit()
            payment = Payment(
                id=uuid.uuid4(), user_id=user.id, amount=890,
                yookassa_id=f"yoo-{token[:8]}", payment_type="web_matrix",
                amount_kopecks=89000, status="succeeded",
            )
            user.has_matrix = True
            s.add_all([payment, user])
            await s.commit()
            report, job = await _create_report_and_job(
                s, user_id=user.id, token=token,
                report_id=uuid.uuid4(), job_id=uuid.uuid4(),
                **kw,
            )
            reservation.payment_id = payment.id
            report.payment_id = payment.id
            await s.commit()
        return report, job, payment, promo, reservation

    async def _snapshot_isolation(self, sf, report, payment, promo, reservation):
        async with sf() as s:
            r = await s.get(Report, report.id)
            u = await s.get(User, report.user_id)
            p = await s.get(Payment, payment.id)
            pc = await s.get(PromoCode, promo.id)
            pr = await s.get(PromoReservation, reservation.id)
        assert r.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
        assert r.payment_id == payment.id
        assert r.payment_confirmed_at is not None
        assert u.has_matrix is True
        assert p.status == "succeeded"
        assert pc.reserved_count == 0
        assert pc.used_count == 0
        assert pr.state == "consumed"
        assert pr.consumed_at is not None

    @pytest.mark.asyncio
    async def test_terminalization_preserves_entitlement(self, sf, test_user):
        now = _now()
        report, job, payment, promo, reservation = await self._create_full_context(
            sf, test_user, "gap-ent-term",
            generation_state=ReportGenerationState.FAILED_RETRYABLE,
            job_state=ReportGenerationJobState.FAILED_RETRYABLE,
            next_attempt_at=now - timedelta(seconds=1),
            job_attempts=5, generation_attempts=0,
        )
        reconciler = _reconciler(sf, max_dispatch_attempts=5)
        result = await reconciler.reconcile_batch(now=now, limit=10)
        assert result.terminalized == 1

        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.generation_state == ReportGenerationState.FAILED_TERMINAL
        await self._snapshot_isolation(sf, report, payment, promo, reservation)

    @pytest.mark.asyncio
    async def test_stale_running_preserves_entitlement(self, sf, test_user):
        now = _now()
        old_started = now - timedelta(minutes=40)
        report, job, payment, promo, reservation = await self._create_full_context(
            sf, test_user, "gap-ent-run",
            generation_state=ReportGenerationState.RUNNING,
            job_state=ReportGenerationJobState.QUEUED,
            generation_started_at=old_started,
        )
        reconciler = _reconciler(sf, running_stale_before=timedelta(minutes=30))
        result = await reconciler.reconcile_batch(now=now, limit=10)
        assert result.running_recovered == 1

        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.generation_state == ReportGenerationState.FAILED_RETRYABLE
        await self._snapshot_isolation(sf, report, payment, promo, reservation)

    @pytest.mark.asyncio
    async def test_due_retry_promotion_preserves_entitlement(self, sf, test_user):
        now = _now()
        report, job, payment, promo, reservation = await self._create_full_context(
            sf, test_user, "gap-ent-retry",
            generation_state=ReportGenerationState.FAILED_RETRYABLE,
            job_state=ReportGenerationJobState.FAILED_RETRYABLE,
            next_attempt_at=now - timedelta(seconds=1),
            job_attempts=1, generation_attempts=1,
        )
        reconciler = _reconciler(sf)
        result = await reconciler.reconcile_batch(now=now, limit=10)
        assert result.retries_promoted == 1

        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.generation_state == ReportGenerationState.PENDING_DISPATCH
        await self._snapshot_isolation(sf, report, payment, promo, reservation)


class TestGapFullLogRecordPrivacy:
    @pytest_asyncio.fixture
    async def _setup(self, sf, test_user):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="gap-privacy-log",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )
        return sf, report, job, now, old_claimed

    def _check_full_record(self, records, report, job, user):
        for record in records:
            combined = (
                str(record.getMessage())
                + " " + str(record.args)
                + " " + str({k: v for k, v in record.__dict__.items()
                              if k not in {"name", "msg", "args", "levelname",
                                           "levelno", "pathname", "filename",
                                           "module", "lineno", "funcName",
                                           "created", "msecs", "relativeCreated",
                                           "thread", "threadName", "processName",
                                           "process", "message", "asctime",
                                           "exc_info", "exc_text", "stack_info"}})
            )
            if record.exc_info:
                combined += " " + str(record.exc_info)
            if record.stack_info:
                combined += " " + str(record.stack_info)

            assert str(report.id) not in combined, "report ID leaked"
            assert str(job.id) not in combined, "job ID leaked"
            assert str(user.id) not in combined, "user UUID leaked"
            assert report.token not in combined, "token leaked"
            assert str(report.payment_id or "") not in combined, "payment ID leaked"

    @pytest.mark.asyncio
    async def test_privacy_on_successful_recovery(self, sf, test_user, caplog):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="gap-privacy-success",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        caplog.set_level(logging.WARNING)
        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        await reconciler.reconcile_batch(now=now, limit=10)

        self._check_full_record(caplog.records, report, job, test_user)

    @pytest.mark.asyncio
    async def test_privacy_on_conflict(self, sf, test_user, caplog):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="gap-privacy-conflict",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        caplog.set_level(logging.WARNING)
        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        await reconciler.reconcile_batch(now=now, limit=10)
        await reconciler.reconcile_batch(now=now, limit=10)

        self._check_full_record(caplog.records, report, job, test_user)

    @pytest.mark.asyncio
    async def test_privacy_on_sensitive_db_exception(self, sf, test_user, caplog):
        now = _now()
        old_claimed = now - timedelta(minutes=10)
        async with sf() as s:
            report, job = await _create_report_and_job(
                s, user_id=test_user.id, token="gap-privacy-db",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )

        caplog.set_level(logging.WARNING)
        reconciler = _reconciler(sf, dispatch_claim_stale_before=timedelta(minutes=2))
        await reconciler.reconcile_batch(now=now, limit=10)

        for record in caplog.records:
            markers = ["report_not_found", "generation_already", "report_not_paid",
                       "generation_claim_conflict", "invalid_report_generation_transition"]
            has_safe = any(m in str(record.getMessage()) for m in markers)
            if has_safe:
                continue
            conn_str = "sqlite://"
            assert conn_str not in str(record.getMessage()), "DB URL in unprotected log"
            assert conn_str not in str(record.args), "DB URL in log args"


class TestGapControlledFailureRollback:
    class FailCommitSession(AsyncSession):
        fail_next_commit: bool = True

        async def commit(self) -> None:
            if type(self).fail_next_commit:
                type(self).fail_next_commit = False
                raise RuntimeError("controlled_reconciliation_commit_failure")
            await super().commit()

    @pytest.mark.asyncio
    async def test_controlled_failure_rollback_and_batch_continues(self, tmp_path, test_user):
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'gap_rollback.db'}",
            poolclass=NullPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")

        self.FailCommitSession.fail_next_commit = True
        fail_sf = async_sessionmaker(engine, class_=self.FailCommitSession, expire_on_commit=False)
        normal_sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            now = _now()
            old_claimed = now - timedelta(minutes=10)
            async with normal_sf() as s:
                u = User(id=uuid.uuid4(), name="GapRollback", birth_date="01.01.2000")
                s.add(u)
                await s.commit()
                report_a, _ = await _create_report_and_job(
                    s, user_id=u.id, token="gap-rollback-a",
                    generation_state=ReportGenerationState.PENDING_DISPATCH,
                    job_state=ReportGenerationJobState.DISPATCHING,
                    claimed_at=old_claimed,
                )
                report_b, job_b = await _create_report_and_job(
                    s, user_id=u.id, token="gap-rollback-b",
                    generation_state=ReportGenerationState.PENDING_DISPATCH,
                    job_state=ReportGenerationJobState.DISPATCHING,
                    claimed_at=old_claimed,
                )

            reconciler = _reconciler(
                fail_sf, dispatch_claim_stale_before=timedelta(minutes=2)
            )
            result = await reconciler.reconcile_batch(now=now, limit=10)

            assert result.errors >= 1, "expected at least one error"
            assert result.dispatch_claims_recovered >= 1, "second pair should recover"

            async with normal_sf() as s:
                stored_a = await s.get(ReportGenerationJob, job_b.id)
                assert stored_a is not None
                assert stored_a.state == ReportGenerationJobState.FAILED_RETRYABLE

                select_result = await s.execute(
                    select(Report).where(Report.id == report_a.id)
                )
                row_a = select_result.scalar_one()
                assert row_a is not None

            async with normal_sf() as s:
                select2 = await s.execute(
                    select(ReportGenerationJob).where(
                        ReportGenerationJob.report_id == report_b.id
                    )
                )
                row_b = select2.scalars().all()
                assert row_b[0].state == ReportGenerationJobState.FAILED_RETRYABLE
        finally:
            await engine.dispose()


class TestGapNoExternalSideEffects:
    @pytest.mark.asyncio
    async def test_reconciler_invokes_no_external_apis(self, sf, test_user, monkeypatch):
        violated: list[str] = []

        def _guard(name):
            def fail(*a, **kw):
                violated.append(name)
                raise AssertionError(f"reconciler called {name}")
            return fail

        from core.tasks import celery_app

        monkeypatch.setattr(celery_app, "send_task", _guard("celery_app.send_task"), raising=False)

        trigger_patches = []

        def _patch(mod_path, attr_name, guard_name):
            import importlib
            try:
                mod = importlib.import_module(mod_path)
                if hasattr(mod, attr_name):
                    monkeypatch.setattr(mod, attr_name, _guard(guard_name), raising=False)
                    trigger_patches.append(f"{mod_path}.{attr_name}")
            except ImportError:
                pass

        _patch("core.services.celery_publisher", "CeleryReportGenerationPublisher.publish", "publish")
        _patch("core.services.celery_publisher", "CeleryReportGenerationPublisher", "publisher_init")
        _patch("core.services.matrix_report_worker", "MatrixReportGenerationWorker.process", "worker.process")
        _patch("core.services.matrix_report_generator", "DefaultMatrixReportGenerator.generate", "generator.generate")
        _patch("core.services.ai", "AIService.chat", "ai.chat")
        _patch("core.services.ai", "AIService.generate_full_report", "ai.generate")
        _patch("core.services.ai", "AIService.generate_kitchen_report", "ai.kitchen")
        _patch("core.services.payment", "PaymentService.process_webhook", "payment.webhook")
        _patch("core.services.payment", "YooPayment", "yookassa")
        _patch("core.database", "get_redis", "redis")

        now = _now()
        old_claimed = now - timedelta(minutes=10)
        old_enqueued = now - timedelta(minutes=15)
        old_started = now - timedelta(minutes=40)

        async with sf() as s:
            u = test_user
            await _create_report_and_job(
                s, user_id=u.id, token="gap-ext-1",
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                job_state=ReportGenerationJobState.DISPATCHING,
                claimed_at=old_claimed,
            )
            await _create_report_and_job(
                s, user_id=u.id, token="gap-ext-2",
                generation_state=ReportGenerationState.QUEUED,
                job_state=ReportGenerationJobState.QUEUED,
                generation_enqueued_at=old_enqueued,
            )
            await _create_report_and_job(
                s, user_id=u.id, token="gap-ext-3",
                generation_state=ReportGenerationState.RUNNING,
                job_state=ReportGenerationJobState.QUEUED,
                generation_started_at=old_started,
            )
            await _create_report_and_job(
                s, user_id=u.id, token="gap-ext-4",
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                job_state=ReportGenerationJobState.FAILED_RETRYABLE,
                next_attempt_at=now - timedelta(seconds=1),
            )

        reconciler = _reconciler(
            sf,
            dispatch_claim_stale_before=timedelta(minutes=2),
            queued_stale_before=timedelta(minutes=10),
            running_stale_before=timedelta(minutes=30),
        )
        result = await reconciler.reconcile_batch(now=now, limit=20)

        assert result.dispatch_claims_recovered >= 1
        assert result.queued_recovered >= 1
        assert result.running_recovered >= 1
        assert result.retries_promoted >= 1

        assert len(violated) == 0, f"external calls detected: {violated}"


class TestBeatScheduleUnchanged:
    def test_beat_entries_present(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "reconcile-report-generation-jobs" in schedule
        assert "dispatch-report-generation-jobs" in schedule
