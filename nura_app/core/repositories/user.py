import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Report, ReportType, User
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

    async def update_birth_date(
        self,
        user_id: uuid.UUID,
        birth_date: str,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.birth_date = birth_date
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

    async def update_tarot_subscription(
        self,
        user_id: uuid.UUID,
        active: bool,
        until: datetime | None = None,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.tarot_subscription = active
            user.tarot_subscription_until = until
            await session.commit()
            await session.refresh(user)
            return user

    async def update_has_matrix(
        self,
        user_id: uuid.UUID,
        has_matrix: bool,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.has_matrix = has_matrix
            if has_matrix:
                user.subscription_status = "premium"
            await session.commit()
            await session.refresh(user)
            return user

    async def get_users_with_tarot(self) -> list[User]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.tarot_subscription == True)  # noqa: E712
            )
            return list(result.scalars().all())

    async def mark_compatibility_used(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is not None:
                user.compatibility_used = True
                await session.commit()

    async def get_has_matrix(self, user_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user_id,
                    Report.report_type == ReportType.FULL.value,
                    Report.matrix_data.isnot(None),
                ).limit(1)
            )
            report = result.scalar_one_or_none()
            return report is not None
