"""Safe Telegram boundary for canonical, already completed full-report PDFs."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from core.config import settings
from core.models import Order, OrderStatus, Report, ReportGenerationState, ReportType, User
from core.repositories.full_report_telegram_delivery import FullReportTelegramDeliveryRepository
from core.services.telegram_report_delivery import TelegramDeliveryError, TelegramDocumentAdapter


class FullReportTelegramDeliveryService:
    def __init__(self, session_factory, adapter: TelegramDocumentAdapter | None = None) -> None:
        self._session_factory = session_factory
        self._deliveries = FullReportTelegramDeliveryRepository(session_factory)
        self._adapter = adapter or TelegramDocumentAdapter()

    async def enqueue_automatic(self, report_id: uuid.UUID) -> uuid.UUID | None:
        subject = await self._subject(report_id)
        if subject is None:
            return None
        report, user, order = subject
        if not self._valid_artifact(report, report.artifact_bytes):
            return None
        row = await self._deliveries.get_or_create(
            report_id=report.id, order_id=order.id if order else None, user_id=user.id,
            reason="automatic", request_key="automatic", artifact_sha256=report.artifact_sha256,
            artifact_size_bytes=report.artifact_size_bytes, chat_id=user.telegram_id,
        )
        return row.id

    async def enqueue_manual(self, user_id: uuid.UUID, report_id: uuid.UUID, request_key: str) -> uuid.UUID | None:
        if not request_key:
            return None
        subject = await self._subject(report_id, user_id)
        if subject is None:
            return None
        report, user, order = subject
        if not self._valid_artifact(report, report.artifact_bytes):
            return None
        row = await self._deliveries.get_or_create(
            report_id=report.id, order_id=order.id if order else None, user_id=user.id,
            reason="manual", request_key=hashlib.sha256(request_key.encode()).hexdigest(),
            artifact_sha256=report.artifact_sha256, artifact_size_bytes=report.artifact_size_bytes,
            chat_id=user.telegram_id,
        )
        return row.id

    async def deliver(
        self, delivery_id: uuid.UUID, claimed_attempt: int | None = None
    ) -> None:
        attempt = claimed_attempt
        if attempt is None:
            attempt = await self._deliveries.claim(
                delivery_id, datetime.now(timezone.utc)
            )
        elif not await self._deliveries.owns_attempt(delivery_id, attempt):
            return
        if attempt is None:
            return
        delivery = await self._deliveries.get(delivery_id)
        if delivery is None:
            return
        caption = (
            "<b>Твоя полная Матрица готова.</b>\n"
            "Я собрала разбор в PDF, чтобы к нему можно было спокойно возвращаться."
        )
        try:
            async with self._locked_subject(
                delivery.report_id, delivery.user_id
            ) as subject:
                if subject is None:
                    await self._deliveries.cancel(delivery_id, attempt)
                    return
                report, user, _order = subject
                if not user.telegram_id:
                    await self._deliveries.cancel(delivery_id, attempt)
                    return
                canonical_file_id = await self._deliveries.get_canonical_file_id(
                    report.id
                )
                if canonical_file_id:
                    try:
                        document = await self._adapter.send_document_by_file_id(
                            user.telegram_id, canonical_file_id, caption
                        )
                    except TelegramDeliveryError as error:
                        if error.code != "invalid_file_id":
                            raise
                        document = await self._upload_artifact(
                            report, report.artifact_bytes, user.telegram_id, caption
                        )
                else:
                    document = await self._upload_artifact(
                        report, report.artifact_bytes, user.telegram_id, caption
                    )
                # Keep the paid-order lock until both the external send and durable
                # completion are done. Refunds therefore linearize strictly before
                # or after the delivery, never between entitlement check and send.
                await self._deliveries.complete(
                    delivery_id,
                    attempt,
                    message_id=document.message_id,
                    file_id=document.file_id,
                )
        except TelegramDeliveryError as error:
            await self._deliveries.fail(delivery_id, attempt, error.code, retryable=error.retryable)
            raise

    async def _upload_artifact(
        self,
        report: Report,
        artifact: bytes | None,
        chat_id: int,
        caption: str,
    ):
        if not self._valid_artifact(report, artifact):
            raise TelegramDeliveryError(
                "invalid_full_report_artifact", retryable=False
            )
        return await self._adapter.send_document_from_artifact(
            chat_id, artifact, "NURA-full-matrix.pdf", caption
        )

    async def _subject(self, report_id: uuid.UUID, user_id: uuid.UUID | None = None):
        async with self._session_factory() as session:
            report = await session.get(Report, report_id)
            if report is None or report.report_type != ReportType.FULL.value or report.generation_state != ReportGenerationState.COMPLETED:
                return None
            if user_id is not None and report.user_id != user_id:
                return None
            user = await session.get(User, report.user_id)
            if (
                user is None
                or user.account_status != "active"
                or not user.has_matrix
            ):
                return None
            order = await session.get(Order, report.order_id) if report.order_id else None
            if order is None or order.status != OrderStatus.PAID:
                return None
            return report, user, order

    @asynccontextmanager
    async def _locked_subject(
        self, report_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> AsyncIterator[tuple[Report, User, Order] | None]:
        """Hold the paid order lock across the Telegram send linearization point."""
        async with self._session_factory() as session:
            order_id = await session.scalar(
                select(Report.order_id).where(Report.id == report_id)
            )
            order = (
                await session.execute(
                    select(Order).where(Order.id == order_id).with_for_update()
                )
            ).scalar_one_or_none()
            report = await session.get(Report, report_id)
            user = await session.get(User, report.user_id) if report else None
            eligible = bool(
                report
                and report.report_type == ReportType.FULL.value
                and report.generation_state == ReportGenerationState.COMPLETED
                and (user_id is None or report.user_id == user_id)
                and user
                and user.account_status == "active"
                and user.has_matrix
                and order
                and order.report_id == report.id
                and order.status == OrderStatus.PAID
            )
            if not eligible:
                yield None
                return
            yield report, user, order

    @staticmethod
    def _valid_artifact(report: Report, artifact: bytes | None) -> bool:
        return bool(
            artifact and artifact.startswith(b"%PDF-") and len(artifact) == report.artifact_size_bytes
            and report.artifact_mime_type == "application/pdf" and report.artifact_sha256 == hashlib.sha256(artifact).hexdigest()
            and len(artifact) <= settings.telegram_document_max_bytes
        )


@dataclass(frozen=True)
class FullReportDeliveryReconciliationResult:
    missing_created: int = 0
    canceled_ineligible: int = 0
    claimed: int = 0
    dispatched: int = 0
    conflicts: int = 0
    errors: int = 0


class FullReportDeliveryReconciler:
    """Repair and dispatch durable full-report deliveries without sending Telegram."""

    def __init__(
        self,
        session_factory,
        dispatch: Callable[[uuid.UUID, int], None] | None = None,
    ) -> None:
        self._service = FullReportTelegramDeliveryService(session_factory)
        self._deliveries = self._service._deliveries
        self._dispatch = dispatch or self._dispatch_task

    @staticmethod
    def _dispatch_task(delivery_id: uuid.UUID, attempt: int) -> None:
        from core.tasks import deliver_full_report

        deliver_full_report.delay(str(delivery_id), attempt)

    async def reconcile_batch(
        self, *, now: datetime, limit: int
    ) -> FullReportDeliveryReconciliationResult:
        counters = {
            "missing_created": 0,
            "canceled_ineligible": 0,
            "claimed": 0,
            "dispatched": 0,
            "conflicts": 0,
            "errors": 0,
        }
        for delivery_id in await self._deliveries.list_ineligible_active_ids(limit):
            if await self._deliveries.cancel(delivery_id):
                counters["canceled_ineligible"] += 1
            else:
                counters["conflicts"] += 1

        for report_id in await self._deliveries.list_missing_automatic_report_ids(limit):
            try:
                delivery_id = await self._service.enqueue_automatic(report_id)
            except Exception:
                counters["errors"] += 1
                continue
            if delivery_id is not None:
                counters["missing_created"] += 1

        for delivery_id in await self._deliveries.list_reconcilable_ids(now, limit):
            attempt = await self._deliveries.claim(delivery_id, now)
            if attempt is None:
                counters["conflicts"] += 1
                continue
            counters["claimed"] += 1
            try:
                self._dispatch(delivery_id, attempt)
            except Exception:
                counters["errors"] += 1
            else:
                counters["dispatched"] += 1
        return FullReportDeliveryReconciliationResult(**counters)
