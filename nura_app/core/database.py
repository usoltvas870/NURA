from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings


def create_engine():
    return create_async_engine(settings.database_url, pool_size=5, max_overflow=0)


def get_async_sessionmaker():
    return async_sessionmaker(create_engine(), class_=AsyncSession, expire_on_commit=False)


_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis
