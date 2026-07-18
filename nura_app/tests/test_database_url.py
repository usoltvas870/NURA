from sqlalchemy.engine import make_url

from core.database_url import normalize_sync_database_url


def test_normalize_sync_database_url_preserves_percent_encoded_password():
    normalized = normalize_sync_database_url(
        "postgresql+asyncpg://nura:p%40ss%2Fword@db.example:5432/nura"
    )

    parsed = make_url(normalized)
    assert parsed.drivername == "postgresql"
    assert parsed.password == "p@ss/word"
    assert parsed.host == "db.example"


def test_normalize_sync_database_url_rejects_whitespace():
    try:
        normalize_sync_database_url("postgresql://user:password@host/db\n")
    except ValueError as error:
        assert "whitespace" in str(error)
    else:
        raise AssertionError("Whitespace in DATABASE_URL must be rejected")
