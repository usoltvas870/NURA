import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Payment, PromoCode, ReferralReward
from core.repositories.base import SQLAlchemyRepository


class PaymentRepository(SQLAlchemyRepository[Payment]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, Payment)

    async def create(
        self,
        user_id: uuid.UUID,
        amount: int,
        yookassa_id: str | None = None,
        payment_type: str = "subscription",
        promo_code_id: uuid.UUID | None = None,
        amount_kopecks: int | None = None,
        promo_reserved: bool = False,
    ) -> Payment:
        payment = Payment(
            id=uuid.uuid4(),
            user_id=user_id,
            amount=amount,
            yookassa_id=yookassa_id,
            payment_type=payment_type,
            promo_code_id=promo_code_id,
            amount_kopecks=amount_kopecks,
            promo_reserved_at=(
                datetime.now(timezone.utc) if promo_code_id is not None and promo_reserved else None
            ),
        )
        async with self._session_factory() as session:
            try:
                session.add(payment)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return payment

    async def create_or_get_by_yookassa_id(
        self,
        *,
        user_id: uuid.UUID,
        amount: int,
        amount_kopecks: int,
        yookassa_id: str,
        payment_type: str,
        promo_code_id: uuid.UUID | None = None,
    ) -> Payment:
        existing = await self.get_by_yookassa_id(yookassa_id)
        if existing is not None:
            self._validate_checkout_payment(
                existing, user_id, amount_kopecks, payment_type, promo_code_id
            )
            return existing
        try:
            payment = await self.create(
                user_id=user_id,
                amount=amount,
                amount_kopecks=amount_kopecks,
                yookassa_id=yookassa_id,
                payment_type=payment_type,
                promo_code_id=promo_code_id,
                promo_reserved=False,
            )
        except IntegrityError:
            existing = await self.get_by_yookassa_id(yookassa_id)
            if existing is None:
                raise
            self._validate_checkout_payment(
                existing, user_id, amount_kopecks, payment_type, promo_code_id
            )
            return existing
        return payment

    @staticmethod
    def _validate_checkout_payment(
        payment: Payment,
        user_id: uuid.UUID,
        amount_kopecks: int,
        payment_type: str,
        promo_code_id: uuid.UUID | None,
    ) -> None:
        if (
            payment.user_id != user_id
            or payment.payment_type != payment_type
            or payment.amount_kopecks != amount_kopecks
            or payment.promo_code_id != promo_code_id
        ):
            raise ValueError("payment_attachment_conflict")

    async def mark_promo_consumed_without_accounting(self, payment_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None or payment.promo_consumed_at is not None:
                return
            payment.promo_consumed_at = datetime.now(timezone.utc)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def consume_promo(self, payment_id: uuid.UUID) -> bool:
        """Consume the promo linked to a verified payment exactly once."""
        async with self._session_factory() as session:
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None or payment.promo_code_id is None:
                return payment is not None
            if payment.promo_consumed_at is not None:
                return True

            promo = await session.get(
                PromoCode, payment.promo_code_id, with_for_update=True
            )
            if promo is None:
                return False
            if payment.promo_reserved_at is not None:
                if promo.reserved_count <= 0:
                    return False
                promo.reserved_count -= 1
                payment.promo_reserved_at = None
            elif promo.max_uses is not None and promo.used_count >= promo.max_uses:
                return False
            promo.used_count += 1
            payment.promo_consumed_at = datetime.now(timezone.utc)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return True

    async def release_consumed_promo(self, payment_id: uuid.UUID) -> None:
        """Undo promo consumption when entitlement activation is rolled back."""
        async with self._session_factory() as session:
            payment = await session.get(Payment, payment_id, with_for_update=True)
            if payment is None or payment.promo_code_id is None:
                return
            if payment.promo_consumed_at is None:
                return

            promo = await session.get(
                PromoCode, payment.promo_code_id, with_for_update=True
            )
            if promo is not None and promo.used_count > 0:
                promo.used_count -= 1
                promo.reserved_count += 1
            payment.promo_consumed_at = None
            payment.promo_reserved_at = datetime.now(timezone.utc)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def get_by_yookassa_id(self, yookassa_id: str) -> Payment | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Payment).where(Payment.yookassa_id == yookassa_id)
            )
            return result.scalar_one_or_none()

    async def claim_succeeded(self, yookassa_id: str) -> Payment | None:
        """
        Atomically fetch and mark payment as succeeded.

        Uses SELECT ... FOR UPDATE to prevent concurrent claims (TOCTOU-safe).
        Returns Payment if successfully claimed (status was pending),
        None if payment not found or already succeeded.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(Payment)
                .where(Payment.yookassa_id == yookassa_id)
                .with_for_update()
            )
            payment = result.scalar_one_or_none()
            if payment is None:
                return None
            if payment.status == "succeeded":
                return None
            payment.status = "succeeded"
            await session.commit()
            await session.refresh(payment)
            return payment

    async def delete_by_user_id(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(ReferralReward).where(
                    (ReferralReward.referrer_id == user_id)
                    | (ReferralReward.referred_id == user_id)
                )
            )
            await session.execute(
                delete(Payment).where(Payment.user_id == user_id)
            )
            await session.commit()

    async def update_status(
        self,
        payment_id: uuid.UUID,
        status: str,
    ) -> Payment | None:
        async with self._session_factory() as session:
            payment = await session.get(Payment, payment_id)
            if payment is None:
                return None
            payment.status = status
            await session.commit()
            await session.refresh(payment)
            return payment
