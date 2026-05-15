from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings


def create_engine():
    return create_async_engine(settings.database_url)


def get_async_sessionmaker():
    engine = create_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
