"""Persistence primitives for resumable Telegram mini-report delivery."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from core.models import TelegramReportDelivery, TelegramReportDeliveryState


class TelegramReportDeliveryRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_or_create(self, *, generation_id: uuid.UUID, user_id: uuid.UUID, report_id: uuid.UUID) -> TelegramReportDelivery:
        async with self._session_factory() as session:
            delivery = TelegramReportDelivery(id=uuid.uuid4(), mini_report_generation_id=generation_id, user_id=user_id, report_id=report_id, purpose="mini_initial")
            session.add(delivery)
            try:
                await session.commit()
                return delivery
            except IntegrityError:
                await session.rollback()
                existing = (await session.execute(select(TelegramReportDelivery).where(TelegramReportDelivery.mini_report_generation_id == generation_id, TelegramReportDelivery.user_id == user_id, TelegramReportDelivery.purpose == "mini_initial"))).scalar_one()
                return existing

    async def get(
        self,
        delivery_id: uuid.UUID,
    ) -> TelegramReportDelivery | None:
        async with self._session_factory() as session:
            return await session.get(TelegramReportDelivery, delivery_id)

    async def claim(self, delivery_id: uuid.UUID, *, now: datetime) -> int | None:
        async with self._session_factory() as session:
            stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
            retryable_state = (
                TelegramReportDelivery.status.in_(
                    [
                        TelegramReportDeliveryState.PARTIALLY_DELIVERED,
                        TelegramReportDeliveryState.FAILED,
                    ]
                )
                & TelegramReportDelivery.retryable.is_(True)
            )
            stale_claim = (
                (TelegramReportDelivery.status == TelegramReportDeliveryState.DELIVERING)
                & (TelegramReportDelivery.claimed_at < stale_before)
            )
            eligible = (
                (TelegramReportDelivery.status == TelegramReportDeliveryState.PENDING)
                | retryable_state
                | stale_claim
            )
            result = await session.execute(
                update(TelegramReportDelivery)
                .where(TelegramReportDelivery.id == delivery_id, eligible)
                .values(
                    status=TelegramReportDeliveryState.DELIVERING,
                    retryable=True,
                    claimed_at=now,
                    attempt_count=TelegramReportDelivery.attempt_count + 1,
                )
                .returning(TelegramReportDelivery.attempt_count)
            )
            attempt = result.scalar_one_or_none()
            await session.commit()
            return attempt

    async def mark_text_sent(self, delivery_id: uuid.UUID, attempt: int, message_ids: list[int]) -> bool:
        return await self._update(delivery_id, attempt, text_status="sent", text_message_ids=message_ids)

    async def save_text_progress(self, delivery_id: uuid.UUID, attempt: int, message_ids: list[int]) -> bool:
        return await self._update(delivery_id, attempt, text_message_ids=message_ids)

    async def mark_document_sent(self, delivery_id: uuid.UUID, attempt: int, message_id: int) -> bool:
        return await self._update(delivery_id, attempt, document_status="sent", document_message_id=message_id)

    async def complete(self, delivery_id: uuid.UUID, attempt: int) -> bool:
        return await self._update(
            delivery_id,
            attempt,
            status=TelegramReportDeliveryState.DELIVERED,
            claimed_at=None,
            last_error_code=None,
        )

    async def fail(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        error_code: str,
        *,
        retryable: bool,
    ) -> bool:
        progress_exists = (
            (TelegramReportDelivery.text_status == "sent")
            | (TelegramReportDelivery.document_status == "sent")
            | (TelegramReportDelivery.text_message_ids.is_not(None))
        )
        return await self._update(
            delivery_id,
            attempt,
            status=case(
                (progress_exists, TelegramReportDeliveryState.PARTIALLY_DELIVERED),
                else_=TelegramReportDeliveryState.FAILED,
            ),
            retryable=retryable,
            claimed_at=None,
            last_error_code=error_code,
        )

    async def _update(self, delivery_id: uuid.UUID, attempt: int, **values: object) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(update(TelegramReportDelivery).where(TelegramReportDelivery.id == delivery_id, TelegramReportDelivery.status == TelegramReportDeliveryState.DELIVERING, TelegramReportDelivery.attempt_count == attempt).values(**values))
            await session.commit()
            return result.rowcount == 1
