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
from core.repositories.report import PRELAUNCH_FULL_REPORT_AUDIT_KEY

RETRYABLE_RECONCILIATION_DELAY_SECONDS = 300
PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT = "prelaunch-full-text-pdf-v1"


class FullReportTelegramDeliveryRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create(
        self, *, report_id: uuid.UUID, order_id: uuid.UUID | None, user_id: uuid.UUID,
        reason: str, request_key: str, artifact_sha256: str, artifact_size_bytes: int,
        chat_id: int | None, delivery_format_version: str = "full-text-pdf-v1",
    ) -> FullReportTelegramDelivery:
        async with self._session_factory() as session:
            active = await self._active_for_report(session, report_id)
            if active is not None:
                return active
            row = FullReportTelegramDelivery(
                id=uuid.uuid4(), report_id=report_id, order_id=order_id, user_id=user_id,
                delivery_reason=reason, request_key=request_key, artifact_sha256=artifact_sha256,
                artifact_size_bytes=artifact_size_bytes, telegram_chat_id_snapshot=chat_id,
                delivery_format_version=delivery_format_version,
            )
            session.add(row)
            try:
                await session.commit()
                return row
            except IntegrityError:
                await session.rollback()
                matching = (await session.execute(select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.report_id == report_id,
                    FullReportTelegramDelivery.delivery_reason == reason,
                    FullReportTelegramDelivery.request_key == request_key,
                ))).scalar_one_or_none()
                if matching is not None:
                    return matching
                active = await self._active_for_report(session, report_id)
                if active is not None:
                    return active
                raise

    async def get(self, delivery_id: uuid.UUID) -> FullReportTelegramDelivery | None:
        async with self._session_factory() as session:
            return await session.get(FullReportTelegramDelivery, delivery_id)

    async def get_existing_for_report(
        self, report_id: uuid.UUID
    ) -> FullReportTelegramDelivery | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(FullReportTelegramDelivery)
                .where(FullReportTelegramDelivery.report_id == report_id)
                .order_by(
                    FullReportTelegramDelivery.created_at,
                    FullReportTelegramDelivery.id,
                )
                .limit(1)
            )
            return result.scalar_one_or_none()

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
            delivery_exists = (
                select(FullReportTelegramDelivery.id)
                .where(
                    FullReportTelegramDelivery.report_id == Report.id,
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
                    ~delivery_exists,
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
        payment_ineligible = (
            (Order.id.is_(None)) | (Order.status != OrderStatus.PAID)
        )
        if settings.is_owner_prelaunch:
            payment_ineligible = payment_ineligible & (
                FullReportTelegramDelivery.delivery_format_version
                != PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT
            )
        async with self._session_factory() as session:
            result = await session.execute(
                select(FullReportTelegramDelivery.id)
                .outerjoin(Order, Order.id == FullReportTelegramDelivery.order_id)
                .where(active, payment_ineligible)
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
            # This is the same paid-order lock used around each Telegram call. A
            # stale claimant therefore cannot overtake an active sender whose call
            # is still in flight and turn its durable progress into a duplicate.
            delivery = await session.scalar(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.id == delivery_id
                ).with_for_update()
            )
            if delivery is None:
                return None
            if delivery.order_id is None:
                if (
                    not settings.is_owner_prelaunch
                    or delivery.delivery_format_version
                    != PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT
                ):
                    return None
                report = await session.get(
                    Report, delivery.report_id, with_for_update=True
                )
                user = await session.get(User, delivery.user_id)
                metadata = report.generation_metadata if report is not None else None
                if (
                    report is None
                    or user is None
                    or report.user_id != user.id
                    or report.generation_state != ReportGenerationState.COMPLETED
                    or not isinstance(metadata, dict)
                    or PRELAUNCH_FULL_REPORT_AUDIT_KEY not in metadata
                    or not user.telegram_id
                    or user.telegram_id
                    not in settings.prelaunch_telegram_allowed_ids
                ):
                    return None
            else:
                locked_order = await session.scalar(
                    select(Order.id)
                    .where(Order.id == delivery.order_id)
                    .with_for_update()
                )
                if locked_order is None:
                    return None
            eligible = (
                (FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.QUEUED)
                | ((FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.FAILED)
                   & FullReportTelegramDelivery.retryable.is_(True))
                | ((FullReportTelegramDelivery.status == FullReportTelegramDeliveryState.SENDING)
                   & (FullReportTelegramDelivery.claimed_at < stale_before))
            )
            result = await session.execute(
                update(FullReportTelegramDelivery)
                .where(FullReportTelegramDelivery.id == delivery_id, eligible)
                .values(
                    status=FullReportTelegramDeliveryState.SENDING,
                    claimed_at=now,
                    attempt_count=FullReportTelegramDelivery.attempt_count + 1,
                    retryable=True,
                    failed_at=None,
                    sent_at=None,
                    error_code=None,
                    error_detail=None,
                )
                .returning(FullReportTelegramDelivery.attempt_count)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return result.scalar_one_or_none()

    @staticmethod
    async def _active_for_report(session, report_id: uuid.UUID):
        result = await session.execute(
            select(FullReportTelegramDelivery)
            .where(
                FullReportTelegramDelivery.report_id == report_id,
                (
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
                ),
            )
            .order_by(FullReportTelegramDelivery.created_at, FullReportTelegramDelivery.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def complete(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        message_id: int | None = None,
        file_id: str | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            filters = [
                FullReportTelegramDelivery.id == delivery_id,
                FullReportTelegramDelivery.status
                == FullReportTelegramDeliveryState.SENDING,
                FullReportTelegramDelivery.attempt_count == attempt,
            ]
            if message_id is None:
                filters.extend(
                    (
                        FullReportTelegramDelivery.text_status == "sent",
                        FullReportTelegramDelivery.document_status == "sent",
                        FullReportTelegramDelivery.telegram_document_message_id.is_not(
                            None
                        ),
                    )
                )
            result = await session.execute(
                update(FullReportTelegramDelivery)
                .where(*filters)
                .values(
                    status=FullReportTelegramDeliveryState.COMPLETED,
                    claimed_at=None,
                    sent_at=datetime.now(timezone.utc),
                    retryable=False,
                    failed_at=None,
                    error_code=None,
                    error_detail=None,
                    **(
                        {
                            "text_status": "sent",
                            "document_status": "sent",
                            "telegram_document_message_id": message_id,
                            "telegram_file_id": file_id,
                        }
                        if message_id is not None
                        else {}
                    ),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def ensure_text_snapshot(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        chunks: list[str],
        payload_sha256: str,
    ) -> FullReportTelegramDelivery | None:
        """Persist immutable rendered chunks before the first external send."""
        async with self._session_factory() as session:
            result = await session.execute(
                update(FullReportTelegramDelivery)
                .where(
                    FullReportTelegramDelivery.id == delivery_id,
                    FullReportTelegramDelivery.status
                    == FullReportTelegramDeliveryState.SENDING,
                    FullReportTelegramDelivery.attempt_count == attempt,
                    FullReportTelegramDelivery.text_chunks_snapshot.is_(None),
                )
                .values(
                    text_chunks_snapshot=chunks,
                    text_payload_sha256=payload_sha256,
                    total_text_chunks=len(chunks),
                )
            )
            await session.commit()
            if result.rowcount != 1:
                return await session.get(FullReportTelegramDelivery, delivery_id)
            return await session.get(FullReportTelegramDelivery, delivery_id)

    async def save_text_progress(
        self, delivery_id: uuid.UUID, attempt: int, message_ids: list[int]
    ) -> bool:
        return await self._progress(
            delivery_id,
            attempt,
            text_message_ids=message_ids,
        )

    async def mark_text_sent(
        self, delivery_id: uuid.UUID, attempt: int, message_ids: list[int]
    ) -> bool:
        return await self._progress(
            delivery_id,
            attempt,
            text_message_ids=message_ids,
            text_status="sent",
        )

    async def mark_document_sent(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        message_id: int,
        file_id: str | None,
    ) -> bool:
        return await self._progress(
            delivery_id,
            attempt,
            document_status="sent",
            telegram_document_message_id=message_id,
            telegram_file_id=file_id,
        )

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

    async def _progress(
        self, delivery_id: uuid.UUID, attempt: int, **values: object
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(FullReportTelegramDelivery)
                .where(
                    FullReportTelegramDelivery.id == delivery_id,
                    FullReportTelegramDelivery.status
                    == FullReportTelegramDeliveryState.SENDING,
                    FullReportTelegramDelivery.attempt_count == attempt,
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount == 1
