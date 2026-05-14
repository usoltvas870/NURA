from typing import Generic, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import Base

ModelType = TypeVar("ModelType", bound=Base)


class SQLAlchemyRepository(Generic[ModelType]):
    def __init__(
        self,
        session_factory: async_sessionmaker,
        model: type[ModelType],
    ):
        self._session_factory = session_factory
        self._model = model

    async def add(self, obj: ModelType) -> ModelType:
        async with self._session_factory() as session:
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    async def get(self, id) -> ModelType | None:
        async with self._session_factory() as session:
            return await session.get(self._model, id)

    async def get_all(self) -> list[ModelType]:
        async with self._session_factory() as session:
            result = await session.execute(select(self._model))
            return list(result.scalars().all())

    async def update(self, obj: ModelType) -> ModelType:
        async with self._session_factory() as session:
            merged = await session.merge(obj)
            await session.commit()
            await session.refresh(merged)
            return merged

    async def delete(self, id) -> None:
        async with self._session_factory() as session:
            stmt = delete(self._model).where(self._model.id == id)
            await session.execute(stmt)
            await session.commit()
