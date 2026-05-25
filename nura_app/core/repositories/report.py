import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Report, ReportType
from core.repositories.base import SQLAlchemyRepository


class ReportRepository(SQLAlchemyRepository[Report]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, Report)

    async def get_by_token(self, token: str) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(Report.token == token)
            )
            return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> list[Report]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(Report.user_id == user_id)
            )
            return list(result.scalars().all())

    async def get_by_user_id_and_type(
        self, user_id: uuid.UUID, report_type: ReportType
    ) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user_id,
                    Report.report_type == report_type.value,
                ).order_by(desc(Report.created_at)).limit(1)
            )
            return result.scalar_one_or_none()

    async def create(
        self,
        user_id: uuid.UUID,
        report_type: ReportType,
        token: str,
        matrix_data: dict[str, Any] | None = None,
        ai_analysis: dict[str, Any] | None = None,
        kitchen_analysis: dict[str, Any] | None = None,
    ) -> Report:
        report = Report(
            id=uuid.uuid4(),
            user_id=user_id,
            report_type=report_type.value,
            token=token,
            matrix_data=matrix_data,
            ai_analysis=ai_analysis,
            kitchen_analysis=kitchen_analysis,
        )
        return await self.add(report)
