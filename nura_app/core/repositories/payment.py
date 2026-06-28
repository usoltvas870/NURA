import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Payment, ReferralReward
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
    ) -> Payment:
        payment = Payment(
            id=uuid.uuid4(),
            user_id=user_id,
            amount=amount,
            yookassa_id=yookassa_id,
            payment_type=payment_type,
        )
        return await self.add(payment)

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
