import asyncio
import logging
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded

import core.celery_async as celery_async
import core.database as database


@pytest.fixture(autouse=True)
def clean_runtime() -> None:
    celery_async._reset_runtime_for_tests()
    database.reset_async_database_state_after_fork()
    yield
    celery_async._reset_runtime_for_tests()
    database.reset_async_database_state_after_fork()


def test_lazy_runtime_reuses_loop_for_success_and_early_return() -> None:
    async def loop_identity(value: str) -> tuple[str, int]:
        return value, id(asyncio.get_running_loop())

    first = celery_async.run_celery_async(loop_identity("success"))
    second = celery_async.run_celery_async(loop_identity("early"))

    assert first[0] == "success"
    assert second[0] == "early"
    assert first[1] == second[1]
    assert celery_async._runtime is not None
    assert celery_async._runtime.owner_pid == os.getpid()
    assert celery_async._runtime.owner_thread_id == threading.get_ident()


def test_ordinary_exception_is_preserved() -> None:
    error = ValueError("original failure")

    async def fail() -> None:
        raise error

    with pytest.raises(ValueError) as raised:
        celery_async.run_celery_async(fail())

    assert raised.value is error
    assert celery_async.run_celery_async(asyncio.sleep(0, result="healthy")) == "healthy"


def test_child_tasks_are_cancelled_and_drained() -> None:
    cancelled = False

    async def child() -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    async def root() -> str:
        asyncio.create_task(child())
        await asyncio.sleep(0)
        return "done"

    assert celery_async.run_celery_async(root()) == "done"
    assert cancelled
    assert celery_async._runtime is not None
    assert not asyncio.all_tasks(celery_async._runtime.loop)


def test_cancellation_drain_has_a_hard_deadline(monkeypatch) -> None:
    stubborn_task: asyncio.Task | None = None

    async def stubborn_child() -> None:
        deadline = asyncio.get_running_loop().time() + 0.2
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass

    async def root() -> None:
        nonlocal stubborn_task
        stubborn_task = asyncio.create_task(stubborn_child())
        await asyncio.sleep(0)

    monkeypatch.setattr(celery_async, "_CLEANUP_TIMEOUT_SECONDS", 0.02)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="cleanup failed"):
        celery_async.run_celery_async(root())
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
    assert celery_async._runtime is not None
    assert celery_async._runtime.broken
    assert stubborn_task is not None
    celery_async._runtime.loop.run_until_complete(asyncio.sleep(0.25))
    assert stubborn_task.done()


def test_nested_execution_fails_closed_without_leaking_coroutine() -> None:
    async def nested() -> None:
        with pytest.raises(RuntimeError, match="Nested or concurrent"):
            celery_async.run_celery_async(asyncio.sleep(0))

    celery_async.run_celery_async(nested())


def test_foreign_thread_fails_closed() -> None:
    celery_async.run_celery_async(asyncio.sleep(0))
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            celery_async.run_celery_async(asyncio.sleep(0))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(timeout=5)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "cross threads" in str(errors[0])


def test_pid_mismatch_detaches_database_and_creates_new_runtime(monkeypatch) -> None:
    resets: list[int] = []
    celery_async.run_celery_async(asyncio.sleep(0))
    original_runtime = celery_async._runtime
    assert original_runtime is not None

    monkeypatch.setattr(celery_async.os, "getpid", lambda: original_runtime.owner_pid + 1)
    monkeypatch.setattr(
        celery_async,
        "reset_async_database_state_after_fork",
        lambda: resets.append(1),
    )

    celery_async.run_celery_async(asyncio.sleep(0))

    assert resets == [1]
    assert celery_async._runtime is not original_runtime
    assert celery_async._runtime is not None
    assert celery_async._runtime.owner_pid == original_runtime.owner_pid + 1
    celery_async._runtime.loop.close()
    celery_async._runtime = None
    original_runtime.loop.close()


def test_worker_signal_init_only_runs_after_prefork(monkeypatch) -> None:
    resets: list[int] = []
    monkeypatch.setattr(celery_async, "_IMPORT_PID", os.getpid() - 1)
    monkeypatch.setattr(
        celery_async,
        "reset_async_database_state_after_fork",
        lambda: resets.append(1),
    )

    celery_async._on_worker_process_init()
    first_loop = celery_async._runtime.loop
    celery_async._on_worker_process_init()

    assert celery_async._runtime is not None
    assert celery_async._runtime.loop is first_loop
    assert resets == [1]


