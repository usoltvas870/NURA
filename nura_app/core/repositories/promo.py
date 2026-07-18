from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import PromoCode
from core.repositories.base import SQLAlchemyRepository


@dataclass(frozen=True)
class PromoReservation:
    promo: PromoCode | None
    reason: Literal["invalid", "expired", "exhausted"] | None = None


class PromoCodeRepository(SQLAlchemyRepository[PromoCode]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, PromoCode)

    async def get_by_code(self, code: str) -> PromoCode | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PromoCode).where(PromoCode.code == code)
            )
            return result.scalar_one_or_none()

    async def reserve(self, code: str) -> PromoReservation:
        """Atomically reserve one promo use before creating provider intent."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(PromoCode)
                .where(PromoCode.code == code)
                .with_for_update()
            )
            promo = result.scalar_one_or_none()
            if promo is None or not promo.is_active:
                return PromoReservation(None, "invalid")

            if promo.expires_at is not None:
                expires_at = promo.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return PromoReservation(None, "expired")

            if not 0 < promo.discount_percent < 100:
                return PromoReservation(None, "invalid")

            if (
                promo.max_uses is not None
                and promo.used_count + promo.reserved_count >= promo.max_uses
            ):
                return PromoReservation(None, "exhausted")

            promo.reserved_count += 1
            try:
                await session.commit()
                await session.refresh(promo)
            except Exception:
                await session.rollback()
                raise
            return PromoReservation(promo)

    async def release_reservation(self, promo_id) -> None:
        """Release a checkout reservation when its payment intent was not saved."""
        async with self._session_factory() as session:
            promo = await session.get(PromoCode, promo_id, with_for_update=True)
            if promo is None or promo.reserved_count == 0:
                return
            promo.reserved_count -= 1
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
