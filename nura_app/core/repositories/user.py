import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import User
from core.repositories.base import SQLAlchemyRepository


class UserRepository(SQLAlchemyRepository[User]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, User)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
        return await self.add(user)

    async def update_archetype(
        self,
        user_id: uuid.UUID,
        archetype: str,
        number: int,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.main_archetype = archetype
            user.main_archetype_number = number
            await session.commit()
            await session.refresh(user)
            return user

    async def update_subscription(
        self,
        user_id: uuid.UUID,
        status: str,
        until: datetime | None = None,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.subscription_status = status
            user.subscription_until = until
            await session.commit()
            await session.refresh(user)
            return user
