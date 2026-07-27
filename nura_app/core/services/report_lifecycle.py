import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Payment,
    PromoCode,
    PromoReservation,
    Report,
    ReportGenerationJob,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.report_lifecycle import (
    ReportGenerationJobRepository,
    ReportLifecycleRepository,
)


class ReportLifecycleService:
    """Coordinates Report and job transitions in a caller-owned transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._reports = ReportLifecycleRepository(session)
        self._jobs = ReportGenerationJobRepository(session)

    async def confirm_payment_and_prepare_generation(
        self,
        report_id: uuid.UUID,
        payment_id: uuid.UUID,
        confirmed_at: datetime | None = None,
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._reports.confirm_report_payment(
            report_id, payment_id, confirmed_at
        )
        with self._session.no_autoflush:
            job = await self._jobs.get_by_report_and_type(report_id)
        if report.generation_state in {
            ReportGenerationState.COMPLETED,
            ReportGenerationState.FAILED_TERMINAL,
        }:
            raise ValueError("invalid_report_generation_transition")
        if report.generation_state == ReportGenerationState.NOT_REQUESTED:
            self._reports.mark_report_pending_dispatch(report)
            if job is None:
                job = self._jobs.create_pending_dispatch_job(report.id)
        elif job is None:
            raise ValueError("report_generation_job_missing")

        if job is None:
            raise ValueError("report_generation_job_missing")
        await self._session.flush()
        return report, job

    async def confirm_order_and_prepare_generation(
        self, report_id: uuid.UUID, order_id: uuid.UUID, confirmed_at: datetime | None = None
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._reports.confirm_report_order(report_id, order_id, confirmed_at)
        with self._session.no_autoflush:
            job = await self._jobs.get_by_report_and_type(report_id)
        if report.generation_state == ReportGenerationState.NOT_REQUESTED:
            self._reports.mark_report_pending_dispatch(report)
            if job is None:
                job = self._jobs.create_pending_dispatch_job(report.id)
        if job is None:
            raise ValueError("report_generation_job_missing")
        await self._session.flush()
        return report, job

    async def mark_generation_queued(
        self,
        report_id: uuid.UUID,
        celery_task_id: str,
        enqueued_at: datetime | None = None,
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._require_report(report_id)
        job = await self._require_full_report_job(report_id)
        self._reports.mark_report_queued(report, enqueued_at)
        self._jobs.mark_job_queued(job, celery_task_id, enqueued_at)
        await self._session.flush()
        return report, job

    async def mark_generation_completed(
        self,
        report_id: uuid.UUID,
        generated_at: datetime | None = None,
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._require_report(report_id)
        job = await self._require_full_report_job(report_id)
        self._reports.mark_report_completed(report, generated_at)
        self._jobs.mark_job_completed(job, generated_at)
        await self._session.flush()
        return report, job

    async def retry_generation(
        self, report_id: uuid.UUID
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._require_report(report_id)
        job = await self._require_full_report_job(report_id)
        self._reports.retry_report_generation(report)
        self._jobs.retry_dispatch(job)
        await self._session.flush()
        return report, job

    async def mark_dispatch_terminal(
        self,
        report_id: uuid.UUID,
        error_category: str,
        failed_at: datetime | None = None,
    ) -> tuple[Report, ReportGenerationJob]:
        report = await self._require_report(report_id)
        job = await self._require_full_report_job(report_id)
        self._reports.mark_report_dispatch_failed_terminal(
            report, error_category, failed_at
        )
        self._jobs.mark_job_failed_terminal(job, error_category, failed_at)
        await self._session.flush()
        return report, job

    async def _require_report(self, report_id: uuid.UUID) -> Report:
        report = await self._reports.get_by_id(report_id)
        if report is None:
            raise ValueError("report_not_found")
        return report

    async def _require_full_report_job(
        self, report_id: uuid.UUID
    ) -> ReportGenerationJob:
        job = await self._jobs.get_by_report_and_type(report_id)
        if job is None:
            raise ValueError("report_generation_job_missing")
        if job.report_id != report_id:
            raise ValueError("invalid_generation_job_transition")
        return job


class ReportLifecycleCoordinator:
    """Coordinates durable Matrix checkout and activation in one DB session."""

    def __init__(
        self,
        session: AsyncSession,
        activation_hook: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._session = session
        self._lifecycle = ReportLifecycleService(session)
        self._activation_hook = activation_hook

    async def create_or_get_matrix_placeholder(
        self,
        *,
        user_id: uuid.UUID,
        idempotency_key: str,
        report_token: str,
        promo_code_id: uuid.UUID | None,
        final_amount_kopecks: int,
        currency: str,
        expires_at: datetime,
    ) -> tuple[PromoReservation, Report]:
        reservation = (
            await self._session.execute(
                select(PromoReservation)
                .where(PromoReservation.idempotency_key == idempotency_key)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reservation is not None:
            if (
                reservation.user_id != user_id
                or reservation.payment_type != "web_matrix"
                or reservation.promo_code_id != promo_code_id
                or reservation.final_amount_kopecks != final_amount_kopecks
                or reservation.currency != currency
                or reservation.report_token != report_token
            ):
                raise ValueError("idempotency_key_conflict")
            report = await self._get_matrix_report(reservation.report_token, user_id)
            return reservation, report

        if promo_code_id is not None:
            claim = await self._session.execute(
                update(PromoCode)
                .where(
                    PromoCode.id == promo_code_id,
                    PromoCode.is_active.is_(True),
                    or_(
                        PromoCode.max_uses.is_(None),
                        PromoCode.used_count + PromoCode.reserved_count
                        < PromoCode.max_uses,
                    ),
                )
                .values(reserved_count=PromoCode.reserved_count + 1)
            )
            if claim.rowcount != 1:
                raise ValueError("promo_capacity_exhausted")

        reservation = PromoReservation(
            id=uuid.uuid4(),
            promo_code_id=promo_code_id,
            user_id=user_id,
            payment_type="web_matrix",
            final_amount_kopecks=final_amount_kopecks,
            currency=currency,
            idempotency_key=idempotency_key,
            report_token=report_token,
            state="reserved",
            expires_at=expires_at,
        )
        report = Report(
            id=uuid.uuid4(),
            user_id=user_id,
            report_type=ReportType.FULL.value,
            token=report_token,
            payment_state=ReportPaymentState.AWAITING_PAYMENT,
            generation_state=ReportGenerationState.NOT_REQUESTED,
        )
        self._session.add_all([reservation, report])
        await self._session.flush()
        return reservation, report

    async def attach_matrix_provider_intent(
        self,
        *,
        reservation_id: uuid.UUID,
        provider_payment_id: str,
        user_id: uuid.UUID,
        amount_kopecks: int,
        promo_code_id: uuid.UUID | None,
    ) -> Payment:
        reservation = await self._session.get(
            PromoReservation, reservation_id, with_for_update=True
        )
        if (
            reservation is None
            or reservation.user_id != user_id
            or reservation.payment_type != "web_matrix"
            or reservation.promo_code_id != promo_code_id
            or reservation.state != "reserved"
        ):
            raise ValueError("reservation_attachment_conflict")
        if (
            reservation.provider_payment_id is not None
            and reservation.provider_payment_id != provider_payment_id
        ):
            raise ValueError("reservation_attachment_conflict")
        payment = (
            await self._session.execute(
                select(Payment)
                .where(Payment.yookassa_id == provider_payment_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if payment is None:
            payment = Payment(
                id=uuid.uuid4(),
                user_id=user_id,
                amount=amount_kopecks // 100,
                amount_kopecks=amount_kopecks,
                yookassa_id=provider_payment_id,
                payment_type="web_matrix",
                promo_code_id=promo_code_id,
            )
            self._session.add(payment)
        elif (
            payment.user_id != user_id
            or payment.payment_type != "web_matrix"
            or payment.amount_kopecks != amount_kopecks
            or payment.promo_code_id != promo_code_id
        ):
            raise ValueError("payment_attachment_conflict")
        if reservation.payment_id not in {None, payment.id}:
            raise ValueError("reservation_attachment_conflict")
        reservation.provider_payment_id = provider_payment_id
        reservation.payment_id = payment.id
        await self._session.flush()
        return payment

    async def activate_verified_matrix_payment(
        self,
        *,
        provider_payment_id: str,
        verified_user_id: uuid.UUID,
        verified_report_token: str,
        confirmed_at: datetime,
    ) -> str:
        payment = (
            await self._session.execute(
                select(Payment)
                .where(Payment.yookassa_id == provider_payment_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if payment is None or payment.payment_type != "web_matrix":
            raise ValueError("matrix_payment_not_found")
        reservation = (
            await self._session.execute(
                select(PromoReservation)
                .where(PromoReservation.payment_id == payment.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            reservation is None
            or reservation.user_id != payment.user_id
            or reservation.user_id != verified_user_id
            or reservation.payment_type != "web_matrix"
            or reservation.report_token != verified_report_token
        ):
            raise ValueError("matrix_reservation_conflict")
        report = await self._get_matrix_report(reservation.report_token, payment.user_id)
        if report.payment_state == ReportPaymentState.LEGACY_UNLINKED:
            raise ValueError("matrix_report_conflict")
        user = await self._session.get(User, payment.user_id, with_for_update=True)
        if user is None:
            raise ValueError("matrix_user_not_found")
        if payment.status == "succeeded":
            if (
                report.payment_id != payment.id
                or report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
                or reservation.state != "consumed"
            ):
                raise ValueError("matrix_duplicate_conflict")
            return "idempotent"
        if payment.status != "pending" or reservation.state != "reserved":
            raise ValueError("matrix_payment_conflict")

        payment.status = "succeeded"
        await self._checkpoint("after_payment_claim")
        await self._lifecycle.confirm_payment_and_prepare_generation(
            report.id, payment.id, confirmed_at
        )
        await self._checkpoint("after_report_job")
        user.has_matrix = True
        await self._checkpoint("after_entitlement")
        if reservation.promo_code_id is not None:
            promo = await self._session.get(
                PromoCode, reservation.promo_code_id, with_for_update=True
            )
            if promo is None or promo.reserved_count <= 0:
                raise ValueError("matrix_promo_conflict")
            promo.reserved_count -= 1
            promo.used_count += 1
        reservation.state = "consumed"
        reservation.consumed_at = confirmed_at
        payment.promo_consumed_at = confirmed_at
        await self._checkpoint("after_promo_consume")
        await self._session.flush()
        return "activated"

    async def _get_matrix_report(self, token: str | None, user_id: uuid.UUID) -> Report:
        if not token:
            raise ValueError("matrix_report_missing")
        report = (
            await self._session.execute(
                select(Report)
                .where(Report.token == token)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            report is None
            or report.user_id != user_id
            or report.report_type != ReportType.FULL.value
        ):
            raise ValueError("matrix_report_conflict")
        return report

    async def _checkpoint(self, stage: str) -> None:
        if self._activation_hook is not None:
            await self._activation_hook(stage)
