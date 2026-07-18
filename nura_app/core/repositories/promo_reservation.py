import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Payment, PromoCode, PromoReservation


class PromoReservationRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        before_capacity_claim: Callable[[], Awaitable[None]] | None = None,
    ):
        self._session_factory = session_factory
        self._before_capacity_claim = before_capacity_claim

    async def create_or_get(
        self, *, promo_code_id: uuid.UUID, user_id: uuid.UUID, payment_type: str,
        final_amount_kopecks: int, currency: str, idempotency_key: str, expires_at: datetime,
        report_token: str | None = None,
    ) -> PromoReservation:
        async with self._session_factory() as session:
            existing = (await session.execute(select(PromoReservation).where(PromoReservation.idempotency_key == idempotency_key))).scalar_one_or_none()
            if existing is not None:
                if not self._matches_checkout(
                    existing, promo_code_id, user_id, payment_type,
                    final_amount_kopecks, currency, report_token,
                ):
                    raise ValueError("idempotency_key_conflict")
                return existing
            await session.rollback()
            if final_amount_kopecks <= 0 or currency != "RUB":
                raise ValueError("invalid_promo_reservation")
            if self._before_capacity_claim is not None:
                await self._before_capacity_claim()
            claim_statement = (
                update(PromoCode)
                .where(
                    PromoCode.id == promo_code_id,
                    PromoCode.is_active.is_(True),
                    or_(
                        PromoCode.max_uses.is_(None),
                        PromoCode.used_count + PromoCode.reserved_count < PromoCode.max_uses,
                    ),
                )
                .values(reserved_count=PromoCode.reserved_count + 1)
            )
            for attempt in range(10):
                try:
                    claim = await session.execute(claim_statement)
                    break
                except OperationalError:
                    await session.rollback()
                    if attempt == 9:
                        raise
                    await asyncio.sleep(0)
            if claim.rowcount != 1:
                await session.rollback()
                promo = await session.get(PromoCode, promo_code_id)
                invalid_promo = promo is None or not promo.is_active
                await session.rollback()
                if invalid_promo:
                    raise ValueError("invalid_promo_reservation")
                raise ValueError("promo_capacity_exhausted")
            reservation = PromoReservation(id=uuid.uuid4(), promo_code_id=promo_code_id, user_id=user_id, payment_type=payment_type, final_amount_kopecks=final_amount_kopecks, currency=currency, idempotency_key=idempotency_key, report_token=report_token, expires_at=expires_at)
            try:
                session.add(reservation)
                await session.commit()
                await session.refresh(reservation)
            except IntegrityError:
                await session.rollback()
                existing = (await session.execute(select(PromoReservation).where(PromoReservation.idempotency_key == idempotency_key))).scalar_one_or_none()
                if existing is not None:
                    if not self._matches_checkout(
                        existing, promo_code_id, user_id, payment_type,
                        final_amount_kopecks, currency, report_token,
                    ):
                        raise ValueError("idempotency_key_conflict")
                    return existing
                raise
            except Exception:
                await session.rollback()
                raise
            return reservation

    @staticmethod
    def _matches_checkout(
        reservation: PromoReservation,
        promo_code_id: uuid.UUID,
        user_id: uuid.UUID,
        payment_type: str,
        final_amount_kopecks: int,
        currency: str,
        report_token: str | None,
    ) -> bool:
        return (
            reservation.promo_code_id == promo_code_id
            and reservation.user_id == user_id
            and reservation.payment_type == payment_type
            and reservation.final_amount_kopecks == final_amount_kopecks
            and reservation.currency == currency
            and reservation.report_token == report_token
        )

    async def attach_provider_payment(self, reservation_id: uuid.UUID, provider_payment_id: str) -> PromoReservation:
        return await self._attach(reservation_id, "provider_payment_id", provider_payment_id)

    async def get_by_payment_id(self, payment_id: uuid.UUID) -> PromoReservation | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PromoReservation).where(PromoReservation.payment_id == payment_id)
            )
            return result.scalar_one_or_none()

    async def attach_local_payment(self, reservation_id: uuid.UUID, payment_id: uuid.UUID) -> PromoReservation:
        async with self._session_factory() as session:
            reservation = await session.get(PromoReservation, reservation_id, with_for_update=True)
            payment = await session.get(Payment, payment_id)
            if reservation is None or payment is None or payment.user_id != reservation.user_id or payment.payment_type != reservation.payment_type:
                raise ValueError("invalid_reservation_transition")
            if reservation.state != "reserved" or (reservation.payment_id is not None and reservation.payment_id != payment_id):
                raise ValueError("reservation_attachment_conflict")
            reservation.payment_id = payment_id
            try:
                await session.commit()
                await session.refresh(reservation)
            except IntegrityError:
                await session.rollback()
                raise ValueError("reservation_attachment_conflict") from None
            except Exception:
                await session.rollback()
                raise
            return reservation

    async def _attach(self, reservation_id: uuid.UUID, field: str, value: object) -> PromoReservation:
        async with self._session_factory() as session:
            reservation = await session.get(PromoReservation, reservation_id, with_for_update=True)
            if reservation is None or reservation.state != "reserved":
                raise ValueError("invalid_reservation_transition")
            current = getattr(reservation, field)
            if current is not None and current != value:
                raise ValueError("reservation_attachment_conflict")
            setattr(reservation, field, value)
            try:
                await session.commit()
                await session.refresh(reservation)
            except IntegrityError:
                await session.rollback()
                raise ValueError("reservation_attachment_conflict") from None
            except Exception:
                await session.rollback()
                raise
            return reservation

    async def mark_consumed(self, reservation_id: uuid.UUID) -> PromoReservation:
        return await self._mark_terminal(reservation_id, "consumed")

    async def mark_released(self, reservation_id: uuid.UUID) -> PromoReservation:
        return await self._mark_terminal(reservation_id, "released")

    async def _mark_terminal(self, reservation_id: uuid.UUID, state: str) -> PromoReservation:
        async with self._session_factory() as session:
            reservation = await session.get(PromoReservation, reservation_id, with_for_update=True)
            if reservation is None or reservation.state not in {"reserved", state}:
                raise ValueError("invalid_reservation_transition")
            if reservation.state == state:
                return reservation
            promo = await session.get(PromoCode, reservation.promo_code_id, with_for_update=True)
            if promo is None or promo.reserved_count <= 0:
                raise ValueError("invalid_reservation_transition")
            promo.reserved_count -= 1
            if state == "consumed":
                promo.used_count += 1
            reservation.state = state
            if state == "consumed":
                reservation.consumed_at = datetime.now(timezone.utc)
            else:
                reservation.released_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(reservation)
            return reservation

    async def list_stale_nonterminal(self, before: datetime, limit: int = 100) -> list[PromoReservation]:
        async with self._session_factory() as session:
            result = await session.execute(select(PromoReservation).where(PromoReservation.state == "reserved", PromoReservation.expires_at < before).order_by(PromoReservation.expires_at, PromoReservation.id).limit(limit))
            return list(result.scalars())
