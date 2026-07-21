import os

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings


def create_engine():
    return create_async_engine(settings.database_url, pool_size=5, max_overflow=0, pool_pre_ping=True)


_engine = None
_session_factory: async_sessionmaker | None = None
_engine_owner_pid: int | None = None
_database_state_creation_blocked = False


def reset_async_database_state_after_fork() -> None:
    """Detach inherited pool state without touching parent-owned connections."""
    global _engine, _session_factory, _engine_owner_pid
    global _database_state_creation_blocked

    _database_state_creation_blocked = False
    engine = _engine
    if engine is not None and _engine_owner_pid == os.getpid():
        return
    _engine = None
    _session_factory = None
    _engine_owner_pid = None
    if engine is not None:
        engine.sync_engine.dispose(close=False)


def block_async_database_state_creation() -> None:
    """Prevent shutdown cleanup from creating a replacement global engine."""
    global _database_state_creation_blocked

    _database_state_creation_blocked = True


async def dispose_async_database_state() -> None:
    """Dispose process-local async database state on its owning event loop."""
    global _engine, _session_factory, _engine_owner_pid

    engine = _engine
    owner_pid = _engine_owner_pid
    _engine = None
    _session_factory = None
    _engine_owner_pid = None
    if engine is None:
        return
    if owner_pid is not None and owner_pid != os.getpid():
        engine.sync_engine.dispose(close=False)
        return
    await engine.dispose()


def get_async_sessionmaker() -> async_sessionmaker:
    global _engine, _session_factory, _engine_owner_pid
    current_pid = os.getpid()
    if _engine_owner_pid is not None and _engine_owner_pid != current_pid:
        reset_async_database_state_after_fork()
    if _database_state_creation_blocked:
        raise RuntimeError("Async database state creation is blocked during shutdown")
    if _session_factory is None:
        _engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        _engine_owner_pid = current_pid
    return _session_factory


_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis
