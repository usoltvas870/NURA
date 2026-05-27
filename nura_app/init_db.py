import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from core.models import Base


# DEPRECATED: используй alembic upgrade head
# create_all оставлен только для первого запуска на чистой БД без истории миграций
async def init_db():
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Database tables created successfully")


if __name__ == "__main__":
    asyncio.run(init_db())
