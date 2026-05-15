from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings


def create_engine():
    return create_async_engine(settings.database_url, pool_size=5, max_overflow=0)


def get_async_sessionmaker():
    return async_sessionmaker(create_engine(), class_=AsyncSession, expire_on_commit=False)
