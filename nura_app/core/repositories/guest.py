import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import GuestProfile
from core.repositories.base import SQLAlchemyRepository


class GuestProfileRepository(SQLAlchemyRepository[GuestProfile]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, GuestProfile)

    async def get_by_token(self, token: str) -> GuestProfile | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(GuestProfile).where(GuestProfile.guest_token == token)
            )
            return result.scalar_one_or_none()

    async def create(
        self,
        token: str,
        expires_at: datetime,
        name: str | None = None,
        birth_date: str | None = None,
        quiz_answers: dict | None = None,
        report_data: dict | None = None,
    ) -> GuestProfile:
        guest = GuestProfile(
            id=uuid.uuid4(),
            guest_token=token,
            name=name,
            birth_date=birth_date,
            quiz_answers=quiz_answers,
            report_data=report_data,
            expires_at=expires_at,
        )
        return await self.add(guest)

    async def mark_merged(self, guest_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            guest = await session.get(GuestProfile, guest_id)
            if guest is None:
                return
            guest.merged_to_user_id = user_id
            await session.commit()

    async def save_report_data(
        self, guest_token: str, report_data: dict
    ) -> GuestProfile | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(GuestProfile).where(GuestProfile.guest_token == guest_token)
            )
            guest = result.scalar_one_or_none()
            if guest is None:
                return None
            guest.report_data = report_data
            await session.commit()
            await session.refresh(guest)
            return guest

    async def delete_by_id(self, guest_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(GuestProfile).where(GuestProfile.id == guest_id)
            )
            await session.commit()

    async def delete_expired(self, now: datetime) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(GuestProfile).where(GuestProfile.expires_at < now)
            )
            await session.commit()
            return result.rowcount or 0