def test_worker_signal_in_same_process_defers_runtime_without_error(caplog) -> None:
    """Solo workers initialize lazily when their first task needs the loop."""
    with caplog.at_level(logging.ERROR, logger="core.celery_async"):
        celery_async._on_worker_process_init()

    assert celery_async._runtime is None
    assert "runtime initialization" not in caplog.text


def test_shutdown_disposes_before_closing_loop_and_is_idempotent(monkeypatch) -> None:
    events: list[str] = []
    celery_async.run_celery_async(asyncio.sleep(0))
    runtime = celery_async._runtime
    assert runtime is not None

    async def dispose() -> None:
        assert asyncio.get_running_loop() is runtime.loop
        assert not runtime.loop.is_closed()
        events.append("dispose")

    monkeypatch.setattr(celery_async, "dispose_async_database_state", dispose)

    celery_async._on_worker_process_shutdown()
    celery_async._on_worker_process_shutdown()

    assert events == ["dispose"]
    assert runtime.loop.is_closed()
    assert celery_async._runtime is None


def test_shutdown_drains_pending_tasks_before_database_disposal(monkeypatch) -> None:
    events: list[str] = []
    celery_async.run_celery_async(asyncio.sleep(0))
    runtime = celery_async._runtime
    assert runtime is not None

    async def pending() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            events.append("task-cleanup")

    async def create_pending() -> None:
        asyncio.create_task(pending())
        await asyncio.sleep(0)

    runtime.loop.run_until_complete(create_pending())

    async def dispose() -> None:
        events.append("dispose")

    monkeypatch.setattr(celery_async, "dispose_async_database_state", dispose)
    celery_async._on_worker_process_shutdown()

    assert events == ["task-cleanup", "dispose"]


def test_shutdown_blocks_pending_task_from_creating_replacement_engine() -> None:
    blocked = False
    celery_async.run_celery_async(asyncio.sleep(0))
    runtime = celery_async._runtime
    assert runtime is not None

    async def pending() -> None:
        nonlocal blocked
        try:
            await asyncio.Event().wait()
        finally:
            with pytest.raises(RuntimeError, match="blocked during shutdown"):
                database.get_async_sessionmaker()
            blocked = True

    async def create_pending() -> None:
        asyncio.create_task(pending())
        await asyncio.sleep(0)

    runtime.loop.run_until_complete(create_pending())
    celery_async._on_worker_process_shutdown()

    assert blocked
    assert database._engine is None
    assert database._session_factory is None


def test_runtime_initialization_preserves_same_pid_database_engine() -> None:
    class SyncEngine:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        def dispose(self, *, close: bool) -> None:
            self.calls.append(close)

    class Engine:
        def __init__(self) -> None:
            self.sync_engine = SyncEngine()
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    engine = Engine()
    factory = object()
    database._engine = engine
    database._session_factory = factory
    database._engine_owner_pid = os.getpid()

    celery_async.run_celery_async(asyncio.sleep(0))

    assert database._engine is engine
    assert database._session_factory is factory
    assert engine.sync_engine.calls == []


def test_failed_cleanup_marks_runtime_broken_without_logging_secret(
    monkeypatch,
    caplog,
) -> None:
    secret = "database-secret-must-not-leak"

    def fail_cleanup(*_args) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(celery_async, "_drain_invocation_tasks", fail_cleanup)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        celery_async.run_celery_async(asyncio.sleep(0, result="done"))

    assert secret not in caplog.text
    assert celery_async._runtime is not None
    assert celery_async._runtime.broken


def test_database_factory_resets_inherited_pid(monkeypatch) -> None:
    class SyncEngine:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        def dispose(self, *, close: bool) -> None:
            self.calls.append(close)

    class Engine:
        def __init__(self) -> None:
            self.sync_engine = SyncEngine()

    inherited = Engine()
    replacement = Engine()
    database._engine = inherited
    database._session_factory = object()
    database._engine_owner_pid = os.getpid() - 1
    monkeypatch.setattr(database, "create_async_engine", lambda *_args, **_kwargs: replacement)
    monkeypatch.setattr(database, "async_sessionmaker", lambda *_args, **_kwargs: "factory")

    assert database.get_async_sessionmaker() == "factory"
    assert inherited.sync_engine.calls == [False]
    assert database._engine is replacement
    assert database._engine_owner_pid == os.getpid()


