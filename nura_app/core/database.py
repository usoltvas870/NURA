import threading

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

_engine = None
_lock = threading.Lock()


def create_engine():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = create_async_engine(settings.database_url)
    return _engine


def get_async_sessionmaker():
    return async_sessionmaker(create_engine(), class_=AsyncSession, expire_on_commit=False)
