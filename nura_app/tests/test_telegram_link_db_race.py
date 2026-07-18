import asyncio
import gc
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import Base, User
from core.repositories.user import UserRepository


@pytest_asyncio.fixture
async def file_backed_sqlite_engine(tmp_path: Path) -> AsyncIterator[tuple[AsyncEngine, Path]]:
    database_path = tmp_path / "telegram-link-race.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        connect_args={"timeout": 5},
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine, database_path
    finally:
        await engine.dispose()
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            database_path.with_name(f"{database_path.name}{suffix}").unlink(
                missing_ok=True
            )


async def _database_path(connection: AsyncSession) -> Path:
    rows = (await connection.execute(text("PRAGMA database_list"))).all()
    return Path(next(path for _, name, path in rows if name == "main"))


class _RaceCoordinator:
    def __init__(self) -> None:
        self.lookup_count = 0
        self.pre_commit_count = 0
        self.rollback_count = 0
        self.both_lookups_finished = asyncio.Event()
        self.both_flows_before_commit = asyncio.Event()
        self.allow_winner_commit = asyncio.Event()
        self.winner_commit_finished = asyncio.Event()
        self.allow_loser_commit = asyncio.Event()

    async def after_lookup(self) -> None:
        self.lookup_count += 1
        if self.lookup_count == 2:
            self.both_lookups_finished.set()
        await self.both_lookups_finished.wait()

    async def before_commit(self, is_winner: bool) -> None:
        self.pre_commit_count += 1
        if self.pre_commit_count == 2:
            self.both_flows_before_commit.set()
        await self.both_flows_before_commit.wait()
        if is_winner:
            await self.allow_winner_commit.wait()
        else:
            await self.allow_loser_commit.wait()


