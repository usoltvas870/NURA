from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings

engine = create_async_engine(settings.database_url)


def get_async_sessionmaker():
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
