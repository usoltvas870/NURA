import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Order,
    OrderStatus,
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
)


class ReportGenerationErrorCategory:
    AI_TIMEOUT = "ai_timeout"
    AI_PROVIDER_UNAVAILABLE = "ai_provider_unavailable"
    PDF_GENERATION_FAILED = "pdf_generation_failed"
    STORAGE_FAILED = "storage_failed"
    DISPATCH_FAILED = "dispatch_failed"
    DISPATCH_CLAIM_EXPIRED = "dispatch_claim_expired"
    WORKER_DELIVERY_EXPIRED = "worker_delivery_expired"
    WORKER_LEASE_EXPIRED = "worker_lease_expired"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    ENTITLEMENT_REVOKED = "entitlement_revoked"
    UNKNOWN_INTERNAL = "unknown_internal"


REPORT_GENERATION_ERROR_CATEGORIES = frozenset(
    {
        ReportGenerationErrorCategory.AI_TIMEOUT,
        ReportGenerationErrorCategory.AI_PROVIDER_UNAVAILABLE,
        ReportGenerationErrorCategory.PDF_GENERATION_FAILED,
        ReportGenerationErrorCategory.STORAGE_FAILED,
        ReportGenerationErrorCategory.DISPATCH_FAILED,
        ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED,
        ReportGenerationErrorCategory.WORKER_DELIVERY_EXPIRED,
        ReportGenerationErrorCategory.WORKER_LEASE_EXPIRED,
        ReportGenerationErrorCategory.RETRY_BUDGET_EXHAUSTED,
        ReportGenerationErrorCategory.ENTITLEMENT_REVOKED,
        ReportGenerationErrorCategory.UNKNOWN_INTERNAL,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_category(category: str) -> str:
    if category not in REPORT_GENERATION_ERROR_CATEGORIES:
        raise ValueError("invalid_generation_error_category")
    return category


def _report_has_active_paid_entitlement() -> object:
    paid_order = (
        select(Order.id)
        .where(
            Order.id == Report.order_id,
            Order.report_id == Report.id,
            Order.status == OrderStatus.PAID,
        )
        .exists()
    )
    return or_(
        and_(Report.order_id.is_(None), Report.payment_id.is_not(None)),
        paid_order,
    )


def _report_is_dispatchable() -> object:
    return (
        select(Report.id)
        .where(
            Report.id == ReportGenerationJob.report_id,
            Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
            Report.generation_state == ReportGenerationState.PENDING_DISPATCH,
            _report_has_active_paid_entitlement(),
        )
        .exists()
    )


class ReportLifecycleRepository:
    """Caller-owned-session lifecycle operations for Report rows."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, report_id: uuid.UUID) -> Report | None:
        return await self._session.get(Report, report_id)

    async def get_by_token_and_user_id(
        self, token: str, user_id: uuid.UUID
    ) -> Report | None:
        result = await self._session.execute(
            select(Report).where(Report.token == token, Report.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_lifecycle_snapshot(self, report_id: uuid.UUID) -> Report | None:
        return await self.get_by_id(report_id)

    async def revoke_unfinished_order_report(
        self, report_id: uuid.UUID, revoked_at: datetime
    ) -> bool:
        """Terminalize unfinished generation while preserving completed artifacts."""
        report = await self._session.get(Report, report_id, with_for_update=True)
        if (
            report is None
            or report.order_id is None
            or report.generation_state == ReportGenerationState.COMPLETED
        ):
            return False

        changed = (
            report.generation_state != ReportGenerationState.FAILED_TERMINAL
            or report.generation_error_category
            != ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
        )
        report.generation_state = ReportGenerationState.FAILED_TERMINAL
        report.generation_failed_at = revoked_at
        report.generation_error_category = (
            ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
        )
        report.matrix_data = None
        report.ai_analysis = None
        report.kitchen_analysis = None
        report.artifact_bytes = None
        report.artifact_sha256 = None
        report.artifact_size_bytes = None
        report.artifact_mime_type = None
        report.artifact_completed_at = None

        job = (
            await self._session.execute(
                select(ReportGenerationJob)
                .where(
                    ReportGenerationJob.report_id == report_id,
                    ReportGenerationJob.job_type == "full_report",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is not None and job.state != ReportGenerationJobState.COMPLETED:
            changed = changed or (
                job.state != ReportGenerationJobState.FAILED_TERMINAL
                or job.last_error_category
                != ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
            )
            job.state = ReportGenerationJobState.FAILED_TERMINAL
            job.failed_at = revoked_at
            job.next_attempt_at = None
            job.claimed_at = None
            job.last_error_category = (
                ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
            )
        return changed

    async def confirm_report_payment(
        self,
        report_id: uuid.UUID,
        payment_id: uuid.UUID,
        confirmed_at: datetime | None = None,
    ) -> Report:
        report = await self._session.get(Report, report_id, with_for_update=True)
        if report is None:
            raise ValueError("report_not_found")
        if report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED:
            if report.payment_id == payment_id:
                return report
            raise ValueError("report_payment_conflict")
        if (
            report.payment_state != ReportPaymentState.AWAITING_PAYMENT
            or report.payment_id is not None
        ):
            raise ValueError("invalid_report_payment_transition")

        payment = await self._session.get(Payment, payment_id)
        if payment is None or payment.user_id != report.user_id:
            raise ValueError("invalid_report_payment")
        linked_report = (
            await self._session.execute(
                select(Report.id).where(Report.payment_id == payment_id)
            )
        ).scalar_one_or_none()
        if linked_report is not None and linked_report != report.id:
            raise ValueError("report_payment_conflict")

        report.payment_id = payment_id
        report.payment_state = ReportPaymentState.PAYMENT_CONFIRMED
        report.payment_confirmed_at = confirmed_at or _now()
        return report

    async def confirm_report_order(
        self, report_id: uuid.UUID, order_id: uuid.UUID, confirmed_at: datetime | None = None
    ) -> Report:
        report = await self._session.get(Report, report_id, with_for_update=True)
        if report is None:
            raise ValueError("report_not_found")
        if report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED:
            if report.order_id == order_id:
                return report
            raise ValueError("report_payment_conflict")
        if report.payment_state != ReportPaymentState.AWAITING_PAYMENT or report.order_id != order_id:
            raise ValueError("invalid_report_payment_transition")
        report.payment_state = ReportPaymentState.PAYMENT_CONFIRMED
        report.payment_confirmed_at = confirmed_at or _now()
        return report

    @staticmethod
    def mark_report_pending_dispatch(report: Report) -> Report:
        if report.generation_state == ReportGenerationState.PENDING_DISPATCH:
            return report
        if (
            report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
            or (report.payment_id is None and report.order_id is None)
            or report.generation_state != ReportGenerationState.NOT_REQUESTED
        ):
            raise ValueError("invalid_report_generation_transition")
        report.generation_state = ReportGenerationState.PENDING_DISPATCH
        return report

    @staticmethod
    def mark_report_queued(report: Report, enqueued_at: datetime | None = None) -> Report:
        if report.generation_state == ReportGenerationState.QUEUED:
            return report
        if (
            report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
            or (report.payment_id is None and report.order_id is None)
            or report.generation_state != ReportGenerationState.PENDING_DISPATCH
        ):
            raise ValueError("invalid_report_generation_transition")
        report.generation_state = ReportGenerationState.QUEUED
        if report.generation_enqueued_at is None:
            report.generation_enqueued_at = enqueued_at or _now()
        return report

    @staticmethod
    def mark_report_running(report: Report, started_at: datetime | None = None) -> Report:
        if report.generation_state == ReportGenerationState.RUNNING:
            return report
        if (
            report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
            or (report.payment_id is None and report.order_id is None)
            or report.generation_state != ReportGenerationState.QUEUED
        ):
            raise ValueError("invalid_report_generation_transition")
        report.generation_state = ReportGenerationState.RUNNING
        if report.generation_started_at is None:
            report.generation_started_at = started_at or _now()
        report.generation_attempts += 1
        return report

    @staticmethod
    def mark_report_completed(report: Report, generated_at: datetime | None = None) -> Report:
        if report.generation_state == ReportGenerationState.COMPLETED:
            return report
        if report.generation_state != ReportGenerationState.RUNNING:
            raise ValueError("invalid_report_generation_transition")
        report.generation_state = ReportGenerationState.COMPLETED
        if report.generated_at is None:
            report.generated_at = generated_at or _now()
        report.generation_error_category = None
        return report

    @staticmethod
    def mark_report_failed_retryable(
        report: Report,
        error_category: str,
        failed_at: datetime | None = None,
    ) -> Report:
        if report.generation_state not in {
            ReportGenerationState.QUEUED,
            ReportGenerationState.RUNNING,
        }:
            raise ValueError("invalid_report_generation_transition")
        safe_category = _safe_error_category(error_category)
        report.generation_state = ReportGenerationState.FAILED_RETRYABLE
        report.generation_failed_at = failed_at or _now()
        report.generation_error_category = safe_category
        return report

    @staticmethod
    def retry_report_generation(report: Report) -> Report:
        if report.generation_state != ReportGenerationState.FAILED_RETRYABLE:
            raise ValueError("invalid_report_generation_transition")
        report.generation_state = ReportGenerationState.PENDING_DISPATCH
        return report

    @staticmethod
    def mark_report_failed_terminal(
        report: Report,
        error_category: str,
        failed_at: datetime | None = None,
    ) -> Report:
        if report.generation_state == ReportGenerationState.FAILED_TERMINAL:
            return report
        if report.generation_state not in {
            ReportGenerationState.QUEUED,
            ReportGenerationState.RUNNING,
            ReportGenerationState.FAILED_RETRYABLE,
        }:
            raise ValueError("invalid_report_generation_transition")
        safe_category = _safe_error_category(error_category)
        report.generation_state = ReportGenerationState.FAILED_TERMINAL
        report.generation_failed_at = failed_at or _now()
        report.generation_error_category = safe_category
        return report

    @staticmethod
    def mark_report_dispatch_failed_terminal(
        report: Report,
        error_category: str,
        failed_at: datetime | None = None,
    ) -> Report:
        if report.generation_state == ReportGenerationState.FAILED_TERMINAL:
            return report
        if report.generation_state != ReportGenerationState.PENDING_DISPATCH:
            raise ValueError("invalid_report_generation_transition")
        safe_category = _safe_error_category(error_category)
        report.generation_state = ReportGenerationState.FAILED_TERMINAL
        report.generation_failed_at = failed_at or _now()
        report.generation_error_category = safe_category
        return report


class ReportGenerationJobRepository:
    """Caller-owned-session lifecycle operations for ReportGenerationJob rows."""

    def __init__(
        self,
        session: AsyncSession,
        before_atomic_claim: Callable[[], Awaitable[None]] | None = None,
    ):
        self._session = session
        self._before_atomic_claim = before_atomic_claim

    async def get_by_id(self, job_id: uuid.UUID) -> ReportGenerationJob | None:
        return await self._session.get(ReportGenerationJob, job_id)

    async def get_by_report_and_type(
        self, report_id: uuid.UUID, job_type: str = "full_report"
    ) -> ReportGenerationJob | None:
        result = await self._session.execute(
            select(ReportGenerationJob).where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == job_type,
            )
        )
        return result.scalar_one_or_none()

    async def get_lifecycle_snapshot(
        self, job_id: uuid.UUID
    ) -> ReportGenerationJob | None:
        return await self.get_by_id(job_id)

    async def list_dispatchable_jobs(
        self,
        now: datetime,
        limit: int,
        job_type: str = "full_report",
    ) -> list[ReportGenerationJob]:
        if limit <= 0:
            return []
        result = await self._session.execute(
            select(ReportGenerationJob)
            .join(Report, Report.id == ReportGenerationJob.report_id)
            .where(
                ReportGenerationJob.job_type == job_type,
                or_(
                    ReportGenerationJob.state
                    == ReportGenerationJobState.PENDING_DISPATCH,
                    and_(
                        ReportGenerationJob.state
                        == ReportGenerationJobState.FAILED_RETRYABLE,
                        ReportGenerationJob.next_attempt_at <= now,
                    ),
                ),
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                Report.generation_state == ReportGenerationState.PENDING_DISPATCH,
                _report_has_active_paid_entitlement(),
            )
            .order_by(
                ReportGenerationJob.next_attempt_at.asc().nullsfirst(),
                ReportGenerationJob.created_at.asc(),
                ReportGenerationJob.id.asc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def claim_job_for_dispatch(
        self, job_id: uuid.UUID, now: datetime
    ) -> str:
        """Atomically claim one dispatchable job without publishing it."""
        if self._before_atomic_claim is not None:
            await self._before_atomic_claim()

        claim_statement = (
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.id == job_id,
                ReportGenerationJob.job_type == "full_report",
                _report_is_dispatchable(),
                or_(
                    ReportGenerationJob.state
                    == ReportGenerationJobState.PENDING_DISPATCH,
                    and_(
                        ReportGenerationJob.state
                        == ReportGenerationJobState.FAILED_RETRYABLE,
                        ReportGenerationJob.next_attempt_at <= now,
                    ),
                ),
            )
            .values(
                state=ReportGenerationJobState.DISPATCHING,
                claimed_at=now,
                next_attempt_at=None,
            )
        )
        for attempt in range(5):
            try:
                async with self._session.begin_nested():
                    result = await self._session.execute(claim_statement)
                if result.rowcount == 1:
                    return "claimed"
                return "generation_job_claim_conflict"
            except OperationalError as error:
                if "database is locked" not in str(error).lower() or attempt == 4:
                    raise
                await asyncio.sleep(0)
        raise RuntimeError("generation_job_claim_retry_exhausted")

    async def mark_stale_dispatch_claim_retryable(
        self,
        job_id: uuid.UUID,
        stale_before: datetime,
        now: datetime,
        next_attempt_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.id == job_id,
                ReportGenerationJob.state == ReportGenerationJobState.DISPATCHING,
                ReportGenerationJob.claimed_at <= stale_before,
                ReportGenerationJob.published_at.is_(None),
                ReportGenerationJob.celery_task_id.is_(None),
                _report_is_dispatchable(),
            )
            .values(
                state=ReportGenerationJobState.FAILED_RETRYABLE,
                failed_at=now,
                next_attempt_at=next_attempt_at,
                last_error_category=ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED,
            )
        )
        return result.rowcount == 1

    def create_pending_dispatch_job(self, report_id: uuid.UUID) -> ReportGenerationJob:
        job = ReportGenerationJob(
            id=uuid.uuid4(),
            report_id=report_id,
            job_type="full_report",
            state=ReportGenerationJobState.PENDING_DISPATCH,
        )
        self._session.add(job)
        return job

    @staticmethod
    def claim_dispatch(
        job: ReportGenerationJob, claimed_at: datetime | None = None
    ) -> ReportGenerationJob:
        if job.state == ReportGenerationJobState.DISPATCHING:
            return job
        if job.state != ReportGenerationJobState.PENDING_DISPATCH:
            raise ValueError("invalid_generation_job_transition")
        job.state = ReportGenerationJobState.DISPATCHING
        if job.claimed_at is None:
            job.claimed_at = claimed_at or _now()
        return job

    @staticmethod
    def mark_job_queued(
        job: ReportGenerationJob,
        celery_task_id: str,
        published_at: datetime | None = None,
    ) -> ReportGenerationJob:
        if not celery_task_id or len(celery_task_id) > 128:
            raise ValueError("invalid_generation_job_transition")
        if job.state == ReportGenerationJobState.QUEUED:
            if job.celery_task_id == celery_task_id:
                return job
            raise ValueError("generation_job_task_conflict")
        if job.state != ReportGenerationJobState.DISPATCHING:
            raise ValueError("invalid_generation_job_transition")
        job.state = ReportGenerationJobState.QUEUED
        job.celery_task_id = celery_task_id
        if job.published_at is None:
            job.published_at = published_at or _now()
        job.attempts += 1
        return job

    @staticmethod
    def mark_job_failed_retryable(
        job: ReportGenerationJob,
        error_category: str,
        next_attempt_at: datetime,
        failed_at: datetime | None = None,
    ) -> ReportGenerationJob:
        allowed = {ReportGenerationJobState.DISPATCHING, ReportGenerationJobState.QUEUED}
        if job.state not in allowed:
            raise ValueError("invalid_generation_job_transition")
        safe_category = _safe_error_category(error_category)
        job.state = ReportGenerationJobState.FAILED_RETRYABLE
        job.failed_at = failed_at or _now()
        job.next_attempt_at = next_attempt_at
        job.last_error_category = safe_category
        job.attempts += 1
        return job

    @staticmethod
    def retry_dispatch(job: ReportGenerationJob) -> ReportGenerationJob:
        if job.state != ReportGenerationJobState.FAILED_RETRYABLE:
            raise ValueError("invalid_generation_job_transition")
        job.state = ReportGenerationJobState.PENDING_DISPATCH
        return job

    @staticmethod
    def mark_job_completed(
        job: ReportGenerationJob, completed_at: datetime | None = None
    ) -> ReportGenerationJob:
        if job.state == ReportGenerationJobState.COMPLETED:
            return job
        if job.state != ReportGenerationJobState.QUEUED:
            raise ValueError("invalid_generation_job_transition")
        job.state = ReportGenerationJobState.COMPLETED
        if job.completed_at is None:
            job.completed_at = completed_at or _now()
        return job

    @staticmethod
    def mark_job_failed_terminal(
        job: ReportGenerationJob,
        error_category: str,
        failed_at: datetime | None = None,
    ) -> ReportGenerationJob:
        if job.state == ReportGenerationJobState.FAILED_TERMINAL:
            return job
        if job.state not in {
            ReportGenerationJobState.DISPATCHING,
            ReportGenerationJobState.QUEUED,
            ReportGenerationJobState.FAILED_RETRYABLE,
        }:
            raise ValueError("invalid_generation_job_transition")
        safe_category = _safe_error_category(error_category)
        job.state = ReportGenerationJobState.FAILED_TERMINAL
        job.failed_at = failed_at or _now()
        job.last_error_category = safe_category
        job.attempts += 1
        return job

    async def claim_generation_run(
        self, report_id: uuid.UUID, now: datetime
    ) -> tuple[str, Report | None, ReportGenerationJob | None]:
        from sqlalchemy import select as sa_select

        for attempt in range(5):
            try:
                async with self._session.begin_nested():
                    claim_result = await self._session.execute(
                        update(Report)
                        .where(
                            Report.id == report_id,
                            Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                            _report_has_active_paid_entitlement(),
                            Report.generation_state == ReportGenerationState.QUEUED,
                        )
                        .values(
                            generation_state=ReportGenerationState.RUNNING,
                            generation_started_at=now,
                            generation_attempts=Report.generation_attempts + 1,
                        )
                    )
                if claim_result.rowcount == 1:
                    break
                report = await self._session.get(Report, report_id)
                if report is None:
                    return "report_not_found", None, None
                if report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED:
                    return "report_not_paid", report, None
                if report.order_id is not None:
                    order = await self._session.get(Order, report.order_id)
                    if order is None or order.status != OrderStatus.PAID:
                        return "entitlement_revoked", report, None
                if report.generation_state == ReportGenerationState.RUNNING:
                    return "generation_already_running", report, None
                if report.generation_state == ReportGenerationState.COMPLETED:
                    return "generation_already_completed", report, None
                if report.generation_state == ReportGenerationState.FAILED_TERMINAL:
                    return "generation_already_terminal", report, None
                return "generation_claim_conflict", report, None
            except OperationalError as error:
                if "database is locked" not in str(error).lower() or attempt == 4:
                    raise
                await asyncio.sleep(0)

        report = await self._session.get(Report, report_id)
        if report is None:
            raise RuntimeError("generation_claim_lost_report")
        job = (
            await self._session.execute(
                sa_select(ReportGenerationJob).where(
                    ReportGenerationJob.report_id == report_id,
                    ReportGenerationJob.job_type == "full_report",
                    ReportGenerationJob.state == ReportGenerationJobState.QUEUED,
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise ValueError("report_generation_job_missing")
        return "claimed", report, job

    async def mark_stale_running_generation_retryable(
        self,
        report_id: uuid.UUID,
        stale_before: datetime,
        now: datetime,
        next_attempt_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(Report)
            .where(
                Report.id == report_id,
                Report.generation_state == ReportGenerationState.RUNNING,
                Report.generation_started_at <= stale_before,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                _report_has_active_paid_entitlement(),
            )
            .values(
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                generation_failed_at=now,
                generation_error_category=ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED,
            )
        )
        if result.rowcount != 1:
            return False
        job_result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state == ReportGenerationJobState.QUEUED,
            )
            .values(
                state=ReportGenerationJobState.FAILED_RETRYABLE,
                failed_at=now,
                next_attempt_at=next_attempt_at,
                last_error_category=ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED,
            )
        )
        return job_result.rowcount == 1

    async def mark_stale_queued_generation_retryable(
        self,
        report_id: uuid.UUID,
        stale_before: datetime,
        now: datetime,
        next_attempt_at: datetime,
    ) -> bool:
        result = await self._session.execute(
            update(Report)
            .where(
                Report.id == report_id,
                Report.generation_state == ReportGenerationState.QUEUED,
                Report.generation_enqueued_at <= stale_before,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                Report.generated_at.is_(None),
                _report_has_active_paid_entitlement(),
            )
            .values(
                generation_state=ReportGenerationState.FAILED_RETRYABLE,
                generation_failed_at=now,
                generation_error_category=ReportGenerationErrorCategory.WORKER_DELIVERY_EXPIRED,
            )
        )
        if result.rowcount != 1:
            return False
        job_result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state == ReportGenerationJobState.QUEUED,
                ReportGenerationJob.completed_at.is_(None),
            )
            .values(
                state=ReportGenerationJobState.FAILED_RETRYABLE,
                failed_at=now,
                next_attempt_at=next_attempt_at,
                last_error_category=ReportGenerationErrorCategory.WORKER_DELIVERY_EXPIRED,
            )
        )
        return job_result.rowcount == 1

    async def promote_failed_retryable_to_pending(
        self,
        report_id: uuid.UUID,
        now: datetime,
    ) -> bool:
        report_result = await self._session.execute(
            update(Report)
            .where(
                Report.id == report_id,
                Report.generation_state == ReportGenerationState.FAILED_RETRYABLE,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                _report_has_active_paid_entitlement(),
            )
            .values(generation_state=ReportGenerationState.PENDING_DISPATCH)
        )
        if report_result.rowcount != 1:
            return False
        job_result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state == ReportGenerationJobState.FAILED_RETRYABLE,
            )
            .values(state=ReportGenerationJobState.PENDING_DISPATCH)
        )
        return job_result.rowcount == 1

    async def terminalize_exhausted_pair(
        self,
        report_id: uuid.UUID,
        now: datetime,
    ) -> bool:
        report_result = await self._session.execute(
            update(Report)
            .where(
                Report.id == report_id,
                Report.generation_state == ReportGenerationState.FAILED_RETRYABLE,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                _report_has_active_paid_entitlement(),
            )
            .values(
                generation_state=ReportGenerationState.FAILED_TERMINAL,
                generation_failed_at=now,
                generation_error_category=ReportGenerationErrorCategory.RETRY_BUDGET_EXHAUSTED,
            )
        )
        if report_result.rowcount != 1:
            return False
        job_result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state == ReportGenerationJobState.FAILED_RETRYABLE,
            )
            .values(
                state=ReportGenerationJobState.FAILED_TERMINAL,
                failed_at=now,
                last_error_category=ReportGenerationErrorCategory.RETRY_BUDGET_EXHAUSTED,
            )
        )
        return job_result.rowcount == 1

    async def repair_missing_full_report_job(
        self,
        report_id: uuid.UUID,
    ) -> bool:
        existing = (
            await self._session.execute(
                select(ReportGenerationJob).where(
                    ReportGenerationJob.report_id == report_id,
                    ReportGenerationJob.job_type == "full_report",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        report = await self._session.get(Report, report_id)
        if report is None:
            return False
        if (
            report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
            or (report.payment_id is None and report.order_id is None)
            or report.generation_state != ReportGenerationState.PENDING_DISPATCH
            or report.report_type != "full"
            or report.generated_at is not None
        ):
            return False
        if report.order_id is not None:
            order = await self._session.get(Order, report.order_id)
            if order is None or order.status != OrderStatus.PAID:
                return False
        job = ReportGenerationJob(
            id=uuid.uuid4(),
            report_id=report_id,
            job_type="full_report",
            state=ReportGenerationJobState.PENDING_DISPATCH,
        )
        self._session.add(job)
        await self._session.flush()
        return True

    async def repair_completed_pair(
        self,
        report_id: uuid.UUID,
        now: datetime,
    ) -> bool:
        report = await self._session.get(Report, report_id)
        if report is None:
            return False
        if (
            report.generation_state != ReportGenerationState.COMPLETED
            or report.generated_at is None
            or report.matrix_data is None
        ):
            return False
        job_result = await self._session.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.report_id == report_id,
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state != ReportGenerationJobState.COMPLETED,
            )
            .values(
                state=ReportGenerationJobState.COMPLETED,
                completed_at=now,
            )
        )
        return job_result.rowcount == 1

    async def list_stale_dispatching_jobs(
        self,
        stale_before: datetime,
        limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        result = await self._session.execute(
            select(ReportGenerationJob.id, ReportGenerationJob.report_id)
            .select_from(ReportGenerationJob)
            .join(Report, Report.id == ReportGenerationJob.report_id)
            .where(
                ReportGenerationJob.state == ReportGenerationJobState.DISPATCHING,
                ReportGenerationJob.claimed_at <= stale_before,
                ReportGenerationJob.published_at.is_(None),
                ReportGenerationJob.celery_task_id.is_(None),
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                Report.generation_state == ReportGenerationState.PENDING_DISPATCH,
                _report_has_active_paid_entitlement(),
                ReportGenerationJob.job_type == "full_report",
            )
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_stale_queued_pairs(
        self,
        stale_before: datetime,
        limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        result = await self._session.execute(
            select(ReportGenerationJob.id, ReportGenerationJob.report_id)
            .select_from(ReportGenerationJob)
            .join(Report, Report.id == ReportGenerationJob.report_id)
            .where(
                ReportGenerationJob.state == ReportGenerationJobState.QUEUED,
                Report.generation_state == ReportGenerationState.QUEUED,
                Report.generation_enqueued_at <= stale_before,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                Report.generated_at.is_(None),
                _report_has_active_paid_entitlement(),
                ReportGenerationJob.completed_at.is_(None),
                ReportGenerationJob.job_type == "full_report",
            )
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_stale_running_pairs(
        self,
        stale_before: datetime,
        limit: int,
    ) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Report.id)
            .select_from(Report)
            .join(ReportGenerationJob, ReportGenerationJob.report_id == Report.id)
            .where(
                Report.generation_state == ReportGenerationState.RUNNING,
                Report.generation_started_at <= stale_before,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                ReportGenerationJob.state == ReportGenerationJobState.QUEUED,
                _report_has_active_paid_entitlement(),
                ReportGenerationJob.job_type == "full_report",
            )
            .limit(limit)
        )
        return [row[0] for row in result.all()]

    async def list_due_failed_retryable_pairs(
        self,
        now: datetime,
        max_dispatch_attempts: int,
        max_generation_attempts: int,
        limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID, int, int]]:
        result = await self._session.execute(
            select(
                ReportGenerationJob.id,
                ReportGenerationJob.report_id,
                ReportGenerationJob.attempts,
                Report.generation_attempts,
            )
            .select_from(ReportGenerationJob)
            .join(Report, Report.id == ReportGenerationJob.report_id)
            .where(
                ReportGenerationJob.state == ReportGenerationJobState.FAILED_RETRYABLE,
                ReportGenerationJob.next_attempt_at <= now,
                Report.generation_state == ReportGenerationState.FAILED_RETRYABLE,
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                ReportGenerationJob.job_type == "full_report",
                _report_has_active_paid_entitlement(),
            )
            .limit(limit)
        )
        return [
            (row[0], row[1], row[2], row[3]) for row in result.all()
        ]

    async def list_missing_job_paid_reports(
        self,
        limit: int,
    ) -> list[uuid.UUID]:
        from sqlalchemy import exists

        has_job = (
            exists()
            .where(
                ReportGenerationJob.report_id == Report.id,
                ReportGenerationJob.job_type == "full_report",
            )
        )
        result = await self._session.execute(
            select(Report.id)
            .where(
                Report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED,
                _report_has_active_paid_entitlement(),
                Report.generation_state == ReportGenerationState.PENDING_DISPATCH,
                Report.report_type == "full",
                Report.generated_at.is_(None),
                ~has_job,
            )
            .limit(limit)
        )
        return [row[0] for row in result.all()]

    async def list_completed_report_active_job_pairs(
        self,
        limit: int,
    ) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Report.id)
            .select_from(Report)
            .join(ReportGenerationJob, ReportGenerationJob.report_id == Report.id)
            .where(
                Report.generation_state == ReportGenerationState.COMPLETED,
                Report.generated_at.isnot(None),
                Report.matrix_data.isnot(None),
                ReportGenerationJob.job_type == "full_report",
                ReportGenerationJob.state != ReportGenerationJobState.COMPLETED,
            )
            .limit(limit)
        )
        return [row[0] for row in result.all()]
