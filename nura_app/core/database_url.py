"""Safe, driver-aware DATABASE_URL normalization for Alembic only."""

from __future__ import annotations

from sqlalchemy.engine import make_url


def normalize_sync_database_url(raw_url: str) -> str:
    """Return a synchronous SQLAlchemy URL without decoding credentials.

    ``DATABASE_URL`` is commonly supplied with percent-encoded passwords.  URL
    parsing must preserve that encoding; using ``unquote`` corrupts passwords
    containing a literal percent sequence and previously made Alembic unusable.
    """
    if not raw_url or any(char.isspace() for char in raw_url):
        raise ValueError("DATABASE_URL must be a non-empty URL without whitespace")

    url = make_url(raw_url)
    drivername = url.drivername
    if drivername == "postgres":
        drivername = "postgresql"
    elif drivername == "postgresql+asyncpg":
        drivername = "postgresql"
    elif "+" in drivername:
        dialect, _driver = drivername.split("+", 1)
        drivername = dialect

    return url.set(drivername=drivername).render_as_string(hide_password=False)
