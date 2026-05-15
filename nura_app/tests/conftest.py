import uuid

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from core.models import Base, Report, ReportType, User
from core.services.matrix import MatrixService


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PgUUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(32)"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session):
    user = User(
        id=uuid.uuid4(),
        telegram_id=123456789,
        username="testuser",
        first_name="Test",
        birth_date="01.01.2000",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_report(test_user, db_session):
    report = Report(
        id=uuid.uuid4(),
        user_id=test_user.id,
        report_type=ReportType.MINI.value,
        token="test-token-001",
        matrix_data={"birth_date": "01.01.2000", "center": 8},
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    return report


@pytest.fixture
def sample_matrix():
    return MatrixService.calculate("01.01.2000")
