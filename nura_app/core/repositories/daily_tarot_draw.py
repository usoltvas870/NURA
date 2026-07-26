"""Atomic persistence operations for daily Tarot draws."""

import re
import uuid
from datetime import date, datetime

from sqlalchemy import false, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import DailyTarotDraw, DailyTarotDrawState

RETRYABLE_ERROR_CODES = frozenset({"daily_tarot_cancelled", "daily_tarot_provider_failure"})


class DailyTarotDrawRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_or_create(self, *, user_id: uuid.UUID, local_date: date, timezone_name: str) -> DailyTarotDraw:
        for _ in range(3):
            async with self._session_factory() as session:
                draw = DailyTarotDraw(
                    id=uuid.uuid4(), user_id=user_id, local_date=local_date,
                    timezone_name=timezone_name,
                )
                session.add(draw)
                try:
                    await session.commit()
                    await session.refresh(draw)
                    return draw
                except IntegrityError:
                    await session.rollback()
                    existing = (await session.execute(select(DailyTarotDraw).where(
                        DailyTarotDraw.user_id == user_id,
                        DailyTarotDraw.local_date == local_date,
                    ))).scalar_one_or_none()
                    if existing is not None:
                        return existing
        raise RuntimeError("daily_tarot_draw_conflict_unresolved")

    async def get(self, draw_id: uuid.UUID) -> DailyTarotDraw | None:
        async with self._session_factory() as session:
            return await session.get(DailyTarotDraw, draw_id)

    async def claim(
        self,
        draw_id: uuid.UUID,
        *,
        allow_retry: bool,
        arcana_number: int,
        now: datetime,
        stale_before: datetime,
    ) -> int | None:
        retryable_failure = (
            (DailyTarotDraw.status == DailyTarotDrawState.FAILED)
            & DailyTarotDraw.error_code.in_(RETRYABLE_ERROR_CODES)
        )
        retry_eligibility = retryable_failure if allow_retry else false()
        async with self._session_factory() as session:
            result = await session.execute(update(DailyTarotDraw).where(
                DailyTarotDraw.id == draw_id,
                (DailyTarotDraw.status == DailyTarotDrawState.PENDING)
                | retry_eligibility
                | (
                    (DailyTarotDraw.status == DailyTarotDrawState.GENERATING)
                    & (DailyTarotDraw.claimed_at < stale_before)
                ),
            ).values(
                status=DailyTarotDrawState.GENERATING,
                arcana_number=func.coalesce(DailyTarotDraw.arcana_number, arcana_number),
                attempt_count=DailyTarotDraw.attempt_count + 1,
                claimed_at=now,
                completed_at=None,
                failed_at=None,
                error_code=None,
                error_detail=None,
                updated_at=now,
            ).returning(DailyTarotDraw.attempt_count))
            attempt = result.scalar_one_or_none()
            await session.commit()
            return attempt

    async def complete(self, draw_id: uuid.UUID, *, attempt: int, interpretation: str, now: datetime) -> bool:
        if not interpretation.strip():
            raise ValueError("empty_daily_tarot_interpretation")
        async with self._session_factory() as session:
            result = await session.execute(update(DailyTarotDraw).where(
                DailyTarotDraw.id == draw_id,
                DailyTarotDraw.status == DailyTarotDrawState.GENERATING,
                DailyTarotDraw.attempt_count == attempt,
            ).values(
                status=DailyTarotDrawState.COMPLETED, interpretation=interpretation,
                completed_at=now,
                failed_at=None,
                error_code=None,
                error_detail=None,
                updated_at=now,
            ))
            await session.commit()
            return result.rowcount == 1

    async def fail(
        self,
        draw_id: uuid.UUID,
        *,
        attempt: int,
        error_code: str,
        now: datetime,
        error_detail: str | None = None,
    ) -> bool:
        if not re.fullmatch(r"[a-z0-9_]{1,64}", error_code):
            raise ValueError("invalid_daily_tarot_error_code")
        if error_detail is not None and (
            len(error_detail) > 256 or not re.fullmatch(r"[a-z0-9_ .:-]+", error_detail)
        ):
            raise ValueError("invalid_daily_tarot_error_detail")
        async with self._session_factory() as session:
            result = await session.execute(update(DailyTarotDraw).where(
                DailyTarotDraw.id == draw_id,
                DailyTarotDraw.status == DailyTarotDrawState.GENERATING,
                DailyTarotDraw.attempt_count == attempt,
            ).values(
                status=DailyTarotDrawState.FAILED, failed_at=now,
                completed_at=None,
                interpretation=None,
                error_code=error_code,
                error_detail=error_detail,
                updated_at=now,
            ))
            await session.commit()
            return result.rowcount == 1
