import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from asyncpg.exceptions import PostgresConnectionError
from sqlalchemy import text

import core.celery_async as celery_async
import core.database as database


@dataclass(frozen=True)
class DisposablePostgres:
    container: str
    database: str
    username: str
    password: str
    url: str


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def disposable_postgres() -> Iterator[DisposablePostgres]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for disposable PostgreSQL coverage")
    if _docker("info", "--format", "{{.ServerVersion}}", check=False).returncode:
        pytest.skip("Docker daemon is unavailable")

    suffix = uuid.uuid4().hex[:12]
    container = f"nura-p43fb-{suffix}"
    username = f"nura_test_{suffix}"
    database_name = f"nura_test_{suffix}"
    password = secrets.token_hex(24)
    try:
        result = _docker(
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            "nura.test=p4-3fb-celery-async-lifecycle",
            "--env",
            f"POSTGRES_USER={username}",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "--env",
            f"POSTGRES_DB={database_name}",
            "--publish",
            "127.0.0.1::5432",
            "postgres:16-alpine",
        )
        assert result.stdout.strip()
        deadline = time.monotonic() + 30
        last_readiness_error = "PostgreSQL readiness probe did not run"
        while time.monotonic() < deadline:
            ready = _docker(
                "exec",
                container,
                "pg_isready",
                "--username",
                username,
                "--dbname",
                database_name,
                check=False,
            )
            query = _docker(
                "exec",
                "--env",
                "PGCONNECT_TIMEOUT=1",
                container,
                "psql",
                "--tuples-only",
                "--no-align",
                "--username",
                username,
                "--dbname",
                database_name,
                "--command",
                "SELECT 1",
                check=False,
            )
            if (
                ready.returncode == 0
                and query.returncode == 0
                and query.stdout.strip() == "1"
            ):
                break
            last_readiness_error = (
                query.stderr or ready.stderr or query.stdout or ready.stdout
            ).strip()
            time.sleep(0.25)
        else:
            pytest.fail(
                "Disposable PostgreSQL did not accept a readiness SELECT within 30s: "
                f"{last_readiness_error}"
            )

        mapping = _docker("port", container, "5432/tcp").stdout.strip()
        host, port = mapping.rsplit(":", 1)
        assert host in {"127.0.0.1", "localhost"}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", int(port)), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Disposable PostgreSQL loopback port is unavailable")
        yield DisposablePostgres(
            container=container,
            database=database_name,
            username=username,
            password=password,
            url=(
                f"postgresql+asyncpg://{username}:{password}"
                f"@127.0.0.1:{port}/{database_name}?ssl=disable"
            ),
        )
    finally:
        _docker("rm", "--force", container, check=False)


def _audit_state(postgres: DisposablePostgres) -> tuple[int, int, int]:
    query = (
        "SELECT count(*) FILTER (WHERE pid <> pg_backend_pid()), "
        "count(*) FILTER (WHERE pid <> pg_backend_pid() "
        "AND state = 'idle in transaction'), "
        "count(*) FILTER (WHERE pid <> pg_backend_pid() AND state = 'active') "
        "FROM pg_stat_activity WHERE datname = current_database()"
    )
    output = _docker(
        "exec",
        postgres.container,
        "psql",
        "--tuples-only",
        "--no-align",
        "--username",
        postgres.username,
        "--dbname",
        postgres.database,
        "--command",
        query,
    ).stdout.strip()
    total, idle_in_transaction, active = output.split("|")
    return int(total), int(idle_in_transaction), int(active)


@pytest.fixture
def isolated_celery_database_globals() -> Iterator[None]:
    saved_runtime = celery_async._runtime
    saved_database_state = (
        database._engine,
        database._session_factory,
        database._engine_owner_pid,
        database._database_state_creation_blocked,
    )
    celery_async._runtime = None
    database._engine = None
    database._session_factory = None
    database._engine_owner_pid = None
    database._database_state_creation_blocked = False
    try:
        yield
    finally:
        celery_async._reset_runtime_for_tests()
        (
            database._engine,
            database._session_factory,
            database._engine_owner_pid,
            database._database_state_creation_blocked,
        ) = saved_database_state
        celery_async._runtime = saved_runtime
        if saved_runtime is not None and not saved_runtime.loop.is_closed():
            asyncio.set_event_loop(saved_runtime.loop)


def test_persistent_runtime_with_disposable_postgres_16(
    disposable_postgres: DisposablePostgres,
    isolated_celery_database_globals: None,
    monkeypatch,
) -> None:
    postgres = disposable_postgres
    monkeypatch.setattr(database, "settings", SimpleNamespace(database_url=postgres.url))
    outcomes: list[str] = []
    connection_samples: list[tuple[int, int, int]] = []

    async def initialize() -> str:
        factory = database.get_async_sessionmaker()
        async with factory() as session, session.begin():
            version = (await session.execute(text("SHOW server_version"))).scalar_one()
            await session.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS celery_lifecycle_probe ("
                    "id UUID PRIMARY KEY, behavior TEXT NOT NULL)"
                )
            )
        return version

    for attempt in range(10):
        try:
            postgres_version = celery_async.run_celery_async(initialize())
            break
        except (ConnectionError, OSError, PostgresConnectionError):
            if attempt == 9:
                raise
            time.sleep(0.25)
    assert postgres_version.startswith("16.")
    loop_id = id(celery_async._runtime.loop)

    async def invoke(index: int, behavior: str) -> str:
        factory = database.get_async_sessionmaker()
        async with factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO celery_lifecycle_probe (id, behavior) "
                    "VALUES (:id, :behavior)"
                ),
                {"id": uuid.uuid4(), "behavior": behavior},
            )
            if behavior == "exception":
                raise ValueError(f"controlled-{index}")
            if behavior == "early":
                return "early"
        return "success"

    try:
        for index in range(20):
            behavior = ("success", "early", "exception")[index % 3]
            try:
                outcomes.append(celery_async.run_celery_async(invoke(index, behavior)))
            except ValueError:
                outcomes.append("exception")
            time.sleep(0.05)
            connection_samples.append(_audit_state(postgres))

        cleanup_complete = False

        async def cancelled_transaction() -> None:
            nonlocal cleanup_complete
            factory = database.get_async_sessionmaker()
            try:
                async with factory() as session, session.begin():
                    await session.execute(text("SELECT 1"))
                    raise asyncio.CancelledError
            finally:
                cleanup_complete = True

        with pytest.raises(asyncio.CancelledError):
            celery_async.run_celery_async(cancelled_transaction())

        assert cleanup_complete
        assert len(outcomes) == 20
        assert {"success", "early", "exception"} <= set(outcomes)
        assert celery_async._runtime is not None
        assert id(celery_async._runtime.loop) == loop_id
        assert database._engine_owner_pid == os.getpid()
        assert all(total <= 1 for total, _, _ in connection_samples)
        assert all(idle == 0 for _, idle, _ in connection_samples)
        assert all(active == 0 for _, _, active in connection_samples)
    finally:
        celery_async._on_worker_process_shutdown()

    time.sleep(0.1)
    assert _audit_state(postgres) == (0, 0, 0)
    assert database._engine is None
    assert database._session_factory is None
    assert database._engine_owner_pid is None
