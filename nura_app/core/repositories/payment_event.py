"""Durable, fenced lifecycle for provider payment events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import PaymentEvent


@dataclass(frozen=True)
class EventClaim:
    event_id: uuid.UUID
    attempt_count: int


class PaymentEventRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_or_create_event(self, **values: object) -> tuple[PaymentEvent, bool, bool]:
        """Return canonical event, whether created, and a safe fingerprint mismatch flag."""
        event = PaymentEvent(id=uuid.uuid4(), **values)
        try:
            async with self._session.begin_nested():
                self._session.add(event)
                await self._session.flush()
            return event, True, False
        except IntegrityError:
            existing = await self.get_event(str(values["dedup_key"]))
            if existing is None:
                raise
            return existing, False, existing.payload_fingerprint != values["payload_fingerprint"]

    async def get_event(self, dedup_key: str) -> PaymentEvent | None:
        return (
            await self._session.execute(
                select(PaymentEvent).where(PaymentEvent.dedup_key == dedup_key)
            )
        ).scalar_one_or_none()

    async def claim_event(
        self, event_id: uuid.UUID, *, now: datetime, claim_ttl: timedelta
    ) -> EventClaim | None:
        stale_before = now - claim_ttl
        allowed = (PaymentEvent.processing_status == "received") | (
            (PaymentEvent.processing_status == "failed") & (PaymentEvent.retryable.is_(True))
        ) | (
            (PaymentEvent.processing_status == "processing")
            & (PaymentEvent.claimed_at < stale_before)
        )
        result = await self._session.execute(
            update(PaymentEvent)
            .where(and_(PaymentEvent.id == event_id, allowed))
            .values(
                processing_status="processing",
                attempt_count=PaymentEvent.attempt_count + 1,
                claimed_at=now,
                failed_at=None,
                retryable=False,
                error_code=None,
                error_detail=None,
            )
            .returning(PaymentEvent.id, PaymentEvent.attempt_count)
        )
        row = result.one_or_none()
        return EventClaim(*row) if row else None

    async def mark_processed(
        self, event_id: uuid.UUID, *, expected_attempt_count: int, now: datetime
    ) -> bool:
        result = await self._session.execute(
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.processing_status == "processing",
                PaymentEvent.attempt_count == expected_attempt_count,
            )
            .values(
                processing_status="processed", processed_at=now, failed_at=None,
                retryable=False, error_code=None, error_detail=None,
            )
        )
        return result.rowcount == 1

    async def mark_failed(
        self, event_id: uuid.UUID, *, expected_attempt_count: int, now: datetime,
        error_code: str, error_detail: str | None, retryable: bool,
    ) -> bool:
        result = await self._session.execute(
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.processing_status == "processing",
                PaymentEvent.attempt_count == expected_attempt_count,
            )
            .values(
                processing_status="failed", failed_at=now, processed_at=None,
                retryable=retryable, error_code=error_code[:64],
                error_detail=error_detail[:256] if error_detail else None,
            )
        )
        return result.rowcount == 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