def test_database_dispose_clears_factory_even_when_dispose_fails() -> None:
    class Engine:
        async def dispose(self) -> None:
            raise RuntimeError("dispose failed")

    database._engine = Engine()
    database._session_factory = object()
    database._engine_owner_pid = os.getpid()

    with pytest.raises(RuntimeError, match="dispose failed"):
        asyncio.run(database.dispose_async_database_state())

    assert database._engine is None
    assert database._session_factory is None
    assert database._engine_owner_pid is None


def _fork_child(connection: Connection) -> None:
    try:
        celery_async._on_worker_process_init()

        async def identity() -> tuple[int, int]:
            database.get_async_sessionmaker()
            return os.getpid(), id(asyncio.get_running_loop())

        first = celery_async.run_celery_async(identity())
        second = celery_async.run_celery_async(identity())
        owner_pid = database._engine_owner_pid
        celery_async._on_worker_process_shutdown()
        connection.send((first, second, owner_pid, celery_async._runtime is None))
    except BaseException as exc:
        connection.send((type(exc).__name__, str(exc)))
    finally:
        connection.close()


def _fork_proof_process(connection: Connection) -> None:
    nested_parent: Connection | None = None
    process: multiprocessing.Process | None = None
    try:
        parent_result = celery_async.run_celery_async(
            asyncio.sleep(0, result=os.getpid())
        )
        parent_runtime = celery_async._runtime
        assert parent_runtime is not None
        context = multiprocessing.get_context("fork")
        nested_parent, nested_child = context.Pipe(duplex=False)
        process = context.Process(target=_fork_child, args=(nested_child,))
        process.start()
        nested_child.close()
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        assert process.exitcode == 0
        assert nested_parent.poll(timeout=2)
        child_result = nested_parent.recv()
        connection.send(
            (
                "ok",
                child_result,
                parent_result,
                os.getpid(),
                celery_async._runtime is parent_runtime,
                parent_runtime.loop.is_closed(),
            )
        )
    except BaseException as exc:
        connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        if process is not None and process.is_alive():
            process.kill()
            process.join(timeout=5)
        if nested_parent is not None:
            nested_parent.close()
        celery_async._reset_runtime_for_tests()
        connection.close()


def _signal_proof_process(connection: Connection) -> None:
    cleaned = False
    started = threading.Event()
    previous = signal.getsignal(signal.SIGUSR1)
    timer: threading.Timer | None = None

    def interrupt(_signum, _frame) -> None:
        raise SoftTimeLimitExceeded()

    async def interrupted() -> None:
        nonlocal cleaned
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned = True

    try:
        signal.signal(signal.SIGUSR1, interrupt)
        timer = threading.Timer(0.1, os.kill, args=(os.getpid(), signal.SIGUSR1))
        timer.start()
        soft_timeout_seen = False
        try:
            celery_async.run_celery_async(interrupted())
        except SoftTimeLimitExceeded:
            soft_timeout_seen = True
        healthy = celery_async.run_celery_async(
            asyncio.sleep(0, result="healthy")
        )
        connection.send(
            ("ok", soft_timeout_seen, started.is_set(), cleaned, healthy)
        )
    except BaseException as exc:
        connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        if timer is not None:
            timer.cancel()
            timer.join(timeout=2)
        signal.signal(signal.SIGUSR1, previous)
        celery_async._reset_runtime_for_tests()
        connection.close()


def _run_isolated_posix_proof(
    target: Callable[[Connection], None],
) -> tuple[Any, ...]:
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(child_connection,))
    process.start()
    child_connection.close()
    try:
        process.join(timeout=30)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        assert process.exitcode == 0
        assert parent_connection.poll(timeout=2)
        result = parent_connection.recv()
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        parent_connection.close()
    assert result[0] == "ok", result
    return result[1:]


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX fork")
def test_real_fork_boundary_preserves_parent_runtime() -> None:
    child_result, parent_result, proof_pid, parent_preserved, parent_loop_closed = (
        _run_isolated_posix_proof(_fork_proof_process)
    )
    first, second, owner_pid, shutdown_complete = child_result

    assert first[0] == second[0] == owner_pid
    assert first[0] != proof_pid
    assert first[1] == second[1]
    assert shutdown_complete
    assert parent_result == proof_pid
    assert parent_preserved
    assert not parent_loop_closed


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX signals")
def test_real_signal_soft_timeout_cancels_and_keeps_runtime_healthy() -> None:
    soft_timeout_seen, started, cleaned, healthy = _run_isolated_posix_proof(
        _signal_proof_process
    )

    assert soft_timeout_seen
    assert started
    assert cleaned
    assert healthy == "healthy"
