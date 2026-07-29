"""Process-local asyncio lifecycle for Celery prefork children.

Normal child shutdown is best effort. A hard process kill cannot run Python
cleanup; the operating system is then responsible for closing process sockets.
"""

import asyncio
import inspect
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from celery import signals

from core.database import (
    block_async_database_state_creation,
    dispose_async_database_state,
    reset_async_database_state_after_fork,
)

logger = logging.getLogger(__name__)

_CLEANUP_TIMEOUT_SECONDS = 2.0
_IMPORT_PID = os.getpid()
_T = TypeVar("_T")


@dataclass
class _ChildRuntime:
    loop: asyncio.AbstractEventLoop
    owner_pid: int
    owner_thread_id: int
    running: bool = False
    broken: bool = False


_runtime: _ChildRuntime | None = None


def _close_unstarted_awaitable(awaitable: object) -> None:
    if inspect.iscoroutine(awaitable):
        awaitable.close()


def _initialize_runtime() -> _ChildRuntime:
    global _runtime

    current_pid = os.getpid()
    current_thread_id = threading.get_ident()
    runtime = _runtime
    if runtime is not None:
        if runtime.owner_pid != current_pid:
            _runtime = None
        elif runtime.owner_thread_id != current_thread_id:
            raise RuntimeError("Celery async runtime cannot cross threads")
        elif runtime.loop.is_closed():
            raise RuntimeError("Celery async runtime loop is closed")
        else:
            return runtime

    reset_async_database_state_after_fork()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runtime = _ChildRuntime(
        loop=loop,
        owner_pid=current_pid,
        owner_thread_id=current_thread_id,
    )
    _runtime = runtime
    return runtime


async def _cancel_and_drain(tasks: set[asyncio.Task[object]]) -> None:
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=_CLEANUP_TIMEOUT_SECONDS)
    for task in done:
        if not task.cancelled():
            task.exception()
    if pending:
        raise TimeoutError("Celery async task cancellation exceeded its deadline")


def _invocation_tasks(
    loop: asyncio.AbstractEventLoop,
    baseline: set[asyncio.Task[object]],
) -> set[asyncio.Task[object]]:
    return {
        task
        for task in asyncio.all_tasks(loop)
        if task not in baseline and not task.done()
    }


def _drain_invocation_tasks(
    runtime: _ChildRuntime,
    baseline: set[asyncio.Task[object]],
) -> None:
    tasks = _invocation_tasks(runtime.loop, baseline)
    if tasks:
        runtime.loop.run_until_complete(_cancel_and_drain(tasks))
    if _invocation_tasks(runtime.loop, baseline):
        raise RuntimeError("Celery async invocation left pending tasks")


def run_celery_async(
    awaitable_or_factory: Awaitable[_T] | Callable[[], Awaitable[_T]],
) -> _T:
    """Run one task invocation on its prefork child's persistent loop."""
    global _runtime

    supplied_awaitable = not callable(awaitable_or_factory)
    try:
        runtime = _initialize_runtime()
    except BaseException:
        if supplied_awaitable:
            _close_unstarted_awaitable(awaitable_or_factory)
        raise
    if runtime.broken:
        if supplied_awaitable:
            _close_unstarted_awaitable(awaitable_or_factory)
        raise RuntimeError("Celery async runtime is unavailable after failed cleanup")
    if runtime.running or runtime.loop.is_running():
        if supplied_awaitable:
            _close_unstarted_awaitable(awaitable_or_factory)
        raise RuntimeError("Nested or concurrent Celery async execution is forbidden")

    baseline = set(asyncio.all_tasks(runtime.loop))
    awaitable = (
        awaitable_or_factory()
        if callable(awaitable_or_factory)
        else awaitable_or_factory
    )
    if not inspect.isawaitable(awaitable):
        raise TypeError("Celery async wrapper requires an awaitable or awaitable factory")

    root = runtime.loop.create_task(awaitable)
    runtime.running = True
    original_error: BaseException | None = None
    result: _T | None = None
    try:
        result = runtime.loop.run_until_complete(root)
    except BaseException as exc:
        original_error = exc
    finally:
        runtime.running = False

    try:
        _drain_invocation_tasks(runtime, baseline)
    except BaseException as cleanup_error:
        runtime.broken = True
        logger.error(
            "Celery async invocation cleanup failed (%s)",
            type(cleanup_error).__name__,
        )
        if original_error is None:
            raise RuntimeError("Celery async invocation cleanup failed") from cleanup_error

    if original_error is not None:
        raise original_error.with_traceback(original_error.__traceback__)
    return result  # type: ignore[return-value]


async def _shutdown_runtime(runtime: _ChildRuntime) -> None:
    block_async_database_state_creation()
    current = asyncio.current_task()
    pending = {
        task
        for task in asyncio.all_tasks(runtime.loop)
        if task is not current and not task.done()
    }
    try:
        await _cancel_and_drain(pending)
    except BaseException as exc:
        logger.error("Celery pending-task shutdown failed (%s)", type(exc).__name__)

    try:
        await dispose_async_database_state()
    except BaseException as exc:
        logger.error("Celery database disposal failed (%s)", type(exc).__name__)

    try:
        await runtime.loop.shutdown_asyncgens()
    except BaseException as exc:
        logger.error("Celery async-generator shutdown failed (%s)", type(exc).__name__)

    shutdown_executor = getattr(runtime.loop, "shutdown_default_executor", None)
    if shutdown_executor is not None:
        try:
            await shutdown_executor()
        except BaseException as exc:
            logger.error("Celery executor shutdown failed (%s)", type(exc).__name__)


def _shutdown_current_runtime() -> None:
    global _runtime

    runtime = _runtime
    if runtime is None:
        return
    if runtime.owner_pid != os.getpid():
        _runtime = None
        return
    if runtime.owner_thread_id != threading.get_ident():
        logger.error("Celery async shutdown ignored on a foreign thread")
        return

    try:
        if not runtime.loop.is_closed():
            runtime.loop.run_until_complete(_shutdown_runtime(runtime))
    except BaseException as exc:
        logger.error("Celery async runtime shutdown failed (%s)", type(exc).__name__)
    finally:
        if not runtime.loop.is_closed():
            runtime.loop.close()
        _runtime = None
        asyncio.set_event_loop(None)


@signals.worker_process_init.connect(weak=False)
def _on_worker_process_init(**_: object) -> None:
    if os.getpid() == _IMPORT_PID:
        logger.debug("Celery async runtime initialization deferred outside prefork child")
        return
    _initialize_runtime()


@signals.worker_process_shutdown.connect(weak=False)
def _on_worker_process_shutdown(**_: object) -> None:
    _shutdown_current_runtime()


def _reset_runtime_for_tests() -> None:
    """Reset local runtime state; production task code must not call this hook."""
    _shutdown_current_runtime()
    reset_async_database_state_after_fork()