class _CoordinatedSession:
    def __init__(
        self,
        session: AsyncSession,
        coordinator: _RaceCoordinator,
        *,
        is_winner: bool,
    ) -> None:
        self.session = session
        self._coordinator = coordinator
        self._is_winner = is_winner

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    async def get(self, *args, **kwargs):
        return await self.session.get(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        result = await self.session.execute(*args, **kwargs)
        await self._coordinator.after_lookup()
        return result

    async def commit(self) -> None:
        await self._coordinator.before_commit(self._is_winner)
        await self.session.commit()
        if self._is_winner:
            self._coordinator.winner_commit_finished.set()

    async def rollback(self) -> None:
        self._coordinator.rollback_count += 1
        await self.session.rollback()


@pytest.mark.asyncio
async def test_file_backed_sqlite_uses_independent_physical_connections(
    file_backed_sqlite_engine: tuple[AsyncEngine, Path],
) -> None:
    engine, database_path = file_backed_sqlite_engine
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session_a, session_factory() as session_b:
        connection_a = await session_a.connection()
        connection_b = await session_b.connection()
        raw_connection_a = await connection_a.get_raw_connection()
        raw_connection_b = await connection_b.get_raw_connection()

        assert raw_connection_a.dbapi_connection is not raw_connection_b.dbapi_connection
        assert raw_connection_a.driver_connection is not raw_connection_b.driver_connection
        assert await _database_path(connection_a) == database_path
        assert await _database_path(connection_b) == database_path

        session_a.add(User(telegram_id=918273645))
        await session_a.commit()

        linked_user = await session_b.scalar(
            select(User).where(User.telegram_id == 918273645)
        )
        assert linked_user is not None


@pytest.mark.asyncio
async def test_file_backed_sqlite_applies_required_pragmas_and_shared_schema(
    file_backed_sqlite_engine: tuple[AsyncEngine, Path],
) -> None:
    engine, database_path = file_backed_sqlite_engine
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session_a, session_factory() as session_b:
        connection_a = await session_a.connection()
        connection_b = await session_b.connection()

        for connection in (connection_a, connection_b):
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert await connection.scalar(text("PRAGMA journal_mode")) == "wal"
            assert await connection.scalar(text("PRAGMA busy_timeout")) == 5000
            assert await _database_path(connection) == database_path

            tables = (await connection.execute(text("SELECT name FROM sqlite_master"))).scalars()
            assert "users" in tables.all()

            indexes = (await connection.execute(text("PRAGMA index_list('users')"))).all()
            telegram_index = next(
                index for index in indexes if index[2] and index[1] == "ix_users_telegram_id"
            )
            index_columns = (
                await connection.execute(text(f"PRAGMA index_info('{telegram_index[1]}')"))
            ).all()
            assert [column[2] for column in index_columns] == ["telegram_id"]


@pytest.mark.asyncio
async def test_concurrent_telegram_link_allows_exactly_one_winner(
    file_backed_sqlite_engine: tuple[AsyncEngine, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine, database_path = file_backed_sqlite_engine
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    for cycle in range(10):
        expected_profiles = {
            "a": {
                "name": f"Race user A {cycle}",
                "email": f"race-a-{cycle}@example.test",
                "vk_id": f"race-vk-a-{cycle}",
                "web_session_id": f"race-web-a-{cycle}",
            },
            "b": {
                "name": f"Race user B {cycle}",
                "email": f"race-b-{cycle}@example.test",
                "vk_id": f"race-vk-b-{cycle}",
                "web_session_id": f"race-web-b-{cycle}",
            },
        }
        async with session_factory() as seed_session:
            user_a = User(**expected_profiles["a"])
            user_b = User(**expected_profiles["b"])
            seed_session.add_all((user_a, user_b))
            await seed_session.commit()

        coordinator = _RaceCoordinator()
        winner_session = _CoordinatedSession(
            session_factory(), coordinator, is_winner=True
        )
        loser_session = _CoordinatedSession(
            session_factory(), coordinator, is_winner=False
        )
        winner_repository = UserRepository(lambda: winner_session)
        loser_repository = UserRepository(lambda: loser_session)
        candidate_telegram_id = 2_000_000_000 + cycle

        winner_connection = await winner_session.session.connection()
        loser_connection = await loser_session.session.connection()
        winner_raw_connection = await winner_connection.get_raw_connection()
        loser_raw_connection = await loser_connection.get_raw_connection()
        assert (
            winner_raw_connection.dbapi_connection
            is not loser_raw_connection.dbapi_connection
        )
        assert (
            winner_raw_connection.driver_connection
            is not loser_raw_connection.driver_connection
        )
        assert await _database_path(winner_connection) == database_path
        assert await _database_path(loser_connection) == database_path

        winner_task = asyncio.create_task(
            winner_repository.link_telegram_id_safely(user_a.id, candidate_telegram_id)
        )
        loser_task = asyncio.create_task(
            loser_repository.link_telegram_id_safely(user_b.id, candidate_telegram_id)
        )

        await asyncio.wait_for(coordinator.both_lookups_finished.wait(), timeout=5)
        assert coordinator.lookup_count == 2
        await asyncio.wait_for(coordinator.both_flows_before_commit.wait(), timeout=5)

        coordinator.allow_winner_commit.set()
        await asyncio.wait_for(coordinator.winner_commit_finished.wait(), timeout=5)
        coordinator.allow_loser_commit.set()

        assert await winner_task
        assert not await loser_task
        assert coordinator.rollback_count == 1

        winner = await loser_session.session.scalar(
            select(User)
            .where(User.id == user_a.id)
            .execution_options(populate_existing=True)
        )
        loser = await loser_session.session.scalar(
            select(User)
            .where(User.id == user_b.id)
            .execution_options(populate_existing=True)
        )
        row_count = await loser_session.session.scalar(select(func.count()).select_from(User))
        assert winner is not None
        assert loser is not None
        assert row_count == (cycle + 1) * 2
        assert winner.telegram_id == candidate_telegram_id
        assert loser.telegram_id is None
        for user, expected_profile in (
            (winner, expected_profiles["a"]),
            (loser, expected_profiles["b"]),
        ):
            assert user.name == expected_profile["name"]
            assert user.email == expected_profile["email"]
            assert user.vk_id == expected_profile["vk_id"]
            assert user.web_session_id == expected_profile["web_session_id"]

        async with session_factory() as verification_session:
            owners = (
                await verification_session.execute(
                    select(User).where(User.telegram_id == candidate_telegram_id)
                )
            ).scalars().all()
        assert [owner.id for owner in owners] == [user_a.id]
        assert all(owner.id in {user_a.id, user_b.id} for owner in owners)

        captured_output = caplog.text
        for sensitive_value in (
            str(candidate_telegram_id),
            str(user_a.id),
            str(user_b.id),
            str(database_path),
        ):
            assert sensitive_value not in captured_output
        assert "IntegrityError" not in captured_output
        assert "SELECT" not in captured_output
        assert "Traceback" not in captured_output

        await winner_session.session.close()
        await loser_session.session.close()
