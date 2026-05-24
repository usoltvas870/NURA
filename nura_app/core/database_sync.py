from sqlalchemy import create_engine as create_sync_engine

from core.config import settings

sync_engine = create_sync_engine(
    settings.database_url_sync,
    pool_size=5,
    max_overflow=0,
)
