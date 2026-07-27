"""Atomic persistence for full-report Telegram PDF deliveries."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from core.config import settings
from core.models import (
    FullReportTelegramDelivery,
    FullReportTelegramDeliveryState,
    Order,
    OrderStatus,
    Report,
    ReportGenerationState,
    ReportType,
    User,
)

RETRYABLE_RECONCILIATION_DELAY_SECONDS = 300


class FullReportTelegramDeliveryRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create(
        self, *, report_id: uuid.UUID, order_id: uuid.UUID | None, user_id: uuid.UUID,
        reason: str, request_key: str, artifact_sha256: str, artifact_size_bytes: int,
        chat_id: int | None,
    ) -> FullReportTelegramDelivery:
        async with self._session_factory() as session:
            row = FullReportTelegramDelivery(
                id=uuid.uuid4(), report_id=report_id, order_id=order_id, user_id=user_id,
                delivery_reason=reason, request_key=request_key, artifact_sha256=artifact_sha256,
                artifact_size_bytes=artifact_size_bytes, telegram_chat_id_snapshot=chat_id,
            )
            session.add(row)
            try:
                await session.commit()
                return row
            except IntegrityError:
                await session.rollback()
                return (await session.execute(select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.report_id == report_id,
                    FullReportTelegramDelivery.delivery_reason == reason,
                    FullReportTelegramDelivery.request_key == request_key,
                ))).scalar_one()

    async def get(self, delivery_id: uuid.UUID) -> FullReportTelegramDelivery | None:
        async with self._session_factory() as session:
            return await session.get(FullReportTelegramDelivery, delivery_id)

    async def owns_attempt(self, delivery_id: uuid.UUID, attempt: int) -> bool:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(FullReportTelegramDelivery.id).where(
                    FullReportTelegramDelivery.id == delivery_id,
                    FullReportTelegramDelivery.status
                    == FullReportTelegramDeliveryState.SENDING,
                    FullReportTelegramDelivery.attempt_count == attempt,
                )
            )
            return value is not None

    async def list_missing_automatic_report_ids(
        self, limit: int
    ) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            automatic_exists = (
                select(FullReportTelegramDelivery.id)
                .where(
                    FullReportTelegramDelivery.report_id == Report.id,
                    FullReportTelegramDelivery.delivery_reason == "automatic",
                )
                .exists()
            )
            result = await session.execute(
                select(Report.id)
                .join(Order, Order.id == Report.order_id)
                .join(User, User.id == Report.user_id)
                .where(
                    Report.report_type == ReportType.FULL.value,
                    Report.generation_state
                    == ReportGenerationState.COMPLETED,
                    Report.artifact_bytes.is_not(None),
                    Report.artifact_sha256.is_not(None),
                    Report.artifact_size_bytes.is_not(None),
                    Report.artifact_mime_type == "application/pdf",
                    Order.status == OrderStatus.PAID,
                    User.account_status == "active",
                    User.has_matrix.is_(True),
                    ~automatic_exists,
                )
                .order_by(Report.generated_at, Report.id)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_reconcilable_ids(
        self, now: datetime, limit: int
    ) -> list[uuid.UUID]:
        stale_before = now - timedelta(
            seconds=settings.telegram_delivery_claim_timeout_seconds
        )
        async with self._session_factory() as session:
            result = await session.execute(
                select(FullReportTelegramDelivery.id)
                .where(
                    (FullReportTelegramDelivery.status
                     == FullReportTelegramDeliveryState.QUEUED)
                    | (
                        (FullReportTelegramDelivery.status
                         == FullReportTelegramDeliveryState.FAILED)
                        & FullReportTelegramDelivery.retryable.is_(True)
                        & (
                            FullReportTelegramDelivery.failed_at
                            <= now
                            - timedelta(
                                seconds=RETRYABLE_RECONCILIATION_DELAY_SECONDS
                            )
                        )
                    )
                    | (
                        (FullReportTelegramDelivery.status
                         == FullReportTelegramDeliveryState.SENDING)
                        & (FullReportTelegramDelivery.claimed_at < stale_before)
                    )
                )
                .order_by(FullReportTelegramDelivery.queued_at, FullReportTelegramDelivery.id)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_ineligible_active_ids(self, limit: int) -> list[uuid.UUID]:
        active = (
            FullReportTelegramDelivery.status.in_(
                (
                    FullReportTelegramDeliveryState.QUEUED,
                    FullReportTelegramDeliveryState.SENDING,
                )
            )
            | (
                (FullReportTelegramDelivery.status
                 == FullReportTelegramDeliveryState.FAILED)
                & FullReportTelegramDelivery.retryable.is_(True)
            )
        )
        async with self._session_factory() as session:
            result = await session.execute(
                select(FullReportTelegramDelivery.id)
                .outerjoin(Order, Order.id == FullReportTelegramDelivery.order_id)
                .where(active, (Order.id.is_(None)) | (Order.status != OrderStatus.PAID))
                .order_by(FullReportTelegramDelivery.queued_at)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_canonical_file_id(self, report_id: uuid.UUID) -> str | None:
        """Return the newest reusable Telegram file ID from a completed send."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(FullReportTelegramDelivery.telegram_file_id)
                .where(
                    FullReportTelegramDelivery.report_id == report_id,
                    FullReportTelegramDelivery.status
                    == FullReportTelegramDeliveryState.COMPLETED,
                )
                .order_by(
                    FullReportTelegramDelivery.sent_at.desc(),
                    FullReportTelegramDelivery.created_at.desc(),
                    FullReportTelegramDelivery.id.desc(),
                )
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def claim(self, delivery_id: uuid.UUID, now: datetime) -> int | None:
        stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
        async with self._session_factory() as session:
            eligible = (
                (FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.QUEUED)
                | ((FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.FAILED)
                   & FullReportTelegramDelivery.retryable.is_(True))
                | ((FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.SENDING)
                   & (FullReportTelegramDelivery.claimed_at < stale_before))
            )
            result = await session.execute(update(FullReportTelegramDelivery).where(
                FullReportTelegramDelivery.id == delivery_id, eligible
            ).values(status=FullReportTelegramDeliveryState.SENDING, claimed_at=now,
                     attempt_count=FullReportTelegramDelivery.attempt_count + 1,
                     retryable=True, failed_at=None, sent_at=None,
                     error_code=None, error_detail=None).returning(FullReportTelegramDelivery.attempt_count))
            await session.commit()
            return result.scalar_one_or_none()

    async def complete(self, delivery_id: uuid.UUID, attempt: int, *, message_id: int, file_id: str | None) -> bool:
        return await self._terminal(delivery_id, attempt, status=FullReportTelegramDeliveryState.COMPLETED,
                                    sent_at=datetime.now(timezone.utc), telegram_document_message_id=message_id,
                                    telegram_file_id=file_id, retryable=False,
                                    failed_at=None, error_code=None, error_detail=None)

    async def fail(self, delivery_id: uuid.UUID, attempt: int, code: str, *, retryable: bool) -> bool:
        return await self._terminal(delivery_id, attempt, status=FullReportTelegramDeliveryState.FAILED,
                                    failed_at=datetime.now(timezone.utc), retryable=retryable,
                                    error_code=code[:64], error_detail=None)

    async def cancel(self, delivery_id: uuid.UUID, attempt: int | None = None) -> bool:
        async with self._session_factory() as session:
            filters = [FullReportTelegramDelivery.id == delivery_id,
                       FullReportTelegramDelivery.status.not_in((FullReportTelegramDeliveryState.COMPLETED, FullReportTelegramDeliveryState.CANCELED))]
            if attempt is not None:
                filters.append(FullReportTelegramDelivery.attempt_count == attempt)
            result = await session.execute(update(FullReportTelegramDelivery).where(*filters).values(
                status=FullReportTelegramDeliveryState.CANCELED, retryable=False, claimed_at=None,
                error_code="delivery_canceled", error_detail=None,
            ))
            await session.commit()
            return result.rowcount == 1

    async def _terminal(self, delivery_id: uuid.UUID, attempt: int, **values: object) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(update(FullReportTelegramDelivery).where(
                FullReportTelegramDelivery.id == delivery_id,
                FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.SENDING,
                FullReportTelegramDelivery.attempt_count == attempt,
            ).values(claimed_at=None, **values))
            await session.commit()
            return result.rowcount == 1
