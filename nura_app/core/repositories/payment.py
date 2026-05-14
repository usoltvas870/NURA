import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Payment
from core.repositories.base import SQLAlchemyRepository


class PaymentRepository(SQLAlchemyRepository[Payment]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, Payment)

    async def create(
        self,
        user_id: uuid.UUID,
        amount: int,
        yookassa_id: str | None = None,
    ) -> Payment:
        payment = Payment(
            id=uuid.uuid4(),
            user_id=user_id,
            amount=amount,
            yookassa_id=yookassa_id,
        )
        return await self.add(payment)

    async def get_by_yookassa_id(self, yookassa_id: str) -> Payment | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Payment).where(Payment.yookassa_id == yookassa_id)
            )
            return result.scalar_one_or_none()

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
